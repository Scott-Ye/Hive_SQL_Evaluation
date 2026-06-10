from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from src.core.project_config import CASE_FIELDS, GOLD_ITERATION_REPORT_MD, REAL_REVIEW_QUEUE_DATASET, VERSION_DIR
from src.pipelines.dataset_pipeline import infer_feature_labels, normalize_case_row, normalize_sql
from src.reporting.evaluator import FOCUS_FEATURE_ORDER


REVIEW_QUEUE_FIELDS = CASE_FIELDS + ["review_reason", "review_priority"]


def _read_case_rows(csv_path: Path, fieldnames: List[str]) -> List[Dict[str, str]]:
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: List[Dict[str, str]] = []
        for row in reader:
            normalized = normalize_case_row(row)
            for field in fieldnames:
                normalized.setdefault(field, (row.get(field, "") or "").strip())
            rows.append({field: (normalized.get(field, "") or "").strip() for field in fieldnames})
        return rows


def _read_review_queue() -> List[Dict[str, str]]:
    return _read_case_rows(REAL_REVIEW_QUEUE_DATASET, REVIEW_QUEUE_FIELDS)


def _snapshot_versions() -> List[Path]:
    return sorted(VERSION_DIR.glob("hive_cases_real_multisource_gold_*.csv"))


def _stable_core(rows_by_snapshot: List[List[Dict[str, str]]]) -> List[Dict[str, str]]:
    if not rows_by_snapshot:
        return []
    occurrence_counter: Dict[str, int] = Counter()
    latest_row_by_sql: Dict[str, Dict[str, str]] = {}
    gt_signature_by_sql: Dict[str, set[Tuple[str, str, str, str]]] = defaultdict(set)

    for snapshot_rows in rows_by_snapshot:
        seen_in_snapshot = set()
        for row in snapshot_rows:
            sql_key = normalize_sql(row["sql_text"])
            if sql_key in seen_in_snapshot:
                continue
            seen_in_snapshot.add(sql_key)
            occurrence_counter[sql_key] += 1
            latest_row_by_sql[sql_key] = row
            gt_signature_by_sql[sql_key].add(
                (
                    row["gt_status"],
                    row["gt_error_type"],
                    row["gt_error_subtype"],
                    row["gt_label_strength"],
                )
            )

    required_count = len(rows_by_snapshot)
    stable_rows = [
        latest_row_by_sql[sql_key]
        for sql_key, count in occurrence_counter.items()
        if count == required_count and len(gt_signature_by_sql[sql_key]) == 1
    ]
    stable_rows.sort(key=lambda row: (row["level1_category"], row["level2_category"], row["source"], row["sql_text"]))
    return stable_rows


def _feature_counter(rows: List[Dict[str, str]]) -> Counter:
    counter: Counter = Counter()
    for row in rows:
        for feature in infer_feature_labels(row):
            if feature.startswith("status_") or feature.startswith("error_"):
                continue
            counter[feature] += 1
    return counter


