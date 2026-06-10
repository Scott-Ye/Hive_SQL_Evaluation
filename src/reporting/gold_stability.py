"""黄金集稳定性分析报告生成逻辑。"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Dict, List

from src.core.case_taxonomy import TARGET_BUCKETS, build_distribution_bucket
from src.core.project_config import CASE_FIELDS, GOLD_STABILITY_REPORT_MD, VERSION_DIR
from src.pipelines.dataset_pipeline import infer_feature_labels, normalize_case_row, normalize_sql
from src.reporting.evaluator import score_case


def _read_case_rows(csv_path: Path) -> List[Dict[str, str]]:
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{field: (normalize_case_row(row).get(field, "") or "").strip() for field in CASE_FIELDS} for row in reader]


def _snapshot_versions() -> List[Path]:
    return sorted(VERSION_DIR.glob("hive_cases_real_multisource_gold_*.csv"))


def _counter_diff(current: Counter, previous: Counter) -> Dict[str, int]:
    keys = set(current) | set(previous)
    return {key: current[key] - previous[key] for key in sorted(keys)}


def _feature_counter(rows: List[Dict[str, str]]) -> Counter:
    counter: Counter = Counter()
    for row in rows:
        for feature in infer_feature_labels(row):
            if feature.startswith("status_") or feature.startswith("error_"):
                continue
            counter[feature] += 1
    return counter


def build_gold_stability_report(
    current_rows: List[Dict[str, str]],
    current_results: List[Dict[str, str]],
    *,
    output_path: Path = GOLD_STABILITY_REPORT_MD,
) -> str:
    current_sql_map = {normalize_sql(row["sql_text"]): row for row in current_rows}
    current_bucket_counter = Counter(build_distribution_bucket(row) for row in current_rows)
    current_status_counter = Counter(row["gt_status"] for row in current_rows)
    current_source_counter = Counter(row["source"] for row in current_rows)
    current_error_counter = Counter(row["gt_error_type"] for row in current_rows if row["gt_error_type"])
    current_gt_strength_counter = Counter(row["gt_label_strength"] for row in current_rows if row["gt_label_strength"])
    current_error_subtype_counter = Counter(
        row["gt_error_subtype"] for row in current_rows if row.get("gt_error_subtype")
    )
    current_feature_counter = _feature_counter(current_rows)
    current_level2_counter = Counter(row["level2_category"] for row in current_rows)
    current_score_counter = Counter(score_case(row) for row in current_results)

    versions = _snapshot_versions()
    latest_snapshot = versions[-1] if versions else None
    previous_snapshot = versions[-2] if len(versions) >= 2 else None
    previous_rows = _read_case_rows(previous_snapshot) if previous_snapshot else []
    previous_sql_map = {normalize_sql(row["sql_text"]): row for row in previous_rows}
    previous_bucket_counter = Counter(build_distribution_bucket(row) for row in previous_rows)
    previous_status_counter = Counter(row["gt_status"] for row in previous_rows)
    previous_feature_counter = _feature_counter(previous_rows)

    overlap_sql = set(current_sql_map) & set(previous_sql_map)
    added_sql = set(current_sql_map) - set(previous_sql_map)
    removed_sql = set(previous_sql_map) - set(current_sql_map)
    overlap_rate = 0 if not previous_rows else len(overlap_sql) / len(previous_rows)
    status_balance_gap = abs(current_status_counter["pass"] - current_status_counter["fail"])
    bucket_diff = _counter_diff(current_bucket_counter, previous_bucket_counter)
    feature_diff = _counter_diff(current_feature_counter, previous_feature_counter)

    sorted_feature_diff = sorted(
        [(key, value) for key, value in feature_diff.items() if value != 0],
        key=lambda item: (-abs(item[1]), item[0]),
    )

    lines = [
        "# 黄金集稳定性分析",
        "",
        "## 当前黄金集画像",
        "",
        f"- 样本总数: {len(current_rows)}",
        f"- 正样本数: {current_status_counter['pass']}",
        f"- 负样本数: {current_status_counter['fail']}",
        f"- 正负样本差值: {status_balance_gap}",
        f"- 负样本错误类型数: {len(current_error_counter)}",
        f"- 负样本错误子类型数: {len(current_error_subtype_counter)}",
        f"- 来源类型数: {len(current_source_counter)}",
        f"- GT 强度类型数: {len(current_gt_strength_counter)}",
        f"- 二级类型数: {len(current_level2_counter)}",
        f"- 典型语法特性数: {len(current_feature_counter)}",
        f"- 2/1/0 评分分布: 2分={current_score_counter[2]}, 1分={current_score_counter[1]}, 0分={current_score_counter[0]}",
        "",
        "## 黄金集代表性",
        "",
    ]
    for bucket, target_count in TARGET_BUCKETS.items():
        lines.append(f"- {bucket}: {current_bucket_counter[bucket]}/{target_count}")

    lines.extend(["", "## 黄金集来源与错误类型", ""])
    for source, count in sorted(current_source_counter.items()):
        lines.append(f"- 来源 {source}: {count}")
    for strength, count in sorted(current_gt_strength_counter.items()):
        lines.append(f"- GT 强度 {strength}: {count}")
    for error_type, count in sorted(current_error_counter.items()):
        lines.append(f"- 错误类型 {error_type}: {count}")
    if not current_error_counter:
        lines.append("- 当前没有负样本错误类型")
    for error_subtype, count in sorted(current_error_subtype_counter.items()):
        lines.append(f"- 错误子类型 {error_subtype}: {count}")
    if not current_error_subtype_counter:
        lines.append("- 当前没有负样本错误子类型")

    lines.extend(["", "## 历史版本对比", ""])
    if previous_snapshot is None:
        lines.append("- 当前仅有一个历史快照，暂时无法与上一版做稳定性对比。")
    else:
        lines.append(f"- 上一版本快照: {previous_snapshot.name}")
        lines.append(f"- 当前版本快照: {latest_snapshot.name if latest_snapshot else 'unknown'}")
        lines.append(f"- Case 重叠数: {len(overlap_sql)}")
        lines.append(f"- Case 重叠率: {overlap_rate:.2%}")
        lines.append(f"- 新增 Case 数: {len(added_sql)}")
        lines.append(f"- 移除 Case 数: {len(removed_sql)}")
        lines.append(f"- 状态分布变化: {dict(_counter_diff(current_status_counter, previous_status_counter))}")

        lines.extend(["", "## 分布漂移", ""])
        for bucket, diff in bucket_diff.items():
            lines.append(f"- {bucket}: {diff:+d}")

        lines.extend(["", "## 特性漂移 Top", ""])
        if sorted_feature_diff:
            for feature, diff in sorted_feature_diff[:12]:
                lines.append(f"- {feature}: {diff:+d}")
        else:
            lines.append("- 当前与上一版在特性覆盖上没有变化")

        lines.extend(["", "## 稳定核心 Case", ""])
        stable_preview = sorted(overlap_sql)[:12]
        if stable_preview:
            for sql_key in stable_preview:
                row = current_sql_map[sql_key]
                lines.append(f"- {row['level1_category']}/{row['level2_category']} | {row['source']} | {row['sql_text'][:120]}")
        else:
            lines.append("- 当前没有稳定重叠 Case")

    lines.extend(
        [
            "",
            "## 稳定性结论",
            "",
            "- 黄金集的稳定性主要看四个维度：结构分布是否稳定、正负样本是否平衡、典型特性是否持续覆盖、历史版本重叠率是否可接受。",
            "- 当前报告将历史重叠率与分布漂移显式输出，避免只用“通过率高”来定义黄金集。",
            "- 后续扩集阶段优先补足 window、cte 等短板，同时保持新增 case 的来源可追溯与类型均衡。",
        ]
    )
    report = "\n".join(lines) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    return report
