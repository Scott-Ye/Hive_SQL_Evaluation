"""构建最终黄金集，并冻结 baseline 标签。"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from src.adapters.hive_parser_sdk import parse_sql_rows
from src.core.case_taxonomy import TARGET_BUCKETS, build_distribution_bucket
from src.core.progress import print_kv, print_stage
from src.core.project_config import (
    CASE_FIELDS,
    CURATED_REAL_DATASET,
    REAL_REVIEW_QUEUE_DATASET,
    MAINTENANCE_REPORT,
    REAL_SOURCE_DIR,
    TARGET_CASE_COUNT,
    VERSION_MANIFEST,
    VERSION_DIR,
)
from src.core.source_extractors import load_source_material_rows
from src.pipelines.independence_audit import assert_gt_baseline_independence, build_independence_audit_report
from src.pipelines.open_benchmark_pipeline import (
    load_cached_open_benchmark_rows,
    refresh_open_benchmark_sources,
    write_open_benchmark_jsonl,
)
from src.pipelines.official_doc_pipeline import (
    is_real_example_case,
    load_cached_real_rows,
    refresh_real_official_sources,
    write_real_cases_jsonl,
)
from src.pipelines.parser_unit_pipeline import (
    load_cached_parser_unit_rows,
    refresh_parser_unit_sources,
    write_parser_unit_jsonl,
)


POSITION_PATTERN = re.compile(r"^\d+:\d+$")
WINDOW_PATTERN = re.compile(r"\bOVER\s*\(", re.IGNORECASE)
CTE_PATTERN = re.compile(r"(^|\s)WITH\s+[A-Z_][A-Z0-9_]*\s+AS\s*\(", re.IGNORECASE)
ALLOWED_GT_LABEL_STRENGTHS = {"strong", "medium", "weak"}


def _split_tags(raw_tags: str) -> List[str]:
    return [tag.strip() for tag in raw_tags.split(";") if tag.strip()]


def _legacy_value(row: Dict[str, str], new_key: str, legacy_key: str) -> str:
    # 优先读取新字段名；缺失时回退到旧字段名。
    value = (row.get(new_key, "") or "").strip()
    if value:
        return value
    return (row.get(legacy_key, "") or "").strip()


def normalize_case_row(row: Dict[str, str]) -> Dict[str, str]:
    # 将单条样本规范化到当前 CASE_FIELDS 结构。
    normalized = {field: "" for field in CASE_FIELDS}
    for field in ("case_id", "level1_category", "level2_category", "difficulty", "sql_text", "source_tier", "source", "source_ref", "tags", "notes"):
        normalized[field] = (row.get(field, "") or "").strip()

    normalized["gt_status"] = _legacy_value(row, "gt_status", "expected_status")
    normalized["gt_error_type"] = _legacy_value(row, "gt_error_type", "expected_error_type")
    normalized["gt_error_subtype"] = _legacy_value(row, "gt_error_subtype", "expected_error_subtype")
    normalized["gt_label_source"] = (row.get("gt_label_source", "") or "").strip() or "manual_source_assertion"
    normalized["gt_label_strength"] = (row.get("gt_label_strength", "") or "").strip().lower() or "medium"
    if normalized["gt_label_strength"] not in ALLOWED_GT_LABEL_STRENGTHS:
        normalized["gt_label_strength"] = "medium"

    normalized["baseline_status"] = (row.get("baseline_status", "") or "").strip()
    normalized["baseline_error_type"] = (row.get("baseline_error_type", "") or "").strip()
    normalized["baseline_error_subtype"] = (row.get("baseline_error_subtype", "") or "").strip()
    normalized["baseline_error_type_raw"] = (row.get("baseline_error_type_raw", "") or "").strip()
    normalized["baseline_error_subtype_raw"] = (row.get("baseline_error_subtype_raw", "") or "").strip()
    normalized["baseline_error_position"] = (row.get("baseline_error_position", "") or "").strip()
    normalized["baseline_label_source"] = (row.get("baseline_label_source", "") or "").strip()
    return normalized


def infer_feature_labels(row: Dict[str, str]) -> List[str]:
    # 从标签与 SQL 结构中提取特征标签，用于覆盖度分析。
    sql_text = row.get("sql_text", "")
    upper_sql = f" {sql_text.upper()} "
    features = set()

    level1 = row.get("level1_category", "").strip().lower()
    level2 = row.get("level2_category", "").strip().lower()
    gt_status = _legacy_value(row, "gt_status", "expected_status").lower()
    gt_error_type = _legacy_value(row, "gt_error_type", "expected_error_type").lower()
    gt_error_subtype = _legacy_value(row, "gt_error_subtype", "expected_error_subtype").lower()

    if level1:
        features.add(level1)
    if level2:
        features.add(level2)
    if gt_status:
        features.add(f"status_{gt_status}")
    if gt_error_type:
        features.add(f"error_{gt_error_type}")
    if gt_error_subtype:
        features.add(f"error_subtype_{gt_error_subtype}")

    keyword_features = {
        "join": " JOIN " in upper_sql,
        "window": bool(WINDOW_PATTERN.search(sql_text)),
        "cte": bool(CTE_PATTERN.search(sql_text)),
        "union": " UNION " in upper_sql,
        "subquery": upper_sql.count("SELECT ") > 1,
        "lateral_view": " LATERAL VIEW " in upper_sql,
        "group_by": " GROUP BY " in upper_sql,
        "having": " HAVING " in upper_sql,
        "order_sort": " ORDER BY " in upper_sql or " SORT BY " in upper_sql,
        "limit": " LIMIT " in upper_sql,
        "transform": " TRANSFORM(" in upper_sql or " MAP " in upper_sql or " REDUCE " in upper_sql,
        "partition": " PARTITION " in upper_sql,
        "bucketing": " CLUSTERED BY " in upper_sql or " BUCKETS " in upper_sql,
        "transactional": "TRANSACTIONAL" in upper_sql,
        "serde": " SERDE " in upper_sql or " ROW FORMAT " in upper_sql,
        "explain": upper_sql.lstrip().startswith("EXPLAIN "),
        "describe": upper_sql.lstrip().startswith("DESCRIBE "),
        "insert_overwrite": " INSERT OVERWRITE " in upper_sql,
        "insert_into": " INSERT INTO " in upper_sql,
        "insert_from": upper_sql.lstrip().startswith("FROM ") and " INSERT " in upper_sql,
        "update": upper_sql.lstrip().startswith("UPDATE "),
        "delete": upper_sql.lstrip().startswith("DELETE "),
        "create_table": upper_sql.lstrip().startswith("CREATE TABLE ") or upper_sql.lstrip().startswith("CREATE EXTERNAL TABLE "),
        "alter_table": upper_sql.lstrip().startswith("ALTER TABLE "),
        "drop_table": upper_sql.lstrip().startswith("DROP TABLE "),
        "within_group": " WITHIN GROUP " in upper_sql,
        "merge": upper_sql.lstrip().startswith("MERGE "),
        "optimizer_hint": "/*+" in sql_text,
        "regex_identifier": "`(" in sql_text,
    }
    for feature, enabled in keyword_features.items():
        if enabled:
            features.add(feature)

    return sorted(features)


def read_csv_rows(file_path: Path, fieldnames: List[str] | None = None) -> List[Dict[str, str]]:
    if not file_path.exists():
        return []
    with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if fieldnames is None:
        return rows
    return [{field: (normalize_case_row(row).get(field, "") or "").strip() for field in fieldnames} for row in rows]


def write_csv_rows(file_path: Path, rows: List[Dict[str, str]], fieldnames: List[str]) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def normalize_sql(sql_text: str) -> str:
    return " ".join(sql_text.lower().split())


def enrich_case(row: Dict[str, str], case_id: str) -> Dict[str, str]:
    enriched = normalize_case_row(row)
    enriched["case_id"] = case_id
    tags = set(tag for tag in _split_tags(enriched["tags"]) if ":" in tag)
    tags.add(f"tier:{enriched['source_tier'].lower() or 'unknown'}")
    tags.add(f"source:{enriched['source'] or 'unknown'}")
    tags.add(f"level1:{enriched['level1_category'].lower() or 'unknown'}")
    tags.add(f"level2:{enriched['level2_category'].lower() or 'unknown'}")
    tags.add(f"gt_status:{enriched['gt_status'].lower() or 'unknown'}")
    tags.add(f"gt_strength:{enriched['gt_label_strength'] or 'unknown'}")
    if enriched["gt_error_type"]:
        tags.add(f"gt_error:{enriched['gt_error_type'].lower()}")
    if enriched["gt_error_subtype"]:
        tags.add(f"gt_error_subtype:{enriched['gt_error_subtype'].lower()}")
    if enriched["baseline_status"]:
        tags.add(f"baseline_status:{enriched['baseline_status'].lower()}")
    if enriched["baseline_error_type"]:
        tags.add(f"baseline_error:{enriched['baseline_error_type'].lower()}")
    for feature in infer_feature_labels(enriched):
        tags.add(f"feature:{feature}")
    enriched["tags"] = ";".join(sorted(tags))
    return enriched


def load_real_source_rows() -> List[Dict[str, str]]:
    rows = load_source_material_rows(REAL_SOURCE_DIR)
    return [normalize_case_row(row) for row in rows]


def clean_real_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    cleaned_rows: List[Dict[str, str]] = []
    for row in rows:
        copied = deepcopy(row)
        if copied["source"] == "hive_official_docs" and not is_real_example_case(copied["sql_text"]):
            continue
        cleaned_rows.append(copied)
    return cleaned_rows


def _has_frozen_baseline(row: Dict[str, str]) -> bool:
    return bool(
        row.get("baseline_status")
        or row.get("baseline_error_type")
        or row.get("baseline_error_subtype")
        or row.get("baseline_error_type_raw")
        or row.get("baseline_error_subtype_raw")
        or row.get("baseline_error_position")
        or row.get("baseline_label_source")
    )


def annotate_baseline_labels(
    # 冻结缺失的 baseline，并按需刷新已缓存的失败样本。
    rows: List[Dict[str, str]],
    *,
    only_missing: bool = False,
    refresh_existing_failures: bool = False,
) -> List[Dict[str, str]]:
    pending_indices = []
    payload = []
    for index, row in enumerate(rows):
        has_frozen_baseline = _has_frozen_baseline(row)
        should_refresh_failure = refresh_existing_failures and row.get("baseline_status") == "fail"
        if only_missing and has_frozen_baseline and not should_refresh_failure:
            continue
        # 这里用列表索引做临时 case_id，便于把批量解析结果再映射回原行。
        pending_indices.append(index)
        payload.append({"case_id": str(index), "sql_text": row["sql_text"]})

    if not payload:
        return [deepcopy(row) for row in rows]

    parsed_rows = parse_sql_rows(payload)
    parsed_by_case_id = {row["case_id"]: row for row in parsed_rows}

    annotated_rows: List[Dict[str, str]] = []
    for index, row in enumerate(rows):
        copied = deepcopy(row)
        parsed = parsed_by_case_id.get(str(index))
        if parsed is None:
            annotated_rows.append(copied)
            continue
        copied["baseline_status"] = parsed.get("actual_status", "")
        copied["baseline_error_type"] = parsed.get("actual_error_type", "")
        copied["baseline_error_subtype"] = parsed.get("actual_error_subtype", "")
        copied["baseline_error_type_raw"] = parsed.get("raw_error_type", "")
        copied["baseline_error_subtype_raw"] = parsed.get("raw_error_subtype", "")
        copied["baseline_error_position"] = parsed.get("actual_error_position", "")
        copied["baseline_label_source"] = "local_hive_parse_sdk"
        if "baseline=local_hive_parse_sdk" not in copied["notes"]:
            copied["notes"] = f"{copied['notes']} | baseline=local_hive_parse_sdk".strip(" |")
        annotated_rows.append(copied)
    return annotated_rows


def freeze_real_source_baselines() -> Dict[str, int]:
    # 刷新已缓存的 fail baseline，让 taxonomy 修正能同步落到来源缓存。
    source_specs = [
        ("official_docs", load_cached_real_rows, write_real_cases_jsonl),
        ("open_benchmark", load_cached_open_benchmark_rows, write_open_benchmark_jsonl),
        ("parser_unit", load_cached_parser_unit_rows, write_parser_unit_jsonl),
    ]
    summary: Dict[str, int] = {}
    for name, loader, writer in source_specs:
        rows = [normalize_case_row(row) for row in loader()]
        missing_count = sum(
            1
            for row in rows
            if (not _has_frozen_baseline(row)) or row.get("baseline_status") == "fail"
        )
        if missing_count:
            rows = annotate_baseline_labels(rows, only_missing=True, refresh_existing_failures=True)
            writer(rows)
        summary[name] = missing_count
    return summary


def filter_strict_real_candidates(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    filtered: List[Dict[str, str]] = []
    for row in rows:
        gt_status = row.get("gt_status", "")
        gt_strength = row.get("gt_label_strength", "")
        if gt_status not in {"pass", "fail"}:
            continue
        if gt_strength != "strong":
            continue
        filtered.append(deepcopy(row))
    return filtered


def build_real_review_queue(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    review_rows: List[Dict[str, str]] = []
    for row in rows:
        gt_strength = row.get("gt_label_strength", "")
        if gt_strength == "strong":
            continue
        copied = normalize_case_row(row)
        if gt_strength == "medium":
            copied["review_reason"] = "medium_gt_requires_manual_review"
            copied["review_priority"] = "high"
        else:
            copied["review_reason"] = "weak_gt_excluded_from_strict_gold"
            copied["review_priority"] = "highest"
        review_rows.append(copied)
    review_rows.sort(
        key=lambda row: (
            0 if row["review_priority"] == "highest" else 1,
            row["level1_category"],
            row["level2_category"],
            row["source"],
            -len(row["sql_text"]),
        )
    )
    return review_rows


def write_review_queue(rows: List[Dict[str, str]]) -> None:
    REAL_REVIEW_QUEUE_DATASET.parent.mkdir(parents=True, exist_ok=True)
    with REAL_REVIEW_QUEUE_DATASET.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_QUEUE_FIELDS)
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in REVIEW_QUEUE_FIELDS} for row in rows])


def _read_version_case_rows(file_path: Path) -> List[Dict[str, str]]:
    if not file_path.exists():
        return []
    with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [normalize_case_row(row) for row in reader]


def build_iteration_preference_sets(snapshot_limit: int = 3) -> Tuple[set[str], set[str]]:
    # 优先保留最近几个快照里出现过的样本，提升版本迭代稳定性。
    snapshots = sorted(VERSION_DIR.glob("hive_cases_real_multisource_gold_*.csv"))
    if not snapshots:
        return set(), set()

    recent_snapshot_paths = snapshots[-snapshot_limit:]
    recent_snapshots = [_read_version_case_rows(path) for path in recent_snapshot_paths]
    previous_snapshot_rows = recent_snapshots[-1] if recent_snapshots else []
    previous_snapshot_sql = {normalize_sql(row["sql_text"]) for row in previous_snapshot_rows}

    occurrence_counter: Counter = Counter()
    gt_signature_counter: Dict[str, set[Tuple[str, str, str, str]]] = {}
    for snapshot_rows in recent_snapshots:
        seen_in_snapshot = set()
        for row in snapshot_rows:
            sql_key = normalize_sql(row["sql_text"])
            if sql_key in seen_in_snapshot:
                continue
            seen_in_snapshot.add(sql_key)
            occurrence_counter[sql_key] += 1
            gt_signature_counter.setdefault(sql_key, set()).add(
                (
                    row["gt_status"],
                    row["gt_error_type"],
                    row["gt_error_subtype"],
                    row["gt_label_strength"],
                )
            )

    # stable_core_sql 表示：最近几个版本里持续存在，且 GT 口径没有漂移的稳定样本。
    stable_core_sql = {
        sql_key
        for sql_key, count in occurrence_counter.items()
        if count == len(recent_snapshots) and len(gt_signature_counter.get(sql_key, set())) == 1
    }
    return stable_core_sql, previous_snapshot_sql


def _diversity_key(
    row: Dict[str, str],
    stable_core_sql: set[str] | None = None,
    previous_snapshot_sql: set[str] | None = None,
) -> tuple:
    feature_count = len(infer_feature_labels(row))
    sql_key = normalize_sql(row.get("sql_text", ""))
    stable_priority = 1 if stable_core_sql and sql_key in stable_core_sql else 0
    history_priority = 1 if previous_snapshot_sql and sql_key in previous_snapshot_sql else 0
    source = row.get("source", "")
    level2 = row.get("level2_category", "")
    sql_length = len(row.get("sql_text", ""))
    source_ref = row.get("source_ref", "")
    return (-stable_priority, -history_priority, -feature_count, source, level2, -sql_length, source_ref)


def _history_priority_key(
    row: Dict[str, str],
    *,
    stable_core_sql: set[str] | None = None,
    previous_snapshot_sql: set[str] | None = None,
) -> tuple[int, int]:
    sql_key = normalize_sql(row.get("sql_text", ""))
    stable_priority = 1 if stable_core_sql and sql_key in stable_core_sql else 0
    history_priority = 1 if previous_snapshot_sql and sql_key in previous_snapshot_sql else 0
    return stable_priority, history_priority


def _pick_diverse_rows(
    # 按 level2 轮转取样，尽量提升样本多样性。
    rows: List[Dict[str, str]],
    target_count: int,
    *,
    stable_core_sql: set[str] | None = None,
    previous_snapshot_sql: set[str] | None = None,
) -> List[Dict[str, str]]:
    by_level2: Dict[str, List[Dict[str, str]]] = {}
    for row in sorted(
        rows,
        key=lambda item: _diversity_key(
            item,
            stable_core_sql=stable_core_sql,
            previous_snapshot_sql=previous_snapshot_sql,
        ),
    ):
        by_level2.setdefault(row["level2_category"], []).append(row)

    picked: List[Dict[str, str]] = []
    ordered_level2 = sorted(by_level2, key=lambda key: (-len(by_level2[key]), key))

    while len(picked) < target_count:
        progressed = False
        # 每轮从不同 level2 各拿一条，避免大量样本被同一种二级类型挤占。
        for level2 in ordered_level2:
            candidates = by_level2[level2]
            if not candidates:
                continue
            picked.append(candidates.pop(0))
            progressed = True
            if len(picked) >= target_count:
                break
        if not progressed:
            break
    return picked


def _balanced_bucket_pick(
    # 在分桶内先交替混排 pass/fail 候选，再做后续比例再平衡。
    rows: List[Dict[str, str]],
    target_count: int,
    *,
    stable_core_sql: set[str] | None = None,
    previous_snapshot_sql: set[str] | None = None,
) -> List[Dict[str, str]]:
    fail_rows = _pick_diverse_rows(
        [row for row in rows if row["gt_status"] == "fail"],
        target_count,
        stable_core_sql=stable_core_sql,
        previous_snapshot_sql=previous_snapshot_sql,
    )
    pass_rows = _pick_diverse_rows(
        [row for row in rows if row["gt_status"] == "pass"],
        target_count,
        stable_core_sql=stable_core_sql,
        previous_snapshot_sql=previous_snapshot_sql,
    )
    picked: List[Dict[str, str]] = []
    fail_index = 0
    pass_index = 0

    while len(picked) < target_count and (fail_index < len(fail_rows) or pass_index < len(pass_rows)):
        if fail_index < len(fail_rows):
            picked.append(fail_rows[fail_index])
            fail_index += 1
            if len(picked) >= target_count:
                break
        if pass_index < len(pass_rows):
            picked.append(pass_rows[pass_index])
            pass_index += 1
    return picked[:target_count]


FEATURE_COVERAGE_PRIORITIES = [
    "describe",
    "lateral_view",
    "update",
    "delete",
    "window",
    "cte",
    "within_group",
    "merge",
]
ERROR_TYPE_COVERAGE_PRIORITIES = [
    "mismatched_input",
    "parse_error",
    "cannot_recognize_input",
]
REVIEW_QUEUE_FIELDS = CASE_FIELDS + ["review_reason", "review_priority"]


def _replace_row_for_feature_coverage(
    selected_rows: List[Dict[str, str]],
    candidate_rows: List[Dict[str, str]],
    feature: str,
    protected_features: set[str],
    *,
    stable_core_sql: set[str] | None = None,
    previous_snapshot_sql: set[str] | None = None,
) -> List[Dict[str, str]]:
    selected_features = [set(infer_feature_labels(row)) for row in selected_rows]
    if any(feature in features for features in selected_features):
        return selected_rows

    replacement = None
    replacement_bucket = ""
    for row in sorted(
        candidate_rows,
        key=lambda item: _diversity_key(
            item,
            stable_core_sql=stable_core_sql,
            previous_snapshot_sql=previous_snapshot_sql,
        ),
    ):
        features = set(infer_feature_labels(row))
        if feature not in features:
            continue
        if row in selected_rows:
            continue
        replacement = row
        replacement_bucket = build_distribution_bucket(row)
        break
    if replacement is None:
        return selected_rows

    removable_indices: List[int] = []
    for index, row in enumerate(selected_rows):
        if build_distribution_bucket(row) != replacement_bucket:
            continue
        row_features = selected_features[index]
        if feature in row_features:
            continue
        if any(protected_feature in row_features for protected_feature in protected_features):
            continue
        removable_indices.append(index)
    if not removable_indices:
        return selected_rows

    level2_counter = Counter(row["level2_category"] for row in selected_rows)
    removable_indices.sort(
        key=lambda index: (
            _history_priority_key(
                selected_rows[index],
                stable_core_sql=stable_core_sql,
                previous_snapshot_sql=previous_snapshot_sql,
            ),
            -level2_counter[selected_rows[index]["level2_category"]],
            len(selected_features[index]),
            selected_rows[index]["level2_category"],
        )
    )
    selected_rows[removable_indices[0]] = replacement
    return selected_rows


def ensure_feature_coverage(
    # 确保最终入选结果仍覆盖稀缺语法特征。
    selected_rows: List[Dict[str, str]],
    candidate_rows: List[Dict[str, str]],
    *,
    stable_core_sql: set[str] | None = None,
    previous_snapshot_sql: set[str] | None = None,
) -> List[Dict[str, str]]:
    covered_rows = [deepcopy(row) for row in selected_rows]
    protected_features: set[str] = set()
    for feature in FEATURE_COVERAGE_PRIORITIES:
        covered_rows = _replace_row_for_feature_coverage(
            covered_rows,
            candidate_rows,
            feature,
            protected_features,
            stable_core_sql=stable_core_sql,
            previous_snapshot_sql=previous_snapshot_sql,
        )
        if any(feature in set(infer_feature_labels(row)) for row in covered_rows):
            protected_features.add(feature)
    return covered_rows


def ensure_negative_error_coverage(
    # 在可行范围内保证负样本覆盖重点错误类型。
    selected_rows: List[Dict[str, str]],
    candidate_rows: List[Dict[str, str]],
    *,
    stable_core_sql: set[str] | None = None,
    previous_snapshot_sql: set[str] | None = None,
) -> List[Dict[str, str]]:
    covered_rows = [deepcopy(row) for row in selected_rows]
    for error_type in ERROR_TYPE_COVERAGE_PRIORITIES:
        if any(
            row["gt_status"] == "fail" and row["gt_error_type"] == error_type
            for row in covered_rows
        ):
            continue
        replacement_candidates = [
            row
            for row in candidate_rows
            if row["gt_status"] == "fail"
            and row["gt_error_type"] == error_type
            and row not in covered_rows
        ]
        replacement = (
            sorted(
                replacement_candidates,
                key=lambda item: _diversity_key(
                    item,
                    stable_core_sql=stable_core_sql,
                    previous_snapshot_sql=previous_snapshot_sql,
                ),
            )[0]
            if replacement_candidates
            else None
        )
        if replacement is None:
            continue
        replacement_bucket = build_distribution_bucket(replacement)
        removable_indices = [
            index
            for index, row in enumerate(covered_rows)
            if build_distribution_bucket(row) == replacement_bucket
            and row["gt_status"] == "pass"
        ]
        removable_indices.sort(
            key=lambda index: (
                _history_priority_key(
                    covered_rows[index],
                    stable_core_sql=stable_core_sql,
                    previous_snapshot_sql=previous_snapshot_sql,
                ),
                len(infer_feature_labels(covered_rows[index])),
                covered_rows[index]["level2_category"],
            )
        )
        removable_index = removable_indices[0] if removable_indices else None
        if removable_index is not None:
            covered_rows[removable_index] = replacement
    return covered_rows


def rebalance_status_ratio(
    # 将最终 100 条样本重新平衡到目标 pass/fail 比例附近。
    selected_rows: List[Dict[str, str]],
    candidate_rows: List[Dict[str, str]],
    *,
    stable_core_sql: set[str] | None = None,
    previous_snapshot_sql: set[str] | None = None,
) -> List[Dict[str, str]]:
    balanced_rows = [deepcopy(row) for row in selected_rows]
    target_fail_count = len(balanced_rows) // 2
    current_fail_count = sum(1 for row in balanced_rows if row["gt_status"] == "fail")
    if current_fail_count >= target_fail_count:
        return balanced_rows

    selected_sql = {normalize_sql(row["sql_text"]) for row in balanced_rows}
    bucket_fail_pool: Dict[str, List[Dict[str, str]]] = {bucket: [] for bucket in TARGET_BUCKETS}
    for row in candidate_rows:
        if row["gt_status"] != "fail":
            continue
        sql_key = normalize_sql(row["sql_text"])
        if sql_key in selected_sql:
            continue
        bucket_fail_pool.setdefault(build_distribution_bucket(row), []).append(row)

    for bucket in bucket_fail_pool:
        bucket_fail_pool[bucket] = _pick_diverse_rows(
            bucket_fail_pool[bucket],
            len(bucket_fail_pool[bucket]),
            stable_core_sql=stable_core_sql,
            previous_snapshot_sql=previous_snapshot_sql,
        )

    while current_fail_count < target_fail_count:
        replaced = False
        for bucket in TARGET_BUCKETS:
            replacement_pool = bucket_fail_pool.get(bucket, [])
            if not replacement_pool:
                continue
            removable_indices = [
                index
                for index, row in enumerate(balanced_rows)
                if build_distribution_bucket(row) == bucket and row["gt_status"] == "pass"
            ]
            if not removable_indices:
                continue
            removable_indices.sort(
                key=lambda index: (
                    _history_priority_key(
                        balanced_rows[index],
                        stable_core_sql=stable_core_sql,
                        previous_snapshot_sql=previous_snapshot_sql,
                    ),
                    len(infer_feature_labels(balanced_rows[index])),
                    balanced_rows[index]["level2_category"],
                )
            )
            balanced_rows[removable_indices[0]] = replacement_pool.pop(0)
            current_fail_count += 1
            replaced = True
            if current_fail_count >= target_fail_count:
                break
        if not replaced:
            break
    return balanced_rows


def deduplicate_rows(rows: Iterable[Dict[str, str]]) -> Tuple[List[Dict[str, str]], int]:
    deduped: List[Dict[str, str]] = []
    seen_sql = set()
    duplicate_count = 0
    for row in rows:
        sql_key = normalize_sql(row["sql_text"])
        if sql_key in seen_sql:
            duplicate_count += 1
            continue
        seen_sql.add(sql_key)
        deduped.append(deepcopy(row))
    return deduped, duplicate_count


def quality_check_rows(rows: List[Dict[str, str]]) -> List[str]:
    issues: List[str] = []
    for index, row in enumerate(rows, start=1):
        case_label = row.get("case_id", f"ROW_{index}")
        if row["gt_status"] not in {"pass", "fail"}:
            issues.append(f"{case_label}: gt_status 必须是 pass 或 fail")
        if not row["sql_text"]:
            issues.append(f"{case_label}: sql_text 不能为空")
        if row["source_tier"] != "real":
            issues.append(f"{case_label}: source_tier 必须是 real")
        if not row["source_ref"]:
            issues.append(f"{case_label}: source_ref 不能为空")
        if row["gt_label_strength"] not in ALLOWED_GT_LABEL_STRENGTHS:
            issues.append(f"{case_label}: gt_label_strength 必须是 strong/medium/weak")
        if row["baseline_status"] == "fail" and row["baseline_error_position"] and not POSITION_PATTERN.match(
            row["baseline_error_position"]
        ):
            issues.append(f"{case_label}: baseline_error_position 必须是合法的行列格式")
    return issues


def select_target_rows(
    # 先按目标分桶选样，再统一调整状态比例、错误覆盖和特征覆盖。
    rows: List[Dict[str, str]],
    target_total: int = TARGET_CASE_COUNT,
    *,
    stable_core_sql: set[str] | None = None,
    previous_snapshot_sql: set[str] | None = None,
) -> List[Dict[str, str]]:
    bucketed_rows: Dict[str, List[Dict[str, str]]] = {bucket: [] for bucket in TARGET_BUCKETS}
    for row in rows:
        bucketed_rows.setdefault(build_distribution_bucket(row), []).append(row)

    selected_rows: List[Dict[str, str]] = []
    selected_ids = set()
    # 先保证每个目标桶都有基础配额，再在后面补足总量与覆盖度。
    for bucket, target_count in TARGET_BUCKETS.items():
        bucket_rows = _balanced_bucket_pick(
            bucketed_rows.get(bucket, []),
            target_count,
            stable_core_sql=stable_core_sql,
            previous_snapshot_sql=previous_snapshot_sql,
        )
        for row in bucket_rows:
            row_id = id(row)
            if row_id in selected_ids:
                continue
            selected_ids.add(row_id)
            selected_rows.append(row)

    if len(selected_rows) < target_total:
        for row in sorted(
            rows,
            key=lambda item: _diversity_key(
                item,
                stable_core_sql=stable_core_sql,
                previous_snapshot_sql=previous_snapshot_sql,
            ),
        ):
            row_id = id(row)
            if row_id in selected_ids:
                continue
            selected_ids.add(row_id)
            selected_rows.append(row)
            if len(selected_rows) >= target_total:
                break
    balanced_rows = rebalance_status_ratio(
        selected_rows[:target_total],
        rows,
        stable_core_sql=stable_core_sql,
        previous_snapshot_sql=previous_snapshot_sql,
    )
    balanced_rows = ensure_negative_error_coverage(
        balanced_rows,
        rows,
        stable_core_sql=stable_core_sql,
        previous_snapshot_sql=previous_snapshot_sql,
    )
    return ensure_feature_coverage(
        balanced_rows,
        rows,
        stable_core_sql=stable_core_sql,
        previous_snapshot_sql=previous_snapshot_sql,
    )


def build_dataset(rows: List[Dict[str, str]], output_path: Path, case_prefix: str) -> Tuple[List[Dict[str, str]], int]:
    deduped_rows, duplicate_count = deduplicate_rows(rows)
    curated_rows = [enrich_case(row, f"{case_prefix}_{index:03d}") for index, row in enumerate(deduped_rows, start=1)]
    issues = quality_check_rows(curated_rows)
    if issues:
        raise ValueError("\n".join(issues))
    write_csv_rows(output_path, curated_rows, CASE_FIELDS)
    return curated_rows, duplicate_count


def build_curated_datasets() -> Dict[str, object]:
    # 刷新各来源、冻结 baseline，并重新生成评测集。
    print_stage("刷新真实来源候选池")
    real_refresh_summary = refresh_real_official_sources()
    benchmark_refresh_summary = refresh_open_benchmark_sources()
    parser_unit_refresh_summary = refresh_parser_unit_sources()
    print_stage("冻结 raw-source baseline 对照")
    baseline_freeze_summary = freeze_real_source_baselines()
    print_kv("官方 baseline 写入/刷新数", baseline_freeze_summary["official_docs"])
    print_kv("benchmark baseline 写入/刷新数", baseline_freeze_summary["open_benchmark"])
    print_kv("parser unit baseline 写入/刷新数", baseline_freeze_summary["parser_unit"])
    print_stage("加载并清洗真实候选池")
    real_rows = load_real_source_rows()
    cleaned_real_rows = clean_real_rows(real_rows)
    review_queue_rows = build_real_review_queue(cleaned_real_rows)
    write_review_queue(review_queue_rows)
    strict_real_candidates = filter_strict_real_candidates(cleaned_real_rows)
    stable_core_sql, previous_snapshot_sql = build_iteration_preference_sets()
    deduped_real_candidates, real_duplicate_count = deduplicate_rows(strict_real_candidates)
    print_kv("清洗后真实候选数", len(cleaned_real_rows))
    print_kv("高可信候选池样本数", len(strict_real_candidates))
    print_kv("去重后高可信候选池样本数", len(deduped_real_candidates))
    print_kv("待审池样本数", len(review_queue_rows))
    print_stage("按目标分布沉淀最终黄金集")
    selected_real_rows = select_target_rows(
        deduped_real_candidates,
        target_total=TARGET_CASE_COUNT,
        stable_core_sql=stable_core_sql,
        previous_snapshot_sql=previous_snapshot_sql,
    )
    print_kv("最终入选样本数", len(selected_real_rows))
    print_stage("检查最终黄金集样本约束")
    assert_gt_baseline_independence(
        selected_real_rows,
        stage="strict_real_gold_pre_eval",
        require_strong_only=True,
        require_empty_baseline=False,
    )
    print_stage("写出数据集、版本快照与维护文档")
    real_curated, real_duplicate_count = build_dataset(selected_real_rows, CURATED_REAL_DATASET, "HIVE_REAL")
    build_independence_audit_report(
        real_curated,
        strict_gold_candidate_rows=strict_real_candidates,
        strict_gold_deduped_candidate_rows=deduped_real_candidates,
    )

    write_version_manifest(
        real_curated=real_curated,
        real_duplicate_count=real_duplicate_count,
    )
    write_maintenance_report(
        real_curated=real_curated,
        real_duplicate_count=real_duplicate_count,
        official_raw_count=int(real_refresh_summary["extracted_case_count"]),
        benchmark_raw_count=int(benchmark_refresh_summary["open_benchmark_case_count"]),
        parser_unit_raw_count=int(parser_unit_refresh_summary["parser_unit_case_count"]),
        cleaned_real_count=len(cleaned_real_rows),
        strict_candidate_count=len(strict_real_candidates),
        strict_candidate_deduped_count=len(deduped_real_candidates),
        review_queue_count=len(review_queue_rows),
    )

    return {
        "real_count": len(real_curated),
        "real_dataset_path": str(CURATED_REAL_DATASET),
        "real_raw_count": int(real_refresh_summary["extracted_case_count"]),
        "real_cleaned_count": len(cleaned_real_rows),
        "real_review_queue_count": len(review_queue_rows),
        "real_strict_candidate_count": len(strict_real_candidates),
        "real_stable_core_preference_count": len(stable_core_sql),
        "real_previous_snapshot_preference_count": len(previous_snapshot_sql),
        "real_deduped_count": len(deduped_real_candidates),
        "real_baseline_frozen_count": len(real_rows),
        "real_baseline_newly_frozen_count": sum(baseline_freeze_summary.values()),
        "open_benchmark_raw_count": int(benchmark_refresh_summary["open_benchmark_case_count"]),
        "open_benchmark_negative_count": int(benchmark_refresh_summary["open_benchmark_negative_count"]),
        "parser_unit_raw_count": int(parser_unit_refresh_summary["parser_unit_case_count"]),
        "parser_unit_negative_count": int(parser_unit_refresh_summary["parser_unit_negative_count"]),
    }


def build_curated_dataset() -> Dict[str, object]:
    return build_curated_datasets()


def write_version_manifest(
    # 写出带时间戳的版本快照，用于历史对比与 stable core 分析。
    *,
    real_curated: List[Dict[str, str]],
    real_duplicate_count: int,
) -> None:
    VERSION_DIR.mkdir(parents=True, exist_ok=True)
    version = datetime.now().strftime("%Y%m%d_%H%M%S")
    real_snapshot = VERSION_DIR / f"hive_cases_real_multisource_gold_{version}.csv"
    write_csv_rows(real_snapshot, real_curated, CASE_FIELDS)

    manifest = {
        "latest_version": version,
        "latest_real_snapshot": str(real_snapshot),
        "stats": {
            "real_source_count": len(real_curated),
            "real_duplicate_removed_count": real_duplicate_count,
        },
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    VERSION_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def write_maintenance_report(
    # 生成维护报告，汇总来源情况、过滤结果与 baseline 状态。
    *,
    real_curated: List[Dict[str, str]],
    real_duplicate_count: int,
    official_raw_count: int,
    benchmark_raw_count: int,
    parser_unit_raw_count: int,
    cleaned_real_count: int,
    strict_candidate_count: int,
    strict_candidate_deduped_count: int,
    review_queue_count: int,
) -> None:
    real_source_counter = Counter(row["source"] for row in real_curated)
    real_bucket_counter = Counter(build_distribution_bucket(row) for row in real_curated)
    real_status_counter = Counter(row["gt_status"] for row in real_curated)
    real_gt_strength_counter = Counter(row["gt_label_strength"] for row in real_curated)
    real_level2_counter = Counter(row["level2_category"] for row in real_curated)
    real_error_counter = Counter(row["gt_error_type"] for row in real_curated if row["gt_error_type"])
    real_error_subtype_counter = Counter(
        row["gt_error_subtype"] for row in real_curated if row.get("gt_error_subtype")
    )
    real_baseline_status_counter = Counter(row["baseline_status"] for row in real_curated if row.get("baseline_status"))
    real_feature_counter = Counter()
    for row in real_curated:
        for feature in infer_feature_labels(row):
            if feature.startswith("status_") or feature.startswith("error_"):
                continue
            real_feature_counter[feature] += 1
    review_queue_rows = build_real_review_queue(clean_real_rows(load_real_source_rows()))
    review_reason_counter = Counter(row["review_reason"] for row in review_queue_rows)

    lines = [
        "# 评测集自动维护报告",
        "",
        "## Real Source 数据集",
        "",
        f"- 当前有效样本: {len(real_curated)}",
        f"- 去重移除样本: {real_duplicate_count}",
        f"- GT pass 样本: {real_status_counter['pass']}",
        f"- GT fail 样本: {real_status_counter['fail']}",
        f"- 当前最终黄金集口径: 只保留高可信真值样本",
        f"- 已隔离待审样本数: {review_queue_count}",
        "",
        "### 原始抓取与过滤规模",
        "",
        f"- Hive 官方文档原始抽取: {official_raw_count}",
        f"- Apache Hive benchmark 原始抽取: {benchmark_raw_count}",
        f"- Apache Hive parser unit 原始抽取: {parser_unit_raw_count}",
        f"- 清洗后真实候选总数: {cleaned_real_count}",
        f"- 选样前高可信候选池样本数: {strict_candidate_count}",
        f"- 去重后高可信候选池样本数: {strict_candidate_deduped_count}",
        f"- 待审池数量(不是原始抓取总量): {review_queue_count}",
        "",
        "### 来源分布",
        "",
    ]
    for key, count in sorted(real_source_counter.items()):
        lines.append(f"- {key}: {count}")

    lines.extend(["", "### 目标分布校准", ""])
    for bucket, target_count in TARGET_BUCKETS.items():
        lines.append(f"- {bucket}: {real_bucket_counter[bucket]}/{target_count}")

    lines.extend(["", "### 二级类型分布", ""])
    for key, count in sorted(real_level2_counter.items()):
        lines.append(f"- {key}: {count}")

    lines.extend(["", "### GT 强度分布", ""])
    for key, count in sorted(real_gt_strength_counter.items()):
        lines.append(f"- {key}: {count}")

    lines.extend(["", "### 待审池原因分布", ""])
    for key, count in sorted(review_reason_counter.items()):
        lines.append(f"- {key}: {count}")

    lines.extend(["", "### 典型语法特性覆盖", ""])
    for key, count in sorted(real_feature_counter.items()):
        lines.append(f"- {key}: {count}")

    lines.extend(["", "### 负样本错误类型", ""])
    if real_error_counter:
        for key, count in sorted(real_error_counter.items()):
            lines.append(f"- {key}: {count}")
    else:
        lines.append("- 当前没有负样本错误类型记录")

    lines.extend(["", "### 负样本错误子类型", ""])
    if real_error_subtype_counter:
        for key, count in sorted(real_error_subtype_counter.items()):
            lines.append(f"- {key}: {count}")
    else:
        lines.append("- 当前没有负样本错误子类型记录")

    lines.extend(["", "### Baseline 标签分布", ""])
    if real_baseline_status_counter:
        for key, count in sorted(real_baseline_status_counter.items()):
            lines.append(f"- {key}: {count}")
    else:
        lines.append("- 当前没有 baseline 标签记录")

    lines.extend(
        [
            "",
            "## 分层说明",
            "",
            "- real-source 黄金集来自可追溯的多源候选池，当前包括 Hive 官方文档、Apache Hive 开源 benchmark、Apache Hive parser unit tests。",
            "- GT 标签来自原始来源断言、目录语义和保守规则；baseline 只单独记录历史对照结果。",
            "- baseline 标签记录当前本地 Hive Parse SDK 的冻结结果，不参与真实黄金集选样。",
            "- 当前 real-source 黄金集只保留高可信真值样本，中低可信样本会进入待审池，不参与最终评分。",
            "- 所有样本均要求 source_tier 和 source_ref 明确可追踪。",
        ]
    )
    MAINTENANCE_REPORT.parent.mkdir(parents=True, exist_ok=True)
    MAINTENANCE_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
