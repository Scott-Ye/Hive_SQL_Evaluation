"""抓取并规范化 Apache Hive 开源 benchmark 查询文件。"""

from __future__ import annotations

import json
import re
from http.client import IncompleteRead, RemoteDisconnected
from pathlib import Path
from typing import Dict, List
from urllib.error import URLError
from urllib.request import Request, urlopen

from src.core.progress import print_kv, print_progress, print_stage
from src.core.project_config import OPEN_BENCHMARK_JSONL
from src.pipelines.official_doc_pipeline import infer_real_meta, is_sql_like

GITHUB_API_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/vnd.github+json",
}

# 各目录 API 与预期 GT pass/fail 状态的映射关系。
GITHUB_DIR_APIS = [
    (
        "clientpositive",
        "https://api.github.com/repos/apache/hive/contents/ql/src/test/queries/clientpositive?ref=master",
        "pass",
    ),
    (
        "clientnegative",
        "https://api.github.com/repos/apache/hive/contents/ql/src/test/queries/clientnegative?ref=master",
        "fail",
    ),
    (
        "positive",
        "https://api.github.com/repos/apache/hive/contents/ql/src/test/queries/positive?ref=master",
        "pass",
    ),
    (
        "negative",
        "https://api.github.com/repos/apache/hive/contents/ql/src/test/queries/negative?ref=master",
        "fail",
    ),
]

MAX_FILES_PER_SOURCE = {
    "clientpositive": 180,
    "clientnegative": 180,
    "positive": 120,
    "negative": 160,
}

BLOCK_COMMENT_PATTERN = re.compile(r"/\*.*?\*/", re.DOTALL)
LINE_COMMENT_PATTERN = re.compile(r"^\s*(--|#).*$", re.MULTILINE)
IGNORE_PREFIXES = (
    "set ",
    "reset ",
    "dfs ",
    "add ",
    "list ",
    "reload ",
    "compile ",
    "delete from junit_",
)


def http_get_text(url: str) -> str:
    last_error: Exception | None = None
    for _ in range(3):
        try:
            request = Request(url, headers=GITHUB_API_HEADERS)
            with urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", errors="ignore")
        except (IncompleteRead, TimeoutError, URLError, RemoteDisconnected) as exc:
            # benchmark 来源依赖 GitHub 网络，请求失败时做有限次重试。
            last_error = exc
            continue
    raise RuntimeError(f"Failed to fetch benchmark source: {url}") from last_error


def http_get_json(url: str) -> object:
    return json.loads(http_get_text(url))


def list_query_files() -> List[Dict[str, str]]:
    files: List[Dict[str, str]] = []
    print_stage("发现 Apache Hive benchmark 文件")
    for source_name, api_url, expected_status in GITHUB_DIR_APIS:
        payload = http_get_json(api_url)
        kept = 0
        for item in payload:
            if kept >= MAX_FILES_PER_SOURCE[source_name]:
                break
            if item.get("type") != "file":
                continue
            if not str(item.get("name", "")).endswith(".q"):
                continue
            files.append(
                {
                    "source_name": source_name,
                    "expected_status": expected_status,
                    "download_url": item["download_url"],
                    "source_ref": item["html_url"],
                }
            )
            kept += 1
        # 每个目录做上限控制，避免单一来源过大挤占总样本配额。
        print_kv(f"{source_name} 文件数", kept)
    return files


def clean_query_file(text: str) -> str:
    # 先移除块注释和行注释，降低后续按分号切分时的噪声。
    text = BLOCK_COMMENT_PATTERN.sub(" ", text)
    text = LINE_COMMENT_PATTERN.sub(" ", text)
    return text


def split_sql_statements(text: str) -> List[str]:
    # 基准测试文件中可能混有环境准备命令与 SQL 语句。
    statements: List[str] = []
    for chunk in text.split(";"):
        sql = " ".join(chunk.strip().split())
        if not sql:
            continue
        if any(sql.lower().startswith(prefix) for prefix in IGNORE_PREFIXES):
            continue
        if not is_sql_like(sql):
            continue
        if "${" in sql:
            continue
        if len(sql) > 800:
            continue
        statements.append(sql)
    return statements


def apply_benchmark_gt(row: Dict[str, str], *, source_name: str, declared_status: str) -> Dict[str, str]:
    # benchmark 的 GT 主要来自目录语义：positive 视为 pass，negative 视为 fail。
    gt_strength = "strong" if declared_status == "pass" else "weak"
    gt_error_type = "" if declared_status == "pass" else "parse_error"
    note_suffix = "positive directory assertion" if declared_status == "pass" else "negative directory assertion"
    tags = ["real", "open_benchmark", row["level1_category"].lower(), declared_status]
    if declared_status == "fail":
        tags.append("weak_gt")

    row["gt_status"] = declared_status
    row["gt_error_type"] = gt_error_type
    row["gt_error_subtype"] = ""
    row["gt_label_source"] = f"open_benchmark_{source_name}_directory"
    row["gt_label_strength"] = gt_strength
    row["baseline_status"] = ""
    row["baseline_error_type"] = ""
    row["baseline_error_subtype"] = ""
    row["baseline_error_type_raw"] = ""
    row["baseline_error_subtype_raw"] = ""
    row["baseline_error_position"] = ""
    row["baseline_label_source"] = ""
    row["notes"] = f"Auto-extracted from Apache Hive open-source query test suite | {note_suffix}"
    row["tags"] = ";".join(tags)
    return row


