"""刷新 Hive 官方文档来源的命令行入口。"""

from __future__ import annotations

from src.core.progress import print_stage
from src.pipelines.official_doc_pipeline import refresh_real_official_sources


def main() -> None:
    # 刷新官方文档、缓存页面，并输出执行摘要。
    print_stage("开始刷新 Hive 官方文档来源")
    summary = refresh_real_official_sources()
    print("Hive official docs fetched and extracted.")
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