def build_gold_iteration_report(
    current_rows: List[Dict[str, str]],
    current_results: List[Dict[str, str]],
    *,
    strict_candidate_count: int | None = None,
    strict_candidate_deduped_count: int | None = None,
    output_path: Path = GOLD_ITERATION_REPORT_MD,
) -> str:
    review_rows = _read_review_queue()
    review_reason_counter = Counter(row["review_reason"] for row in review_rows)
    review_source_counter = Counter(row["source"] for row in review_rows)
    review_strength_counter = Counter(row["gt_label_strength"] for row in review_rows)

    versions = _snapshot_versions()
    recent_snapshots = versions[-3:] if len(versions) >= 3 else versions
    recent_snapshot_rows = [_read_case_rows(path, CASE_FIELDS) for path in recent_snapshots]
    stable_core_rows = _stable_core(recent_snapshot_rows)
    stable_core_sql = {normalize_sql(row["sql_text"]) for row in stable_core_rows}
    current_sql = {normalize_sql(row["sql_text"]) for row in current_rows}
    non_stable_current_count = len(current_sql - stable_core_sql)

    current_feature_counter = _feature_counter(current_rows)
    uncovered_focus_features = [
        feature for feature in FOCUS_FEATURE_ORDER if current_feature_counter.get(feature, 0) == 0
    ]

    parser_gap_rows = [row for row in current_results if int(row["actual_score"]) < 2]
    parser_gap_score_counter = Counter(int(row["actual_score"]) for row in parser_gap_rows)
    parser_gap_level2_counter = Counter(row["level2_category"] for row in parser_gap_rows)

    lines = [
        "# 黄金集迭代方案",
        "",
        "## 当前策略",
        "",
        "- 最终黄金集只保留高可信真值样本。",
        "- 中等可信和低可信样本全部进入待审池，不参与最终打分。",
        "- 通过率只能通过两种诚实方式提升：提升 GT 质量，或提升解析器能力；不能通过删难题、贴合当前 SDK 标签来提升。",
        "",
        "## 初始黄金集与最终黄金集",
        "",
        "- 初始黄金集更准确地说是“初始黄金候选集”：它由当时可获得的高可信候选池按目标分布、正负平衡、去重和覆盖补洞规则选出。",
        "- 初始黄金集已经具备来源可追溯、结构分布达标和 baseline 对照可用等基础条件，但它还没有经过多轮版本演进来验证哪些 case 是稳定核心。",
        "- 最终黄金集是在初始候选集基础上，继续经历版本快照比对、稳定核心保留、边缘样本替换和待审池升标后收敛得到的版本。",
        "- 因此，二者的差别不只是“最终版多了稳定核心验证”，还包括：最终版对历史漂移更敏感、对覆盖缺口更清楚、对待审样本边界更清楚。",
        "",
        "## 当前迭代状态",
        "",
        f"- 当前最终黄金集规模: {len(current_rows)}",
    ]
    if strict_candidate_count is not None:
        lines.append(f"- 选样前高可信候选池样本数: {strict_candidate_count}")
    if strict_candidate_deduped_count is not None:
        lines.append(f"- 去重后高可信候选池样本数: {strict_candidate_deduped_count}")
    lines.extend(
        [
        f"- 当前待审池规模: {len(review_rows)}",
        f"- 最近 {len(recent_snapshots)} 个快照稳定核心数: {len(stable_core_rows)}",
        f"- 当前非稳定核心样本数: {non_stable_current_count}",
        f"- 当前 actual 低于 2 分样本数: {len(parser_gap_rows)}",
        f"- 当前 actual 1/0 分分布: 1分={parser_gap_score_counter[1]}, 0分={parser_gap_score_counter[0]}",
        "",
        "## 待审池画像",
        "",
        ]
    )
    for key, count in sorted(review_strength_counter.items()):
        lines.append(f"- GT 强度 {key}: {count}")
    for key, count in sorted(review_reason_counter.items()):
        lines.append(f"- 待审原因 {key}: {count}")
    for key, count in sorted(review_source_counter.items())[:10]:
        lines.append(f"- 待审来源 {key}: {count}")

    lines.extend(["", "## 稳定核心策略", ""])
    if stable_core_rows:
        for row in stable_core_rows[:12]:
            lines.append(f"- {row['level1_category']}/{row['level2_category']} | {row['source']} | {row['sql_text'][:100]}")
    else:
        lines.append("- 历史快照不足，暂时无法计算稳定核心。")

    lines.extend(["", "## 初始黄金集构建原理", ""])
    lines.extend(
        [
            "- 第一步: 从真实来源抽取候选样本，并为每条样本写入独立 GT 标签。",
            "- 第二步: 在原始多源候选池上统一冻结 baseline，对后续版本保留原始对照。",
            "- 第三步: 过滤到高可信候选池，只保留 gt_status 明确且 GT 强度足够高的样本。",
            "- 第四步: 按 QUERY 50 / DDL 20 / DML 20 / UTILITY 10 做结构选样，并尽量维持正负样本均衡。",
            "- 第五步: 做去重、特性补洞和错误类型补洞，形成第一版可用黄金候选集。",
            "- 第六步: 选样逻辑按固定排序、历史偏好和覆盖补洞规则确定，不使用随机抽样；因此固定输入下会收敛到同一版黄金集。",
        ]
    )

    lines.extend(["", "## 解析器改进 Backlog", ""])
    for level2, count in parser_gap_level2_counter.most_common(12):
        lines.append(f"- {level2}: {count}")
    if not parser_gap_level2_counter:
        lines.append("- 当前没有解析器能力缺口。")

    lines.extend(["", "## 特性补洞方向", ""])
    if uncovered_focus_features:
        lines.append(f"- 当前最终黄金集未覆盖特性: {', '.join(uncovered_focus_features)}")
    else:
        lines.append("- 当前重点特性已全部覆盖，后续优先扩展更细粒度负样本类型。")

    lines.extend(
        [
            "",
            "## 升级规则",
            "",
            "- 规则 1: 新样本先入候选池，不直接进最终黄金集。",
            "- 规则 2: 只有 GT 来源足够强，或完成人工审校后，样本才能从待审池提升为高可信真值。",
            "- 规则 3: 样本进入最终黄金集时优先满足当前覆盖缺口；若同一样本同时也是当前解析器容易通过的 case，可以同时满足，但覆盖缺口优先级更高，不能把“容易通过”作为主导入选条件。",
            "- 规则 4: 样本进入最终黄金集后，尽量连续保留多个版本；只有重复、失真或被更强 GT 替代时才移除。",
            "- 规则 5: 每次迭代同时看四个指标：GT 强度、覆盖率、稳定核心比例、真实 0/1/2 分布。",
            "- 规则 6: 当前没有进入最终黄金集的重点特性（例如 within_group）必须保留在待审池并优先审校，不能因未覆盖就直接忽略。",
            "",
            "## 停止标准",
            "",
            "- 标准 1: 最终黄金集全部为高可信真值样本。",
            "- 标准 2: 结构分布稳定满足 QUERY 50 / DDL 20 / DML 20 / UTILITY 10，且正负样本接近平衡。",
            "- 标准 3: 最近多个版本的稳定核心比例足够高，当前 gold 只发生小规模轮换，而不是大范围抖动。",
            "- 标准 4: 已知重点特性没有被“遗忘”；若仍未入最终黄金集，必须在待审池中有明确补洞计划。",
            "- 标准 5: 新增样本主要来自 GT 升级或覆盖补洞，而不是为了迎合当前解析器结果去改题。",
            "",
            "## 不允许的做法",
            "",
            "- 不允许因为某类 case 通过率低，就系统性删掉这类 case。",
            "- 不允许只追求高通过率，而牺牲负样本、多样性或来源可追溯性。",
            "- 不允许把还未升到 strong 的样本直接塞进最终 gold，只为了让报告看起来更全面。",
            "",
            "## 当前执行流程",
            "",
            "- 第一步: 从待审池中按覆盖缺口挑样本做人工审校。",
            "- 第二步: 把审校通过的样本升级成高可信真值，再进入下一版候选池。",
            "- 第三步: 运行版本对比，优先保留稳定核心，少量替换非稳定边缘样本。",
            "- 第四步: 单独跟踪 1 分和 0 分 case，把它们作为解析器优化 backlog，而不是修改 GT 去迁就当前结果。",
        ]
    )
    report = "\n".join(lines) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    return report
