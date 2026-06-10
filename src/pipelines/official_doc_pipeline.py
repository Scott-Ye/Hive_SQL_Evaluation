"""抓取、缓存并抽取 Hive 官方文档中的 SQL 示例。"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit, urlunsplit
from typing import Dict, List
from urllib.request import Request, urlopen

from src.core.progress import print_kv, print_progress, print_stage
from src.core.project_config import REAL_EXTRACTED_JSONL, REAL_HTML_CACHE_DIR


# 用于发现最新官方文档页面的种子 URL。
SEED_OFFICIAL_DOC_URLS = [
    "https://hive.apache.org/docs/latest/language/languagemanual/",
    "https://hive.apache.org/docs/latest/language/languagemanual-ddl/",
    "https://hive.apache.org/docs/latest/language/languagemanual-dml/",
    "https://hive.apache.org/docs/latest/language/languagemanual-select/",
    "https://hive.apache.org/docs/latest/language/languagemanual-windowingandanalytics/",
    "https://hive.apache.org/docs/latest/language/languagemanual-joins/",
    "https://hive.apache.org/docs/latest/language/languagemanual-union/",
    "https://hive.apache.org/docs/latest/language/languagemanual-lateralview/",
    "https://hive.apache.org/docs/latest/language/languagemanual-groupby/",
    "https://hive.apache.org/docs/latest/language/languagemanual-sortby/",
    "https://hive.apache.org/docs/latest/language/languagemanual-subqueries/",
    "https://hive.apache.org/docs/latest/language/languagemanual-udf/",
    "https://hive.apache.org/docs/latest/language/languagemanual-transform/",
    "https://hive.apache.org/docs/latest/language/enhanced-aggregation-cube-grouping-and-rollup/",
    "https://hive.apache.org/docs/latest/languagemanual-explain_27362037/",
    "https://hive.apache.org/docs/latest/languagemanual-types_27838462/",
    "https://hive.apache.org/docs/latest/configuration-properties_27842758/",
]

CODE_BLOCK_PATTERN = re.compile(
    r"<pre[^>]*>\s*<code[^>]*>(?P<code>.*?)</code>\s*</pre>",
    re.IGNORECASE | re.DOTALL,
)
TAG_PATTERN = re.compile(r"<[^>]+>")
HREF_PATTERN = re.compile(r'href=["\'](?P<href>[^"\']+)["\']', re.IGNORECASE)

SQL_PREFIXES = (
    "CREATE ",
    "DROP ",
    "ALTER ",
    "USE ",
    "LOAD ",
    "INSERT ",
    "FROM ",
    "SELECT ",
    "WITH ",
    "EXPLAIN ",
    "SHOW ",
    "DESCRIBE ",
)

PLACEHOLDER_TOKENS = (
    "DATABASE_NAME",
    "TABLE_NAME",
    "DB_NAME",
    "HDFS_PATH",
    "FILEPATH",
    "PARTITION_SPEC",
    "PROPERTY_NAME",
    "PROPERTY_VALUE",
    "SELECT_STATEMENT",
    "FROM_STATEMENT",
    "ROW_FORMAT",
    "SERDE_PROPERTIES",
    "EXISTING_TABLE_OR_VIEW_NAME",
    "DATATYPE",
    "COLUMN_CONSTRAINT_SPECIFICATION",
    "CONSTRAINT_SPECIFICATION",
)
MAX_DISCOVERED_PAGES = 40


def slugify_url(url: str) -> str:
    slug = url.replace("https://", "").replace("http://", "")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", slug).strip("_")
    return slug


def fetch_official_html(url: str) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="ignore")
    except HTTPError as exc:
        return exc.read().decode("utf-8", errors="ignore")


def normalize_doc_url(base_url: str, href: str) -> str:
    absolute = urljoin(base_url, href)
    parsed = urlsplit(absolute)
    normalized = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return normalized


def should_follow_url(url: str) -> bool:
    # 只追踪 Hive docs 主站里的语言手册类页面，避免图片、压缩包等无关资源。
    if not url.startswith("https://hive.apache.org/docs/latest/"):
        return False
    lower_url = url.lower()
    if any(lower_url.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".zip")):
        return False
    return (
        "/docs/latest/language/" in lower_url
        or "enhanced-aggregation-cube-grouping-and-rollup" in lower_url
        or "languagemanual" in lower_url
    )


def discover_official_doc_urls(seed_urls: List[str] | None = None) -> List[str]:
    # 按广度优先方式抓取 Hive 文档，直到达到页面数量上限。
    seed_urls = seed_urls or SEED_OFFICIAL_DOC_URLS
    queue = list(dict.fromkeys(seed_urls))
    discovered: List[str] = []
    seen = set()
    print_stage("发现 Hive 官方文档页面")

    while queue and len(discovered) < MAX_DISCOVERED_PAGES:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            html_text = fetch_official_html(url)
        except Exception:
            continue

        discovered.append(url)
        print_progress("官方文档发现", len(discovered), MAX_DISCOVERED_PAGES, item=url)
        for match in HREF_PATTERN.finditer(html_text):
            next_url = normalize_doc_url(url, match.group("href"))
            if next_url in seen or next_url in queue:
                continue
            if not should_follow_url(next_url):
                continue
            queue.append(next_url)
    return discovered


def cache_official_pages(urls: List[str] | None = None) -> List[Path]:
    urls = urls or discover_official_doc_urls()
    REAL_HTML_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached_paths: List[Path] = []
    print_stage("缓存 Hive 官方文档页面")
    for index, url in enumerate(urls, start=1):
        html_text = fetch_official_html(url)
        slug = slugify_url(url)
        html_path = REAL_HTML_CACHE_DIR / f"{slug}.html"
        meta_path = REAL_HTML_CACHE_DIR / f"{slug}.json"
        # html 与 source_ref 分开落盘，后续抽取时就不需要再次请求网络。
        html_path.write_text(html_text, encoding="utf-8")
        meta_path.write_text(
            json.dumps({"source_ref": url}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        cached_paths.append(html_path)
        print_progress("官方文档缓存", index, len(urls), item=slug)
    return cached_paths


def html_code_to_text(code_html: str) -> str:
    text = html.unescape(code_html)
    text = TAG_PATTERN.sub("", text)
    text = text.replace("\xa0", " ")
    return " ".join(text.strip().split())


def is_sql_like(code_text: str) -> bool:
    upper_text = code_text.upper()
    if any(upper_text.startswith(prefix) for prefix in SQL_PREFIXES):
        return True
    return "SELECT " in upper_text and " FROM " in upper_text


def infer_real_meta(sql_text: str, source_ref: str) -> Dict[str, str]:
    # 只保留看起来可以直接执行的 SQL 代码块。
    upper_sql = sql_text.upper()
    level1 = "UTILITY"
    level2 = "OTHER"
    difficulty = "medium"

    if upper_sql.startswith("CREATE "):
        level1 = "DDL"
        level2 = "CREATE_TABLE_SYNTAX" if "TABLE" in upper_sql else "CREATE_DATABASE_SYNTAX"
    elif upper_sql.startswith("DROP "):
        level1 = "DDL"
        level2 = "DROP_DATABASE_SYNTAX" if "DATABASE" in upper_sql or "SCHEMA" in upper_sql else "DROP_TABLE_SYNTAX"
    elif upper_sql.startswith("ALTER "):
        level1 = "DDL"
        level2 = "ALTER_TABLE_SYNTAX"
    elif upper_sql.startswith("LOAD "):
        level1 = "DML"
        level2 = "LOAD_DATA_SYNTAX"
    elif upper_sql.startswith("INSERT OVERWRITE "):
        level1 = "DML"
        level2 = "INSERT_OVERWRITE_SYNTAX"
    elif upper_sql.startswith("INSERT INTO "):
        level1 = "DML"
        level2 = "INSERT_INTO_SYNTAX"
    elif upper_sql.startswith("USE "):
        level1 = "UTILITY"
        level2 = "USE_DB"
        difficulty = "easy"
    elif upper_sql.startswith("SELECT "):
        level1 = "QUERY"
        if " LATERAL VIEW " in upper_sql:
            level2 = "LATERAL_VIEW"
            difficulty = "hard"
        elif " UNION " in upper_sql:
            level2 = "UNION"
            difficulty = "hard"
        elif " JOIN " in upper_sql:
            level2 = "JOIN"
        elif " OVER " in upper_sql:
            level2 = "WINDOW"
            difficulty = "hard"
        elif " GROUP BY " in upper_sql:
            level2 = "GROUP_BY"
        elif " HAVING " in upper_sql:
            level2 = "HAVING"
        elif " ORDER BY " in upper_sql or " SORT BY " in upper_sql:
            level2 = "ORDER_SORT"
        elif " LIMIT " in upper_sql:
            level2 = "LIMIT"
            difficulty = "easy"
        elif " WHERE " in upper_sql:
            level2 = "WHERE_FILTER"
        else:
            level2 = "SELECT_BASIC"
            difficulty = "easy"
    elif upper_sql.startswith("WITH "):
        level1 = "QUERY"
        level2 = "CTE"
        difficulty = "hard"
    elif upper_sql.startswith("FROM "):
        level1 = "QUERY"
        if " TRANSFORM(" in upper_sql or " MAP " in upper_sql or " REDUCE " in upper_sql:
            level2 = "TRANSFORM"
        else:
            level2 = "INSERT_FROM"
        difficulty = "hard"
    elif upper_sql.startswith("EXPLAIN "):
        level1 = "UTILITY"
        level2 = "EXPLAIN"

    return {
        "level1_category": level1,
        "level2_category": level2,
        "difficulty": difficulty,
        "gt_status": "pass",
        "gt_error_type": "",
        "gt_error_subtype": "",
        "gt_label_source": "official_doc_example",
        "gt_label_strength": "strong",
        "baseline_status": "",
        "baseline_error_type": "",
        "baseline_error_subtype": "",
        "baseline_error_type_raw": "",
        "baseline_error_subtype_raw": "",
        "baseline_error_position": "",
        "baseline_label_source": "",
        "sql_text": sql_text,
        "source_tier": "real",
        "source": "hive_official_docs",
        "source_ref": source_ref,
        "tags": f"real;{level1.lower()};{level2.lower()}",
        "notes": "Auto-extracted from Apache Hive official documentation code block",
    }


def is_real_example_case(sql_text: str) -> bool:
    # 过滤文档里的占位写法、命令行示例和过长片段，尽量留下可直接评测的真实 SQL。
    upper_sql = sql_text.upper()

    if "[" in sql_text or "]" in sql_text:
        return False
    if "..." in sql_text:
        return False
    if "-- (NOTE:" in upper_sql or "//" in sql_text:
        return False
    if " : " in sql_text:
        return False
    if len(sql_text) > 500:
        return False
    if sql_text.count(";") > 1:
        return False
    if "HIVE>" in upper_sql:
        return False
    if any(token in upper_sql for token in PLACEHOLDER_TOKENS):
        return False
    return True


def extract_cases_from_cached_html() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    if not REAL_HTML_CACHE_DIR.exists():
        return rows

    html_paths = sorted(REAL_HTML_CACHE_DIR.glob("*.html"))
    print_stage("抽取 Hive 官方文档 SQL")
    for index, html_path in enumerate(html_paths, start=1):
        meta_path = html_path.with_suffix(".json")
        if not meta_path.exists():
            continue
        source_ref = json.loads(meta_path.read_text(encoding="utf-8"))["source_ref"]
        html_text = html_path.read_text(encoding="utf-8")
        for match in CODE_BLOCK_PATTERN.finditer(html_text):
            code_text = html_code_to_text(match.group("code"))
            if not code_text or not is_sql_like(code_text):
                continue
            # 文档页里的代码块很多，这里只把识别出的 SQL 代码块转换成候选样本。
            rows.append(infer_real_meta(code_text, source_ref))
        print_progress("官方 SQL 抽取", index, len(html_paths), item=html_path.stem)
    return rows


def write_real_cases_jsonl(rows: List[Dict[str, str]]) -> None:
    REAL_EXTRACTED_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with REAL_EXTRACTED_JSONL.open("w", encoding="utf-8") as handle:
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


def load_cached_real_rows() -> List[Dict[str, str]]:
    if not REAL_EXTRACTED_JSONL.exists():
        return []
    rows: List[Dict[str, str]] = []
    needs_rewrite = False
    with REAL_EXTRACTED_JSONL.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if "gt_status" not in payload:
                # 兼容旧版缓存字段名，读到后顺手升级并回写。
                payload["gt_status"] = payload.get("expected_status", "")
                payload["gt_error_type"] = payload.get("expected_error_type", "")
                payload["gt_error_subtype"] = payload.get("expected_error_subtype", "")
                payload["gt_label_source"] = "official_doc_example"
                payload["gt_label_strength"] = "strong"
                payload["baseline_status"] = ""
                payload["baseline_error_type"] = ""
                payload["baseline_error_subtype"] = ""
                payload["baseline_error_type_raw"] = ""
                payload["baseline_error_subtype_raw"] = ""
                payload["baseline_error_position"] = ""
                payload["baseline_label_source"] = ""
                needs_rewrite = True
            if "gt_error_position" in payload:
                payload.pop("gt_error_position", None)
                needs_rewrite = True
            rows.append(payload)
    if needs_rewrite:
        write_real_cases_jsonl(rows)
    return rows


def refresh_real_official_sources(force_refresh: bool = False) -> Dict[str, object]:
    cached_rows = load_cached_real_rows()
    if not force_refresh:
        if cached_rows and REAL_HTML_CACHE_DIR.exists():
            print_stage("使用缓存的 Hive 官方文档候选池")
            print_kv("官方缓存样本数", len(cached_rows))
            return {
                "official_page_count": len(list(REAL_HTML_CACHE_DIR.glob("*.html"))),
                "extracted_case_count": len(cached_rows),
                "jsonl_path": str(REAL_EXTRACTED_JSONL),
                "cache_hit": True,
            }

    # 强制刷新时重新发现页面、重建缓存，再把旧 baseline 合并回新样本。
    official_urls = discover_official_doc_urls()
    cache_official_pages(official_urls)
    rows = extract_cases_from_cached_html()
    rows = _merge_existing_baselines(rows, cached_rows)
    write_real_cases_jsonl(rows)
    print_kv("官方页面数", len(official_urls))
    print_kv("官方抽取样本数", len(rows))
    return {
        "official_page_count": len(official_urls),
        "extracted_case_count": len(rows),
        "jsonl_path": str(REAL_EXTRACTED_JSONL),
        "cache_hit": False,
    }