def extract_open_benchmark_rows() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    file_list = list_query_files()
    print_stage("抽取 Apache Hive benchmark SQL")
    for index, file_meta in enumerate(file_list, start=1):
        try:
            text = http_get_text(file_meta["download_url"])
        except RuntimeError:
            continue
        statements = split_sql_statements(clean_query_file(text))
        if not statements:
            continue

        # 对负样本文件，仅保留最后一条语句作为代表性失败样本。
        selected_statements = statements if file_meta["expected_status"] == "pass" else [statements[-1]]
        for sql_text in selected_statements:
            row = infer_real_meta(sql_text, file_meta["source_ref"])
            row["source"] = f"apache_hive_{file_meta['source_name']}"
            row["source_ref"] = file_meta["source_ref"]
            rows.append(
                apply_benchmark_gt(
                    row,
                    source_name=file_meta["source_name"],
                    declared_status=file_meta["expected_status"],
                )
            )
        print_progress("benchmark 抽取", index, len(file_list), item=file_meta["source_name"])
    return rows


def write_open_benchmark_jsonl(rows: List[Dict[str, str]]) -> None:
    OPEN_BENCHMARK_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with OPEN_BENCHMARK_JSONL.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _baseline_key(row: Dict[str, str]) -> tuple[str, str, str]:
    return (" ".join(row.get("sql_text", "").lower().split()), row.get("source", ""), row.get("source_ref", ""))


def _merge_existing_baselines(new_rows: List[Dict[str, str]], cached_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    # 刷新缓存样本时，保留已经冻结的 baseline 字段。
    baseline_by_key = {
        _baseline_key(row): row
        for row in cached_rows
        if row.get("baseline_label_source") or row.get("baseline_status")
    }
    merged_rows: List[Dict[str, str]] = []
    for row in new_rows:
        copied = dict(row)
        cached = baseline_by_key.get(_baseline_key(row))
        if cached:
            for field in (
                "baseline_status",
                "baseline_error_type",
                "baseline_error_subtype",
                "baseline_error_type_raw",
                "baseline_error_subtype_raw",
                "baseline_error_position",
                "baseline_label_source",
            ):
                copied[field] = cached.get(field, copied.get(field, ""))
            if "baseline=local_hive_parse_sdk" in cached.get("notes", "") and "baseline=local_hive_parse_sdk" not in copied.get(
                "notes", ""
            ):
                copied["notes"] = f"{copied.get('notes', '')} | baseline=local_hive_parse_sdk".strip(" |")
        merged_rows.append(copied)
    return merged_rows


def load_cached_open_benchmark_rows() -> List[Dict[str, str]]:
    if not OPEN_BENCHMARK_JSONL.exists():
        return []
    rows: List[Dict[str, str]] = []
    needs_rewrite = False
    with OPEN_BENCHMARK_JSONL.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if "gt_error_position" in payload:
                payload.pop("gt_error_position", None)
                needs_rewrite = True
            rows.append(payload)
    if any("gt_status" not in row for row in rows):
        # 旧缓存缺少 GT 字段时，直接整批重抽一次，避免混合新旧 schema。
        refreshed_rows = extract_open_benchmark_rows()
        write_open_benchmark_jsonl(refreshed_rows)
        return refreshed_rows
    if needs_rewrite:
        write_open_benchmark_jsonl(rows)
    return rows


def refresh_open_benchmark_sources(force_refresh: bool = False) -> Dict[str, object]:
    cached_rows = load_cached_open_benchmark_rows()
    if not force_refresh:
        if cached_rows:
            negative_count = sum(1 for row in cached_rows if row["gt_status"] == "fail")
            print_stage("使用缓存的 Apache Hive benchmark 候选池")
            print_kv("benchmark 缓存样本数", len(cached_rows))
            return {
                "open_benchmark_case_count": len(cached_rows),
                "open_benchmark_negative_count": negative_count,
                "jsonl_path": str(OPEN_BENCHMARK_JSONL),
                "cache_hit": True,
            }

    # 强制刷新时重新联网抓取，再把旧 baseline 合并回新样本。
    rows = extract_open_benchmark_rows()
    rows = _merge_existing_baselines(rows, cached_rows)
    write_open_benchmark_jsonl(rows)
    negative_count = sum(1 for row in rows if row["gt_status"] == "fail")
    print_kv("benchmark 抽取样本数", len(rows))
    print_kv("benchmark 负样本数", negative_count)
    return {
        "open_benchmark_case_count": len(rows),
        "open_benchmark_negative_count": negative_count,
        "jsonl_path": str(OPEN_BENCHMARK_JSONL),
        "cache_hit": False,
    }
