from __future__ import annotations

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
SOURCE_MATERIAL_DIR = DATA_DIR / "source_materials"
REAL_SOURCE_DIR = SOURCE_MATERIAL_DIR / "real"
REAL_HTML_CACHE_DIR = REAL_SOURCE_DIR / "official_html_cache"
REAL_EXTRACTED_JSONL = REAL_SOURCE_DIR / "hive_official_docs.jsonl"
OPEN_BENCHMARK_DIR = REAL_SOURCE_DIR / "open_benchmark"
OPEN_BENCHMARK_JSONL = OPEN_BENCHMARK_DIR / "apache_hive_open_tests.jsonl"
PARSER_UNIT_DIR = REAL_SOURCE_DIR / "parser_unit"
PARSER_UNIT_JSONL = PARSER_UNIT_DIR / "apache_hive_parser_unit_cases.jsonl"
CURATED_DIR = DATA_DIR / "curated"
VERSION_DIR = DATA_DIR / "versions"
OUTPUT_DIR = ROOT_DIR / "outputs"
MAINTENANCE_DIR = OUTPUT_DIR / "maintenance"
SDK_DIR = ROOT_DIR / "sdk" / "hive_parse_sdk"
SDK_LIB_DIR = SDK_DIR / "lib"
SDK_BUILD_DIR = SDK_DIR / "build"
SDK_CLASS_DIR = SDK_BUILD_DIR / "classes"
SDK_SOURCE_FILE = (
    SDK_DIR
    / "src"
    / "main"
    / "java"
    / "com"
    / "trainingcamp"
    / "hive"
    / "HiveParseSdkCli.java"
)
SDK_MAIN_CLASS = "com.trainingcamp.hive.HiveParseSdkCli"

CURATED_REAL_DATASET = CURATED_DIR / "hive_cases_real_multisource_gold.csv"
REAL_REVIEW_QUEUE_DATASET = CURATED_DIR / "hive_cases_real_review_candidates.csv"
CURATED_DATASET = CURATED_REAL_DATASET
VERSION_MANIFEST = VERSION_DIR / "manifest.json"
MAINTENANCE_REPORT = MAINTENANCE_DIR / "maintenance_report.md"
EVAL_RESULT_CSV = OUTPUT_DIR / "eval_results_real_gold.csv"
EVAL_REPORT_MD = OUTPUT_DIR / "eval_report_real_gold.md"
CAPABILITY_ANALYSIS_MD = OUTPUT_DIR / "parse_capability_analysis.md"
GOLD_STABILITY_REPORT_MD = OUTPUT_DIR / "gold_stability_analysis.md"
GOLD_ITERATION_REPORT_MD = OUTPUT_DIR / "gold_iteration_report.md"
INDEPENDENCE_AUDIT_MD = OUTPUT_DIR / "independence_audit.md"
EVALUATION_STANDARD_MD = OUTPUT_DIR / "parse_evaluation_standard.md"
TARGET_CASE_COUNT = 100

CASE_FIELDS = [
    "case_id",
    "level1_category",
    "level2_category",
    "difficulty",
    "gt_status",
    "gt_error_type",
    "gt_error_subtype",
    "gt_label_source",
    "gt_label_strength",
    "baseline_status",
    "baseline_error_type",
    "baseline_error_subtype",
    "baseline_error_type_raw",
    "baseline_error_subtype_raw",
    "baseline_error_position",
    "baseline_label_source",
    "sql_text",
    "source_tier",
    "source",
    "source_ref",
    "tags",
    "notes",
]

RAW_SOURCE_FIELDS = [
    "level1_category",
    "level2_category",
    "difficulty",
    "gt_status",
    "gt_error_type",
    "gt_error_subtype",
    "gt_label_source",
    "gt_label_strength",
    "baseline_status",
    "baseline_error_type",
    "baseline_error_subtype",
    "baseline_error_type_raw",
    "baseline_error_subtype_raw",
    "baseline_error_position",
    "baseline_label_source",
    "sql_text",
    "source_tier",
    "source",
    "source_ref",
    "tags",
    "notes",
]
