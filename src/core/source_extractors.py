"""从 Markdown、SQL 与 JSONL 中抽取样本的通用加载器。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List


# 各来源 pipeline 共用的 CASE 块匹配规则。
MD_CASE_PATTERN = re.compile(
    r"### CASE\s+"
    r"(?P<meta>(?:[a-z_]+:\s.*\n)+)"
    r"```sql\n(?P<sql>.*?)\n```",
    re.DOTALL | re.IGNORECASE,
)

SQL_CASE_PATTERN = re.compile(
    r"-- CASE\s+"
    r"(?P<meta>(?:-- [a-z_]+:\s.*\n)+)"
    r"(?P<sql>.*?;)\n(?=(?:-- CASE|$))",
    re.DOTALL | re.IGNORECASE,
)


def parse_meta_block(meta_text: str, comment_prefix: str = "") -> Dict[str, str]:
    # 将元数据块解析为规范化的键值映射。
    meta: Dict[str, str] = {}
    for raw_line in meta_text.strip().splitlines():
        line = raw_line.strip()
        if comment_prefix and line.startswith(comment_prefix):
            line = line[len(comment_prefix) :].strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    return meta


def extract_from_markdown(file_path: Path) -> List[Dict[str, str]]:
    text = file_path.read_text(encoding="utf-8")
    rows: List[Dict[str, str]] = []
    for match in MD_CASE_PATTERN.finditer(text):
        meta = parse_meta_block(match.group("meta"))
        meta["sql_text"] = " ".join(match.group("sql").strip().split())
        rows.append(meta)
    return rows


def extract_from_sql(file_path: Path) -> List[Dict[str, str]]:
    text = file_path.read_text(encoding="utf-8")
    rows: List[Dict[str, str]] = []
    for match in SQL_CASE_PATTERN.finditer(text + "\n"):
        meta = parse_meta_block(match.group("meta"), comment_prefix="-- ")
        meta["sql_text"] = " ".join(match.group("sql").strip().split())
        rows.append(meta)
    return rows


def extract_from_log_jsonl(file_path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        payload["sql_text"] = " ".join(str(payload["sql_text"]).strip().split())
        rows.append({key: str(value) for key, value in payload.items()})
    return rows


def load_source_material_rows(source_dir: Path) -> List[Dict[str, str]]:
    # 递归加载目录下所有支持的来源文件。
    rows: List[Dict[str, str]] = []
    for file_path in sorted(source_dir.rglob("*.md")):
        rows.extend(extract_from_markdown(file_path))
    for file_path in sorted(source_dir.rglob("*.sql")):
        rows.extend(extract_from_sql(file_path))
    for file_path in sorted(source_dir.rglob("*.jsonl")):
        rows.extend(extract_from_log_jsonl(file_path))
    return rows
