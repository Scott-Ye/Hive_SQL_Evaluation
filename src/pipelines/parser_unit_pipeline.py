from __future__ import annotations

import json
import re
from typing import Dict, List
from urllib.error import URLError
from urllib.request import Request, urlopen

from src.core.progress import print_kv, print_progress, print_stage
from src.core.project_config import PARSER_UNIT_JSONL
from src.pipelines.official_doc_pipeline import infer_real_meta, is_sql_like

GITHUB_API_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/vnd.github+json",
}

PARSER_TEST_TREE_API = "https://api.github.com/repos/apache/hive/git/trees/master?recursive=1"

EXCLUDED_TEST_FILES = {"HqlParser.java"}

STRING_ASSIGN_PATTERN = re.compile(
    r"String\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<expr>.*?);",
    re.DOTALL,
)
SQL11_KEYWORDS_PATTERN = re.compile(r'\{\s*"(?P<keyword>[^"]+)"\s*\}')
RESERVED_KEYWORDS_BLOCK_PATTERN = re.compile(r"Arrays\.asList\((?P<body>.*?)\);", re.DOTALL)
STRING_LITERAL_PATTERN = re.compile(r'"((?:\\.|[^"])*)"')
PARSE_FUNCTION_NAMES = ("parseDriver.parse", "parseDriver.parseSelect", "parse")
NEGATIVE_FILE_HINTS = ("negative", "invalid", "error", "quote", "quoted", "reserved", "unsupported")


def infer_parser_unit_gt(file_name: str, sql_text: str) -> Dict[str, str]:
    lower_name = file_name.lower()
    gt_status = "fail" if any(hint in lower_name for hint in NEGATIVE_FILE_HINTS) else "pass"
    gt_error_type = ""
    gt_error_subtype = ""
    gt_strength = "medium"
    gt_label_source = f"parser_unit_file_heuristic:{file_name}"

    if gt_status == "fail":
        gt_error_type = "parse_error"
        if "reserved" in lower_name:
            gt_error_subtype = "reserved_keyword_table_name"
            gt_strength = "strong"
        elif "quote" in lower_name:
            gt_error_subtype = "quoted_identifier_path_syntax"
            gt_strength = "strong"
        elif "cte" in lower_name:
            gt_error_subtype = "cte_syntax"
        elif "window" in lower_name or "withingroup" in lower_name:
            gt_error_subtype = "window_clause_syntax"

    return {
        "gt_status": gt_status,
        "gt_error_type": gt_error_type,
        "gt_error_subtype": gt_error_subtype,
        "gt_label_source": gt_label_source,
        "gt_label_strength": gt_strength,
        "baseline_status": "",
        "baseline_error_type": "",
        "baseline_error_subtype": "",
        "baseline_error_type_raw": "",
        "baseline_error_subtype_raw": "",
        "baseline_error_position": "",
        "baseline_label_source": "",
    }


def http_get_text(url: str) -> str:
    request = Request(url, headers=GITHUB_API_HEADERS)
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="ignore")


def http_get_json(url: str) -> object:
    return json.loads(http_get_text(url))


def unescape_java_string(raw_text: str) -> str:
    return bytes(raw_text, "utf-8").decode("unicode_escape")


def split_top_level(expression: str, separator: str) -> List[str]:
    parts: List[str] = []
    current: List[str] = []
    depth = 0
    in_string = False
    escape = False
    for char in expression:
        if in_string:
            current.append(char)
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            current.append(char)
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        if char == separator and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    if current:
        parts.append("".join(current).strip())
    return parts


def split_first_argument(expression: str) -> str:
    return split_top_level(expression, ",")[0].strip()


def resolve_java_string_expression(expression: str, constants: Dict[str, str]) -> str | None:
    expression = expression.strip()
    if not expression:
        return None

    if expression.startswith("String.format("):
        match = re.match(
            r'String\.format\(\s*"(?P<template>(?:\\.|[^"])*)"\s*,\s*(?P<variable>[A-Za-z_][A-Za-z0-9_]*)\s*\)$',
            expression,
            re.DOTALL,
        )
        if not match:
            return None
        template = unescape_java_string(match.group("template"))
        variable_name = match.group("variable")
        variable_value = constants.get(variable_name)
        if variable_value is None:
            return None
        return template % variable_value

    parts = split_top_level(expression, "+")
    resolved: List[str] = []
    for part in parts:
        if not part:
            continue
        if part in constants:
            resolved.append(constants[part])
            continue
        string_match = re.fullmatch(r'"((?:\\.|[^"])*)"', part, re.DOTALL)
        if string_match:
            resolved.append(unescape_java_string(string_match.group(1)))
            continue
        return None
    return "".join(resolved).strip() if resolved else None


