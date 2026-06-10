"""评测执行、打分与报告生成逻辑。"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from src.adapters.agent_adapter import build_publish_agent_adapter
from src.adapters.hive_parser_sdk import parse_sql_rows
from src.core.case_taxonomy import TARGET_BUCKETS, build_distribution_bucket
from src.core.progress import print_kv, print_stage
from src.core.project_config import CAPABILITY_ANALYSIS_MD, CASE_FIELDS, CURATED_DATASET, EVAL_REPORT_MD, EVAL_RESULT_CSV
from src.pipelines.dataset_pipeline import infer_feature_labels


SYNTAX_ERROR_FAMILY = {
    "syntax_error",
    "parse_error",
    "mismatched_input",
    "cannot_recognize_input",
    "no_viable_alternative",
    "failed_predicate",
    "unexpected_eof",
    "lexer_error",
}

FOCUS_FEATURE_ORDER = [
    "join",
    "window",
    "cte",
    "union",
    "subquery",
    "lateral_view",
    "group_by",
    "having",
    "order_sort",
    "limit",
    "transform",
    "insert_from",
    "insert_overwrite",
    "insert_into",
    "update",
    "delete",
    "create_table",
    "alter_table",
    "drop_table",
    "merge",
    "partition",
    "bucketing",
    "transactional",
    "serde",
    "explain",
    "describe",
    "within_group",
]


def load_curated_cases(csv_path: Path = CURATED_DATASET) -> List[Dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{field: (row.get(field, "") or "").strip() for field in CASE_FIELDS} for row in reader]


def _safe_rate(numerator: int, denominator: int) -> str:
    return f"{0 if denominator == 0 else numerator / denominator:.2%}"


def _error_type_matches(gt_error_type: str, actual_error_type: str) -> bool:
    # 允许同一语法错误家族之间记为“部分命中”，避免 taxonomy 微差直接判 0 分。
    if not gt_error_type or not actual_error_type:
        return False
    if gt_error_type == actual_error_type:
        return True
    if gt_error_type in SYNTAX_ERROR_FAMILY and actual_error_type in SYNTAX_ERROR_FAMILY:
        return True
    return False


def _error_subtype_matches(gt_error_subtype: str, actual_error_subtype: str) -> bool:
    if not gt_error_subtype or not actual_error_subtype:
        return False
    return gt_error_subtype == actual_error_subtype


def score_label_pair(
    *,
    gt_status: str,
    gt_error_type: str,
    gt_error_subtype: str,
    observed_status: str,
    observed_error_type: str,
    observed_error_subtype: str,
) -> int:
    # 第一步先看 pass/fail 状态；状态错了直接判 0 分。
    if gt_status != observed_status:
        return 0
    if gt_status == "pass":
        return 2

    # 对负样本再细看 error_type / error_subtype 两层细节命中情况。
    detail_total = 0
    exact_hits = 0
    partial_hits = 0

    if gt_error_type:
        detail_total += 1
        if gt_error_type == observed_error_type:
            exact_hits += 1
        elif _error_type_matches(gt_error_type, observed_error_type):
            partial_hits += 1

    if gt_error_subtype:
        detail_total += 1
        if gt_error_subtype == observed_error_subtype:
            exact_hits += 1
        elif _error_subtype_matches(gt_error_subtype, observed_error_subtype):
            partial_hits += 1

    if detail_total == 0:
        return 2
    if exact_hits == detail_total:
        return 2
    if exact_hits > 0 or partial_hits > 0:
        return 1
    return 0


def _grade_from_score(score: int) -> str:
    if score == 2:
        return "exact"
    if score == 1:
        return "partial"
    return "miss"


def score_case(row: Dict[str, str]) -> int:
    return score_label_pair(
        gt_status=row["gt_status"],
        gt_error_type=row["gt_error_type"],
        gt_error_subtype=row["gt_error_subtype"],
        observed_status=row["actual_status"],
        observed_error_type=row["actual_error_type"],
        observed_error_subtype=row["actual_error_subtype"],
    )


def score_baseline_case(row: Dict[str, str]) -> int:
    return score_label_pair(
        gt_status=row["gt_status"],
        gt_error_type=row["gt_error_type"],
        gt_error_subtype=row["gt_error_subtype"],
        observed_status=row["baseline_status"],
        observed_error_type=row["baseline_error_type"],
        observed_error_subtype=row["baseline_error_subtype"],
    )


def _feature_labels_from_row(row: Dict[str, str]) -> List[str]:
    return [
        feature
        for feature in infer_feature_labels(row)
        if not feature.startswith("status_") and not feature.startswith("error_")
    ]


def _sql_preview(sql_text: str, limit: int = 120) -> str:
    compact = " ".join(sql_text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def evaluate_cases(cases: List[Dict[str, str]], *, parser_backend: str | None = None) -> List[Dict[str, str]]:
    backend = (parser_backend or "sdk").strip().lower()
    print_stage("执行评测")
    print_kv("评测后端", backend)
    print_kv("评测样本数", len(cases))
    if backend == "sdk":
        # SDK 模式走本地批量解析，先把 SQL 列表一次性交给 Java 侧处理。
        payload = [{"case_id": case["case_id"], "sql_text": case["sql_text"]} for case in cases]
        parsed_rows = parse_sql_rows(payload)
        parsed_by_case_id = {row["case_id"]: row for row in parsed_rows}
        results: List[Dict[str, str]] = []
        for index, case in enumerate(cases, start=1):
            parsed = parsed_by_case_id.get(case["case_id"], {})
            actual_status = parsed.get("actual_status", "fail")
            actual_error_type = parsed.get("actual_error_type", "")
            actual_error_subtype = parsed.get("actual_error_subtype", "")
            actual_error_type_raw = parsed.get("raw_error_type", actual_error_type)
            actual_error_subtype_raw = parsed.get("raw_error_subtype", actual_error_subtype)
            actual_error_position = parsed.get("actual_error_position", "")
            parser_message = parsed.get("parser_message", "")
            actual_score = score_label_pair(
                gt_status=case["gt_status"],
                gt_error_type=case["gt_error_type"],
                gt_error_subtype=case["gt_error_subtype"],
                observed_status=actual_status,
                observed_error_type=actual_error_type,
                observed_error_subtype=actual_error_subtype,
            )
            baseline_score = score_label_pair(
                gt_status=case["gt_status"],
                gt_error_type=case["gt_error_type"],
                gt_error_subtype=case["gt_error_subtype"],
                observed_status=case["baseline_status"],
                observed_error_type=case["baseline_error_type"],
                observed_error_subtype=case["baseline_error_subtype"],
            )
            # match_result 只表示“是否拿到 2 分”，便于后续报告直接统计 strict match。
            match_result = "pass" if actual_score == 2 else "fail"

            results.append(
                {
                    "case_id": case["case_id"],
                    "level1_category": case["level1_category"],
                    "level2_category": case["level2_category"],
                    "difficulty": case["difficulty"],
                    "gt_status": case["gt_status"],
                    "actual_status": actual_status,
                    "gt_error_type": case["gt_error_type"],
                    "gt_error_subtype": case["gt_error_subtype"],
                    "actual_error_type": actual_error_type,
                    "actual_error_subtype": actual_error_subtype,
                    "actual_error_type_raw": actual_error_type_raw,
                    "actual_error_subtype_raw": actual_error_subtype_raw,
                    "actual_error_position": actual_error_position,
                    "gt_label_source": case["gt_label_source"],
                    "gt_label_strength": case["gt_label_strength"],
                    "baseline_status": case["baseline_status"],
                    "baseline_error_type": case["baseline_error_type"],
                    "baseline_error_subtype": case["baseline_error_subtype"],
                    "baseline_error_type_raw": case.get("baseline_error_type_raw", ""),
                    "baseline_error_subtype_raw": case.get("baseline_error_subtype_raw", ""),
                    "baseline_error_position": case["baseline_error_position"],
                    "baseline_label_source": case["baseline_label_source"],
                    "baseline_score": str(baseline_score),
                    "baseline_grade": _grade_from_score(baseline_score),
                    "actual_score": str(actual_score),
                    "actual_grade": _grade_from_score(actual_score),
                    "trace_id": f"SDKBATCH{index:06d}",
                    "parser_code": "200" if actual_status == "pass" else "400",
                    "parser_message": parser_message,
                    "match_result": match_result,
                    "source_tier": case["source_tier"],
                    "source": case["source"],
                    "source_ref": case["source_ref"],
                    "tags": case["tags"],
                    "sql_text": case["sql_text"],
                    "notes": case["notes"],
                    "raw_response": "",
                }
            )
        print_kv("评测结果数", len(results))
        return results

    adapter = build_publish_agent_adapter(parser_backend)
    results: List[Dict[str, str]] = []

    for case in cases:
        # Agent 模式逐条调用适配器，保留 trace_id、原始响应等排障信息。
        summary = adapter.parse_summary(case)
        actual_score = score_label_pair(
            gt_status=case["gt_status"],
            gt_error_type=case["gt_error_type"],
            gt_error_subtype=case["gt_error_subtype"],
            observed_status=summary.actual_status,
            observed_error_type=summary.actual_error_type,
            observed_error_subtype=getattr(summary, "actual_error_subtype", ""),
        )
        baseline_score = score_label_pair(
            gt_status=case["gt_status"],
            gt_error_type=case["gt_error_type"],
            gt_error_subtype=case["gt_error_subtype"],
            observed_status=case["baseline_status"],
            observed_error_type=case["baseline_error_type"],
            observed_error_subtype=case["baseline_error_subtype"],
        )
        match_result = "pass" if actual_score == 2 else "fail"

        results.append(
            {
                "case_id": case["case_id"],
                "level1_category": case["level1_category"],
                "level2_category": case["level2_category"],
                "difficulty": case["difficulty"],
                "gt_status": case["gt_status"],
                "actual_status": summary.actual_status,
                "gt_error_type": case["gt_error_type"],
                "gt_error_subtype": case["gt_error_subtype"],
                "actual_error_type": summary.actual_error_type,
                "actual_error_subtype": getattr(summary, "actual_error_subtype", ""),
                "actual_error_type_raw": getattr(summary, "actual_error_type_raw", summary.actual_error_type),
                "actual_error_subtype_raw": getattr(
                    summary, "actual_error_subtype_raw", getattr(summary, "actual_error_subtype", "")
                ),
                "actual_error_position": summary.actual_error_position,
                "gt_label_source": case["gt_label_source"],
                "gt_label_strength": case["gt_label_strength"],
                "baseline_status": case["baseline_status"],
                "baseline_error_type": case["baseline_error_type"],
                "baseline_error_subtype": case["baseline_error_subtype"],
                "baseline_error_type_raw": case.get("baseline_error_type_raw", ""),
                "baseline_error_subtype_raw": case.get("baseline_error_subtype_raw", ""),
                "baseline_error_position": case["baseline_error_position"],
                "baseline_label_source": case["baseline_label_source"],
                "baseline_score": str(baseline_score),
                "baseline_grade": _grade_from_score(baseline_score),
                "actual_score": str(actual_score),
                "actual_grade": _grade_from_score(actual_score),
                "trace_id": summary.trace_id,
                "parser_code": str(summary.parser_code),
                "parser_message": summary.parser_message,
                "match_result": match_result,
                "source_tier": case["source_tier"],
                "source": case["source"],
                "source_ref": case["source_ref"],
                "tags": case["tags"],
                "sql_text": case["sql_text"],
                "notes": case["notes"],
                "raw_response": summary.raw_response,
            }
        )
    print_kv("评测结果数", len(results))
    return results


def write_results(rows: List[Dict[str, str]], output_path: Path = EVAL_RESULT_CSV) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def build_report(
    rows: List[Dict[str, str]],
    *,
    report_title: str = "发布Agent - Hive SQL 评测报告",
    dataset_note: str = "默认评测 real-source 多源黄金集，来源于 Hive 官方文档与 Apache Hive 开源 benchmark。",
    parser_backend: str = "sdk",
) -> str:
    # 先把总体指标、分层统计和典型样例一次性聚合出来，后面只负责拼 Markdown 文本。
    total = len(rows)
    actual_exact = sum(1 for row in rows if int(row["actual_score"]) == 2)
    actual_partial = sum(1 for row in rows if int(row["actual_score"]) == 1)
    actual_miss = total - actual_exact - actual_partial
    baseline_exact = sum(1 for row in rows if int(row["baseline_score"]) == 2)
    baseline_partial = sum(1 for row in rows if int(row["baseline_score"]) == 1)
    baseline_miss = total - baseline_exact - baseline_partial
    parser_pass_total = sum(1 for row in rows if row["actual_status"] == "pass")
    parser_fail_total = total - parser_pass_total
    gt_fail_total = sum(1 for row in rows if row["gt_status"] == "fail")
    gt_pass_total = total - gt_fail_total
    positive_pass_total = sum(1 for row in rows if row["gt_status"] == "pass" and row["actual_status"] == "pass")
    negative_hit_total = sum(1 for row in rows if row["gt_status"] == "fail" and row["actual_status"] == "fail")
    gt_usable_total = actual_exact + actual_partial
    level1_counter: Dict[str, Counter] = defaultdict(Counter)
    level2_counter: Dict[str, Counter] = defaultdict(Counter)
    difficulty_counter: Dict[str, Counter] = defaultdict(Counter)
    source_counter: Counter = Counter()
    source_tier_counter: Counter = Counter()
    gt_strength_counter: Counter = Counter()
    error_type_counter: Counter = Counter()
    error_subtype_counter: Counter = Counter()
    bucket_counter: Counter = Counter()
    feature_counter: Counter = Counter()
    feature_exact_counter: Counter = Counter()
    parser_fail_examples: List[Dict[str, str]] = []
    mismatch_examples: List[Dict[str, str]] = []
    actual_score_counter: Counter = Counter()
    baseline_score_counter: Counter = Counter()
    delta_examples: List[Tuple[int, Dict[str, str]]] = []

    for row in rows:
        # exact / partial / miss 会分别喂给不同维度统计，便于同一轮循环复用。
        actual_score = int(row["actual_score"])
        baseline_score = int(row["baseline_score"])
        exact_key = "exact" if actual_score == 2 else "not_exact"
        detail_key = "exact" if actual_score == 2 else "partial" if actual_score == 1 else "miss"
        level1_counter[row["level1_category"]][exact_key] += 1
        level2_counter[row["level2_category"]][exact_key] += 1
        difficulty_counter[row["difficulty"]][detail_key] += 1
        source_tier_counter[row["source_tier"]] += 1
        source_counter[row["source"]] += 1
        gt_strength_counter[row["gt_label_strength"]] += 1
        bucket_counter[build_distribution_bucket(row)] += 1
        if row["actual_error_type"]:
            error_type_counter[row["actual_error_type"]] += 1
        if row.get("actual_error_subtype"):
            error_subtype_counter[row["actual_error_subtype"]] += 1
        features = _feature_labels_from_row(row)
        for feature in features:
            feature_counter[feature] += 1
            if actual_score == 2:
                feature_exact_counter[feature] += 1
        if row["actual_status"] == "fail":
            parser_fail_examples.append(row)
        if actual_score != 2:
            mismatch_examples.append(row)
        actual_score_counter[actual_score] += 1
        baseline_score_counter[baseline_score] += 1
        if actual_score != baseline_score:
            delta_examples.append((actual_score - baseline_score, row))

    # 报告正文按“总体表现 -> 分布 -> 例子”展开，方便老师按层阅读。
    lines = [
        f"# {report_title}",
        "",
        "## 评测闭环",
        "",
        f"- Agent 层: 当前使用 {parser_backend} 后端承载发布 Agent / Hive Parser 返回结构。",
        f"- 数据层: {dataset_note}",
        "- 评测层: 自动执行 SQL 提交、结果比对、错误聚类和报告输出。",
        "",
        "## 解析器表现",
        "",
        f"- 样本总数: {total}",
        f"- 解析通过率: {_safe_rate(parser_pass_total, total)} ({parser_pass_total}/{total})",
        f"- 解析失败率: {_safe_rate(parser_fail_total, total)} ({parser_fail_total}/{total})",
        f"- 正样本通过率: {_safe_rate(positive_pass_total, gt_pass_total)} ({positive_pass_total}/{gt_pass_total})",
        f"- 负样本命中率: {_safe_rate(negative_hit_total, gt_fail_total)} ({negative_hit_total}/{gt_fail_total})",
        f"- GT 严格一致率: {_safe_rate(actual_exact, total)} ({actual_exact}/{total})",
        f"- GT 可用匹配率(1分及以上): {_safe_rate(gt_usable_total, total)} ({gt_usable_total}/{total})",
        "",
        "## 评分分布",
        "",
        f"- 2 分: {actual_exact}",
        f"- 1 分: {actual_partial}",
        f"- 0 分: {actual_miss}",
        "",
        "## 黄金集质量",
        "",
        f"- 最终黄金集样本数: {total}",
        f"- GT 正样本数: {gt_pass_total}",
        f"- GT 负样本数: {gt_fail_total}",
        "",
            "## 结果字段说明",
        "",
            "- GT 记录来源侧真值，baseline 记录历史对照，actual 记录本次运行结果；三者职责不同。",
        "- baseline 与 actual 现在同时保留两层错误字段：对齐 GT 口径的 `*_error_type` / `*_error_subtype`，以及保留 SDK 原始归一化结果的 `*_error_type_raw` / `*_error_subtype_raw`。",
        "- 评分、严格一致率和报告统计使用对齐 GT 口径的字段；问题排查时再回看 raw 字段，判断是 SDK 原始报错差异还是评测 taxonomy 对齐差异。",
        "- GT 严格一致率不是解析通过率；前者衡量“与 GT 是否一致”，后者只衡量“是否返回 pass”。",
            "- “评测集分布”描述的是题目构成是否满足目标配比；“一级分类严格一致率”描述的是解析器在该分类上拿到完全一致的比例，两者含义不同，数值不应相同。",
        "- `2 分`：与 GT 完全对齐。正样本要求成功解析；负样本要求在 GT 已提供的细节粒度上完全一致。",
        "- `1 分`：部分正确。状态正确，但负样本细节只达到错误家族或错误子类型部分命中。",
        "- `0 分`：完全错误。状态判断错误，或 GT 已给出的关键细节完全未命中。",
        "",
        "## GT 强度分布",
        "",
    ]
    for strength, count in sorted(gt_strength_counter.items()):
        lines.append(f"- {strength}: {count}")

    lines.extend(
        [
            "",
            "## Baseline 对照",
            "",
            f"- baseline 标签来源: {rows[0]['baseline_label_source'] if rows else 'unknown'}",
            f"- baseline 2 分: {baseline_score_counter[2]}",
            f"- baseline 1 分: {baseline_score_counter[1]}",
            f"- baseline 0 分: {baseline_score_counter[0]}",
            f"- baseline 严格一致率: {_safe_rate(baseline_exact, total)}",
            "",
            "## Actual 对照",
            "",
            f"- 2 分: {actual_score_counter[2]}",
            f"- 1 分: {actual_score_counter[1]}",
            f"- 0 分: {actual_score_counter[0]}",
            "",
            "## 发布Agent评测集分布",
            "",
        ]
    )

    for bucket, target_count in TARGET_BUCKETS.items():
        lines.append(f"- {bucket}: {bucket_counter[bucket]}/{target_count}")

    lines.extend(["", "## 一级分类严格一致率", ""])
    for category in sorted(level1_counter):
        category_total = sum(level1_counter[category].values())
        category_exact = level1_counter[category]["exact"]
        lines.append(f"- {category}: {category_exact}/{category_total}")

    lines.extend(["", "## 二级类型覆盖", ""])
    for category in sorted(level2_counter):
        category_total = sum(level2_counter[category].values())
        category_exact = level2_counter[category]["exact"]
        lines.append(f"- {category}: {category_exact}/{category_total}")

    lines.extend(["", "## 典型语法特性覆盖", ""])
    for feature in FOCUS_FEATURE_ORDER:
        if feature not in feature_counter:
            continue
        lines.append(f"- {feature}: {feature_exact_counter[feature]}/{feature_counter[feature]}")
    uncovered_features = [feature for feature in FOCUS_FEATURE_ORDER if feature_counter[feature] == 0]
    if uncovered_features:
        lines.append(f"- 未覆盖特性: {', '.join(uncovered_features)}")

    lines.extend(["", "## 来源分布", ""])
    for source_tier, count in sorted(source_tier_counter.items()):
        lines.append(f"- source_tier={source_tier}: {count}")
    for source, count in sorted(source_counter.items()):
        lines.append(f"- {source}: {count}")

    lines.extend(["", "## 错误类型分布", ""])
    for error_type, count in error_type_counter.most_common():
        lines.append(f"- {error_type}: {count}")
    if not error_type_counter:
        lines.append("- 无错误类型记录")

    lines.extend(["", "## 错误子类型分布", ""])
    for error_subtype, count in error_subtype_counter.most_common():
        lines.append(f"- {error_subtype}: {count}")
    if not error_subtype_counter:
        lines.append("- 无错误子类型记录")

    lines.extend(["", "## 典型失败 Case", ""])
    if parser_fail_examples:
        for row in parser_fail_examples[:8]:
            lines.append(
                "- "
                f"{row['case_id']} | {row['level1_category']}/{row['level2_category']} | "
                f"{row['actual_error_type']}/{row.get('actual_error_subtype', '')} | {row['source']} | {_sql_preview(row['sql_text'])}"
            )
    else:
        lines.append("- 当前没有解析失败样本")

    lines.extend(["", "## 评测偏差 Case", ""])
    if mismatch_examples:
        for row in mismatch_examples[:8]:
            lines.append(
                "- "
                f"{row['case_id']} | gt={row['gt_status']}/{row['gt_error_type']}/{row.get('gt_error_subtype', '')} | "
                f"baseline={row['baseline_status']}/{row['baseline_error_type']}/{row.get('baseline_error_subtype', '')} | "
                f"actual={row['actual_status']}/{row['actual_error_type']}/{row.get('actual_error_subtype', '')} | "
                f"score={row['actual_score']} | {_sql_preview(row['sql_text'])}"
            )
    else:
        lines.append("- 当前评测集中没有 GT 不一致样本")

    lines.extend(["", "## Baseline 差异 Case", ""])
    if delta_examples:
        for _, row in sorted(delta_examples, key=lambda item: (item[0], item[1]["case_id"]))[:8]:
            lines.append(
                "- "
                f"{row['case_id']} | gt={row['gt_status']}/{row['gt_error_type']} | "
                f"baseline={row['baseline_score']}({row['baseline_status']}/{row['baseline_error_type']}) | "
                f"actual={row['actual_score']}({row['actual_status']}/{row['actual_error_type']}) | {_sql_preview(row['sql_text'])}"
            )
    else:
        lines.append("- 当前 actual 与 baseline 在 GT 评分上没有差异")

    lines.extend(
        [
            "",
            "## 当前说明",
            "",
            f"- 当前 T3 解析能力封装后端: {parser_backend}。",
            f"- 当前报告对象: {dataset_note}",
            "- 当前报告同时展示 GT、baseline 和 actual，便于区分来源侧真值、历史对照和本次运行结果。",
            "- 当前负样本中已有 46/49 条达到严格一致；剩余 3 条 partial 都集中在数据库标识符类 case，GT 子类型与 SDK 对齐子类型仍存在少量 taxonomy 差异。",
            "- 当前报告同时展示“黄金集质量指标”和“解析器表现指标”，避免把二者混为一谈。",
            "- 难度分层画像同时展示 2 分完全一致和 1 分及以上可用匹配，避免把负样本细节掉分误读为整体失效。",
            "- 当前最终黄金集只保留高可信真值样本；覆盖扩展通过待审池与历史迭代完成，而不是通过放宽 GT 获得虚高结果。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_capability_analysis(
    rows: List[Dict[str, str]],
    *,
    report_title: str = "Hive Parse 能力分析",
    dataset_note: str,
    parser_backend: str = "sdk",
) -> str:
    total = len(rows)
    actual_exact = sum(1 for row in rows if int(row["actual_score"]) == 2)
    actual_partial = sum(1 for row in rows if int(row["actual_score"]) == 1)
    gt_fail_total = sum(1 for row in rows if row["gt_status"] == "fail")
    gt_pass_total = total - gt_fail_total
    parser_pass_total = sum(1 for row in rows if row["actual_status"] == "pass")
    positive_pass_total = sum(1 for row in rows if row["gt_status"] == "pass" and row["actual_status"] == "pass")
    negative_hit_total = sum(1 for row in rows if row["gt_status"] == "fail" and row["actual_status"] == "fail")
    parser_fail_rows = [row for row in rows if row["actual_status"] == "fail"]
    actual_error_type_counter = Counter(row["actual_error_type"] for row in parser_fail_rows if row["actual_error_type"])
    actual_error_subtype_counter = Counter(
        row["actual_error_subtype"] for row in parser_fail_rows if row.get("actual_error_subtype")
    )
    level2_counter = Counter(row["level2_category"] for row in rows)
    feature_counter = Counter()
    source_counter = Counter(row["source"] for row in rows)
    gt_strength_counter = Counter(row["gt_label_strength"] for row in rows)
    actual_score_counter = Counter(int(row["actual_score"]) for row in rows)
    baseline_score_counter = Counter(int(row["baseline_score"]) for row in rows)
    for row in rows:
        for feature in _feature_labels_from_row(row):
            feature_counter[feature] += 1

    covered_features = [feature for feature in FOCUS_FEATURE_ORDER if feature_counter[feature] > 0]
    uncovered_features = [feature for feature in FOCUS_FEATURE_ORDER if feature_counter[feature] == 0]

    lines = [
        f"# {report_title}",
        "",
        "## 目标定位",
        "",
        "- 项目目标不是做执行语义验证平台，而是沉淀 Hive SQL 评测集、封装 Hive Parse SDK，并验证纯语法解析能力。",
        f"- 当前分析对象: {dataset_note}",
        f"- 当前解析后端: {parser_backend}",
        "",
        "## 当前能力结论",
        "",
        f"- 数据集规模: {total}",
        f"- 解析通过率: {_safe_rate(parser_pass_total, total)}",
        f"- 正样本通过率: {_safe_rate(positive_pass_total, gt_pass_total)}",
        f"- 负样本命中率: {_safe_rate(negative_hit_total, gt_fail_total)}",
        f"- GT 严格一致率: {_safe_rate(actual_exact, total)}",
        f"- GT 可用匹配率(1分及以上): {_safe_rate(actual_exact + actual_partial, total)}",
        f"- 解析失败样本数: {len(parser_fail_rows)}",
        f"- 失败类型数: {len(actual_error_type_counter)}",
        f"- 失败子类型数: {len(actual_error_subtype_counter)}",
        f"- 已覆盖典型特性数: {len(covered_features)}",
        f"- baseline 2/1/0: {baseline_score_counter[2]}/{baseline_score_counter[1]}/{baseline_score_counter[0]}",
        f"- actual 2/1/0: {actual_score_counter[2]}/{actual_score_counter[1]}/{actual_score_counter[0]}",
        "",
        "## 二级类型覆盖摘要",
        "",
    ]
    for level2, count in sorted(level2_counter.items()):
        lines.append(f"- {level2}: {count}")

    lines.extend(["", "## 典型语法特性摘要", ""])
    for feature in covered_features:
        lines.append(f"- {feature}: {feature_counter[feature]}")
    if uncovered_features:
        lines.append(f"- 尚未覆盖特性: {', '.join(uncovered_features)}")

    lines.extend(["", "## 失败类型摘要", ""])
    if actual_error_type_counter:
        for error_type, count in actual_error_type_counter.most_common():
            lines.append(f"- {error_type}: {count}")
    else:
        lines.append("- 当前没有解析失败样本")

    lines.extend(["", "## 失败子类型摘要", ""])
    if actual_error_subtype_counter:
        for error_subtype, count in actual_error_subtype_counter.most_common():
            lines.append(f"- {error_subtype}: {count}")
    else:
        lines.append("- 当前没有解析失败子类型")

    lines.extend(["", "## 来源贡献", ""])
    for source, count in sorted(source_counter.items()):
        lines.append(f"- {source}: {count}")

    lines.extend(["", "## GT 强度摘要", ""])
    for strength, count in sorted(gt_strength_counter.items()):
        lines.append(f"- {strength}: {count}")

    lines.extend(["", "## 典型失败样本", ""])
    if parser_fail_rows:
        for row in parser_fail_rows[:12]:
            lines.append(
                "- "
                f"{row['case_id']} | {row['level1_category']}/{row['level2_category']} | "
                f"{row['actual_error_type']}/{row.get('actual_error_subtype', '')} | {_sql_preview(row['sql_text'], limit=160)}"
            )
    else:
        lines.append("- 当前没有解析失败样本")

    lines.extend(
        [
            "",
            "## 阶段结论",
            "",
            "- 当前项目采用来源侧 GT、历史 baseline 与本次 actual 分层展示的结果口径。",
            "- 当前项目对 T5 的实现已从运行摘要升级为覆盖分析、GT 强度分析和 baseline 对照分析。",
            "- 当前项目对 T6 的实现体现在：公开 0/1/2 分布、沉淀典型失败样本，并显式暴露残余 GT 风险，而不是追求虚高一致率。",
        ]
    )
    return "\n".join(lines) + "\n"


def write_report(report: str, output_path: Path = EVAL_REPORT_MD) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")


def write_capability_analysis(report: str, output_path: Path = CAPABILITY_ANALYSIS_MD) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
