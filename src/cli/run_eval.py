from __future__ import annotations

from src.core.progress import print_stage
from src.core.project_config import (
    CAPABILITY_ANALYSIS_MD,
    CURATED_DATASET,
    EVALUATION_STANDARD_MD,
    EVAL_REPORT_MD,
    EVAL_RESULT_CSV,
    INDEPENDENCE_AUDIT_MD,
    GOLD_ITERATION_REPORT_MD,
    GOLD_STABILITY_REPORT_MD,
)
from src.pipelines.dataset_pipeline import build_curated_dataset
from src.reporting.evaluation_standard import build_evaluation_standard_report
from src.reporting.evaluator import (
    build_capability_analysis,
    build_report,
    evaluate_cases,
    load_curated_cases,
    write_capability_analysis,
    write_report,
    write_results,
)
from src.reporting.gold_iteration import build_gold_iteration_report
from src.reporting.gold_stability import build_gold_stability_report


def main() -> None:
    parser_backend = "sdk"
    real_dataset_note = (
        "评测 real-source 多源黄金集，来源于 Hive 官方文档、Apache Hive 开源 benchmark、"
        "Apache Hive parser unit tests。"
    )
    print_stage("开始执行完整评测链路")
    build_summary = build_curated_dataset()
    print_stage("加载最终黄金集并执行评测")
    real_cases = load_curated_cases(CURATED_DATASET)
    real_results = evaluate_cases(real_cases, parser_backend=parser_backend)
    print_stage("写出评测结果与分析报告")
    write_results(real_results, EVAL_RESULT_CSV)
    write_report(
        build_report(
            real_results,
            report_title="发布Agent - Hive SQL 多源真实来源黄金集评测报告",
            dataset_note=real_dataset_note,
            parser_backend=parser_backend,
        ),
        EVAL_REPORT_MD,
    )
    write_capability_analysis(
        build_capability_analysis(
            real_results,
            report_title="Hive Parse 多源黄金集能力分析",
            dataset_note=real_dataset_note,
            parser_backend=parser_backend,
        ),
        CAPABILITY_ANALYSIS_MD,
    )
    build_evaluation_standard_report(real_results, output_path=EVALUATION_STANDARD_MD)
    build_gold_stability_report(real_cases, real_results, output_path=GOLD_STABILITY_REPORT_MD)
    build_gold_iteration_report(
        real_cases,
        real_results,
        strict_candidate_count=int(build_summary["real_strict_candidate_count"]),
        strict_candidate_deduped_count=int(build_summary["real_deduped_count"]),
        output_path=GOLD_ITERATION_REPORT_MD,
    )

    print(f"Real-source dataset built: {build_summary['real_count']} cases")
    print(f"Real-source dataset path: {build_summary['real_dataset_path']}")
    print(f"Real results written to: {EVAL_RESULT_CSV}")
    print(f"Real report written to: {EVAL_REPORT_MD}")
    print(f"Capability analysis written to: {CAPABILITY_ANALYSIS_MD}")
    print(f"Evaluation standard written to: {EVALUATION_STANDARD_MD}")
    print(f"Gold constraint summary written to: {INDEPENDENCE_AUDIT_MD}")
    print(f"Gold stability analysis written to: {GOLD_STABILITY_REPORT_MD}")
    print(f"Gold iteration report written to: {GOLD_ITERATION_REPORT_MD}")


if __name__ == "__main__":
    main()