def extract_string_constants(java_text: str) -> Dict[str, str]:
    constants: Dict[str, str] = {}
    for match in STRING_ASSIGN_PATTERN.finditer(java_text):
        value = resolve_java_string_expression(match.group("expr"), constants)
        if value is not None:
            constants[match.group("name")] = value
    return constants


def _capture_parenthesized(java_text: str, open_index: int) -> str:
    depth = 0
    in_string = False
    escape = False
    captured: List[str] = []
    for char in java_text[open_index:]:
        captured.append(char)
        if in_string:
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return "".join(captured)
    return ""


def extract_parse_expressions(java_text: str) -> List[str]:
    expressions: List[str] = []
    for function_name in PARSE_FUNCTION_NAMES:
        search_from = 0
        while True:
            index = java_text.find(function_name, search_from)
            if index == -1:
                break
            open_paren_index = index + len(function_name)
            if open_paren_index >= len(java_text) or java_text[open_paren_index] != "(":
                search_from = index + len(function_name)
                continue
            captured = _capture_parenthesized(java_text, open_paren_index)
            if captured:
                expressions.append(captured[1:-1].strip())
            search_from = index + len(function_name)
    return expressions


def extract_sql11_negative_rows(java_text: str, source_ref: str) -> List[Dict[str, str]]:
    keywords = [match.group("keyword") for match in SQL11_KEYWORDS_PATTERN.finditer(java_text)]
    rows: List[Dict[str, str]] = []
    for keyword in keywords:
        sql_text = f"CREATE TABLE {keyword} (col STRING)"
        row = infer_real_meta(sql_text, source_ref)
        row["source"] = "apache_hive_parser_unit"
        row["source_ref"] = source_ref
        row.update(
            {
                "gt_status": "fail",
                "gt_error_type": "parse_error",
                "gt_error_subtype": "reserved_keyword_table_name",
                "gt_label_source": "parser_unit_explicit_negative",
                "gt_label_strength": "strong",
                "baseline_status": "",
                "baseline_error_type": "",
                "baseline_error_subtype": "",
                "baseline_error_type_raw": "",
                "baseline_error_subtype_raw": "",
                "baseline_error_position": "",
                "baseline_label_source": "",
            }
        )
        row["notes"] = "Auto-extracted from Apache Hive parser unit tests"
        row["tags"] = "real;parser_unit;reserved_keyword;strong_gt"
        rows.append(row)
    return rows


def extract_reserved_keyword_negative_rows(java_text: str, source_ref: str) -> List[Dict[str, str]]:
    match = RESERVED_KEYWORDS_BLOCK_PATTERN.search(java_text)
    if not match:
        return []
    keywords = [unescape_java_string(keyword) for keyword in STRING_LITERAL_PATTERN.findall(match.group("body"))]
    rows: List[Dict[str, str]] = []
    for keyword in keywords:
        sql_text = f"CREATE TABLE {keyword} (col STRING)"
        row = infer_real_meta(sql_text, source_ref)
        row["source"] = "apache_hive_parser_unit"
        row["source_ref"] = source_ref
        row.update(
            {
                "gt_status": "fail",
                "gt_error_type": "parse_error",
                "gt_error_subtype": "reserved_keyword_table_name",
                "gt_label_source": "parser_unit_explicit_negative",
                "gt_label_strength": "strong",
                "baseline_status": "",
                "baseline_error_type": "",
                "baseline_error_subtype": "",
                "baseline_error_type_raw": "",
                "baseline_error_subtype_raw": "",
                "baseline_error_position": "",
                "baseline_label_source": "",
            }
        )
        row["notes"] = "Auto-extracted from Apache Hive parser unit tests"
        row["tags"] = "real;parser_unit;reserved_words;strong_gt"
        rows.append(row)
    return rows


