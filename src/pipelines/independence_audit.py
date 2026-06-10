from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Dict, List

from src.core.project_config import INDEPENDENCE_AUDIT_MD


def assert_gt_baseline_independence(
    rows: List[Dict[str, str]],
    *,
    stage: str,
    require_strong_only: bool,
    require_empty_baseline: bool,
) -> None:
    issues: List[str] = []
    for index, row in enumerate(rows, start=1):
        case_label = row.get("case_id", f"{stage}_{index}")
        gt_strength = (row.get("gt_label_strength", "") or "").lower()
        baseline_status = (row.get("baseline_status", "") or "").strip()

        if require_strong_only and gt_strength != "strong":
            issues.append(f"{case_label}: 当前阶段要求高可信真值，但实际为 {row.get('gt_label_strength', '')}")
        if require_empty_baseline and (
            baseline_status
            or row.get("baseline_error_type", "")
            or row.get("baseline_error_subtype", "")
            or row.get("baseline_error_position", "")
            or row.get("baseline_label_source", "")
        ):
            issues.append(f"{case_label}: 当前阶段 baseline 字段必须为空")

    if issues:
        raise ValueError("黄金集样本约束检查失败:\n" + "\n".join(issues[:50]))


def build_independence_audit_report(
    final_rows: List[Dict[str, str]],
    *,
    strict_gold_candidate_rows: List[Dict[str, str]],
    strict_gold_deduped_candidate_rows: List[Dict[str, str]],
    output_path: Path = INDEPENDENCE_AUDIT_MD,
) -> str:
    gt_strength_counter = Counter(row.get("gt_label_strength", "") for row in final_rows)
    gt_source_counter = Counter(row.get("gt_label_source", "") for row in final_rows)
    non_strong_rows = [row for row in final_rows if (row.get("gt_label_strength", "") or "").lower() != "strong"]

    lines = [
        "# 黄金集样本约束说明",
        "",
        "## 当前结果",
        "",
        f"- 最终黄金集样本数: {len(final_rows)}",
        f"- 选样前高可信候选池样本数: {len(strict_gold_candidate_rows)}",
        f"- 去重后高可信候选池样本数: {len(strict_gold_deduped_candidate_rows)}",
        f"- 最终黄金集非高可信真值样本数: {len(non_strong_rows)}",
        "- 当前约束结论: 最终黄金集只保留高可信真值样本。",
        "",
        "## GT 来源分布",
        "",
    ]
    for source, count in sorted(gt_source_counter.items()):
        lines.append(f"- {source}: {count}")

    lines.extend(["", "## GT 强度分布", ""])
    for strength, count in sorted(gt_strength_counter.items()):
        lines.append(f"- {strength}: {count}")

    lines.extend(
        [
            "",
            "## 当前约束",
            "",
            "- 约束 1: 最终 real-source 黄金集只保留高可信真值样本。",
            "- 约束 2: baseline 在原始多源候选池首次冻结时写入，后续评测只生成 actual。",
            "- 约束 3: 选样逻辑按固定排序、目标分布和覆盖补洞规则执行，不使用随机抽样。",
        ]
    )
    report = "\n".join(lines) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    return report
