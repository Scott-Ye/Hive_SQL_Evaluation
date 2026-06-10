from __future__ import annotations

from src.core.progress import print_stage
from src.pipelines.official_doc_pipeline import refresh_real_official_sources


def main() -> None:
    print_stage("开始刷新 Hive 官方文档来源")
    summary = refresh_real_official_sources()
    print("Hive official docs fetched and extracted.")
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
