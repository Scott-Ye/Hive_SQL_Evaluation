from __future__ import annotations

from src.core.progress import print_stage
from src.pipelines.dataset_pipeline import build_curated_dataset


def main() -> None:
    print_stage("开始构建评测集")
    summary = build_curated_dataset()
    print("Dataset build finished.")
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