def extract_rows_from_java_test(file_name: str, download_url: str, html_url: str) -> List[Dict[str, str]]:
    java_text = http_get_text(download_url)
    constants = extract_string_constants(java_text)
    rows: List[Dict[str, str]] = []

    if file_name == "TestSQL11ReservedKeyWordsNegative.java":
        rows.extend(extract_sql11_negative_rows(java_text, html_url))
    if file_name == "TestReservedWords.java":
        rows.extend(extract_reserved_keyword_negative_rows(java_text, html_url))

    for expression in extract_parse_expressions(java_text):
        sql_text = resolve_java_string_expression(split_first_argument(expression), constants)
        if not sql_text or not is_sql_like(sql_text):
            continue
        sql_text = " ".join(sql_text.strip().split())
        if len(sql_text) > 1200:
            continue
        row = infer_real_meta(sql_text, html_url)
        row["source"] = "apache_hive_parser_unit"
        row["source_ref"] = html_url
        row.update(infer_parser_unit_gt(file_name, sql_text))
        row["notes"] = "Auto-extracted from Apache Hive parser unit tests"
        row["tags"] = f"real;parser_unit;{file_name}"
        rows.append(row)
    return rows


def list_parser_test_files() -> List[Dict[str, str]]:
    payload = http_get_json(PARSER_TEST_TREE_API)
    files: List[Dict[str, str]] = []
    print_stage("发现 Apache Hive parser unit 文件")
    for item in payload.get("tree", []):
        if item.get("type") != "blob":
            continue
        path = str(item.get("path", ""))
        if not path.startswith("parser/src/test/org/apache/hadoop/hive/ql/parse/"):
            continue
        file_name = path.rsplit("/", 1)[-1]
        if not file_name.endswith(".java") or file_name in EXCLUDED_TEST_FILES:
            continue
        files.append(
            {
                "name": file_name,
                "download_url": f"https://raw.githubusercontent.com/apache/hive/master/{path}",
                "html_url": f"https://github.com/apache/hive/blob/master/{path}",
            }
        )
    print_kv("parser unit 测试文件数", len(files))
    return files


def extract_parser_unit_rows() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    file_list = list_parser_test_files()
    print_stage("抽取 Apache Hive parser unit SQL")
    for index, file_meta in enumerate(file_list, start=1):
        try:
            rows.extend(
                extract_rows_from_java_test(
                    file_meta["name"],
                    file_meta["download_url"],
                    file_meta["html_url"],
                )
            )
        except URLError:
            continue
        print_progress("parser unit 抽取", index, len(file_list), item=file_meta["name"])
    return rows


def write_parser_unit_jsonl(rows: List[Dict[str, str]]) -> None:
    PARSER_UNIT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with PARSER_UNIT_JSONL.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _baseline_key(row: Dict[str, str]) -> tuple[str, str, str]:
    return (" ".join(row.get("sql_text", "").lower().split()), row.get("source", ""), row.get("source_ref", ""))


def _merge_existing_baselines(new_rows: List[Dict[str, str]], cached_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
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


def load_cached_parser_unit_rows() -> List[Dict[str, str]]:
    if not PARSER_UNIT_JSONL.exists():
        return []
    rows: List[Dict[str, str]] = []
    needs_rewrite = False
    with PARSER_UNIT_JSONL.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if "gt_error_position" in payload:
                payload.pop("gt_error_position", None)
                needs_rewrite = True
            rows.append(payload)
    if any("gt_status" not in row for row in rows):
        refreshed_rows = extract_parser_unit_rows()
        write_parser_unit_jsonl(refreshed_rows)
        return refreshed_rows
    if needs_rewrite:
        write_parser_unit_jsonl(rows)
    return rows


def refresh_parser_unit_sources(force_refresh: bool = False) -> Dict[str, object]:
    cached_rows = load_cached_parser_unit_rows()
    if not force_refresh:
        if cached_rows:
            negative_count = sum(1 for row in cached_rows if row["gt_status"] == "fail")
            print_stage("使用缓存的 Apache Hive parser unit 候选池")
            print_kv("parser unit 缓存样本数", len(cached_rows))
            return {
                "parser_unit_case_count": len(cached_rows),
                "parser_unit_negative_count": negative_count,
                "jsonl_path": str(PARSER_UNIT_JSONL),
                "cache_hit": True,
            }

    rows = extract_parser_unit_rows()
    rows = _merge_existing_baselines(rows, cached_rows)
    write_parser_unit_jsonl(rows)
    negative_count = sum(1 for row in rows if row["gt_status"] == "fail")
    print_kv("parser unit 抽取样本数", len(rows))
    print_kv("parser unit 负样本数", negative_count)
    return {
        "parser_unit_case_count": len(rows),
        "parser_unit_negative_count": negative_count,
        "jsonl_path": str(PARSER_UNIT_JSONL),
        "cache_hit": False,
    }
