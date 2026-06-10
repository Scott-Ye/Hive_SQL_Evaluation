# Hive SQL 评测工程

这是“发布 Agent - Hive SQL 评测集沉淀与 Hive 解析能力验证”的当前可运行版本。

项目目标是沉淀一套可维护的 Hive SQL 评测底座，包括：

- 多源真实来源候选池
- 最终黄金集与待审池
- 基于 Hive `ParseDriver` 的本地 Java SDK
- `GT / baseline / actual` 分层评测
- 自动生成的评测报告与迭代分析

## 核心特点

- GT 与 baseline 分离，避免用本地 SDK 回写标准答案
- 最终黄金集只保留高可信 GT，待审样本单独隔离
- 评测同时输出 `GT vs baseline` 与 `GT vs actual`
- 评分采用 `2 / 1 / 0` 三档，不把严格一致率和解析通过率混为一谈

## 项目结构

```text
.
├─ README.md
├─ requirements.txt
├─ docs/
│  └─ architecture.md
├─ src/
│  ├─ cli/
│  ├─ pipelines/
│  ├─ reporting/
│  ├─ adapters/
│  └─ core/
├─ sdk/
│  └─ hive_parse_sdk/
│     ├─ src/
│     ├─ lib/
│     └─ pom.xml
├─ data/
│  ├─ source_materials/
│  ├─ curated/
│  └─ versions/
└─ outputs/
```

## 环境要求

- Windows 10 / 11
- Python 3.10+，推荐 3.11+
- JDK 11

说明：

- Python 主评测链路基本只依赖标准库
- `requirements.txt` 中的 `pandas`、`matplotlib` 主要用于辅助可视化产物生成，安装后不影响主链路
- Java SDK 依赖通过 `sdk/hive_parse_sdk/lib/` 中的本地 jar 提供，分享项目时这一目录需要保留

## 安装

如需安装额外 Python 依赖：

```bash
pip install -r requirements.txt
```

## 快速开始

### 1. 刷新官方文档来源

```bash
python -m src.cli.fetch_hive_official_docs
```

### 2. 构建数据集

```bash
python -m src.cli.build_dataset
```

### 3. 执行完整评测

```bash
python -m src.cli.run_eval
```

## 重点查看文件

- 最终黄金集：`data/curated/hive_cases_real_multisource_gold.csv`
- 待审池：`data/curated/hive_cases_real_review_candidates.csv`
- 主评测报告：`outputs/eval_report_real_gold.md`
- 能力分析：`outputs/parse_capability_analysis.md`
- 评分标准：`outputs/parse_evaluation_standard.md`
- 独立性审计：`outputs/independence_audit.md`
- 版本迭代说明：`outputs/gold_iteration_report.md`
- 项目结构说明：`docs/architecture.md`
- 主流程入口：`src/cli/run_eval.py`
- Java SDK 实现：`sdk/hive_parse_sdk/src/main/java/com/trainingcamp/hive/HiveParseSdkCli.java`

## 答辩材料

- 答辩材料首页：`outputs/star_defense/index.html`
- 答辩材料子页面：`outputs/star_defense/pages/`

使用方式：

- 在 GitHub 仓库中，可直接进入 `outputs/star_defense/index.html` 与 `outputs/star_defense/pages/` 查看答辩材料文件位置和页面源码。
- 如需按最终展示效果浏览，请下载仓库后在本地浏览器中直接打开 `outputs/star_defense/index.html`。
- `index.html` 是整套答辩材料的总入口，页面内已串联主报告、评分标准、样本约束说明、代码页和补充页。

## 当前评测口径

- 评测目标是纯语法解析，不做执行语义验证
- 数据集来自真实来源候选池，最终黄金集只保留高可信真值样本
- 最终指标需要同时看解析通过率、正样本通过率、负样本命中率、GT 严格一致率和三档评分分布

## 补充说明

- `sdk/hive_parse_sdk/pom.xml` 主要用于让 IDE 正确识别 Java 源码和本地 jar 依赖
- Java SDK 的 `build/` 目录属于运行时编译产物，可在重新编译时自动生成
