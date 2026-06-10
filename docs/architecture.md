# 任务二工程架构说明

本文只解释工程分层、自动化链路和任务映射。

- 数量口径与候选池统计，统一见 `outputs/maintenance/maintenance_report.md`
- GT / baseline / actual 与评分口径，统一见 `outputs/parse_evaluation_standard.md`
- 解析器表现与 baseline / actual 对照，统一见 `outputs/eval_report_real_gold.md`
- 稳定核心与黄金集迭代规则，统一见 `outputs/gold_iteration_report.md`

## 1. 当前工程如何体现 Agent

当前工程已经按职责拆成 5 层：

1. `src/cli`
   - 命令入口，负责串起构建、评测和报告生成
2. `src/pipelines`
   - 多源采集、GT 构建、黄金集沉淀、样本约束说明
3. `src/adapters`
   - `ParseDriver -> Java SDK -> Python Adapter`
4. `src/reporting`
   - 评测、评分、稳定性分析、报告输出
5. `src/core`
   - 全局配置、分类映射、通用加载逻辑

其中 `Agent` 的体现位置在 [agent_adapter.py](file:///C:/Users/INT/Desktop/工程训练营-构建大数据开发套件智能体评估体系/src/adapters/agent_adapter.py)：

- `HiveParseSdkAdapter`
  - 当前唯一后端
  - 把本地 Java Hive Parse SDK 封装成与课题 Agent 一致的返回结构

## 2. 自动化链路

### 多源采集

当前 `real-source` 已接入 3 类真实可追溯来源：

- Hive 官方文档
  - [official_doc_pipeline.py](file:///C:/Users/INT/Desktop/工程训练营-构建大数据开发套件智能体评估体系/src/pipelines/official_doc_pipeline.py)
  - 自动发现页面、抓取 HTML、缓存页面、抽取 SQL 代码块
- Apache Hive benchmark
  - [open_benchmark_pipeline.py](file:///C:/Users/INT/Desktop/工程训练营-构建大数据开发套件智能体评估体系/src/pipelines/open_benchmark_pipeline.py)
  - 自动抓取 `clientpositive/clientnegative/positive/negative`
- Apache Hive parser unit tests
  - [parser_unit_pipeline.py](file:///C:/Users/INT/Desktop/工程训练营-构建大数据开发套件智能体评估体系/src/pipelines/parser_unit_pipeline.py)
  - 递归扫描 parser 单测并抽取 SQL

### 自动清洗与沉淀

执行 `python -m src.cli.run_eval` 后会自动：

1. 刷新官方文档候选池
2. 刷新 benchmark 候选池
3. 刷新 parser unit 候选池
4. 多源汇聚、清洗和 SQL 去重
5. 按 GT 强度划分高可信候选池与待审池
6. 检查最终黄金集样本约束
7. 仅在高可信候选池中按 `QUERY 50 / DDL 20 / DML 20 / UTILITY 10` 沉淀最终 100 条
8. 在原始多源候选池阶段冻结 baseline 标签
9. 输出版本快照、manifest、维护报告、评测报告和稳定性分析

### 负样本策略

当前负样本不再让 SDK 回写 GT，而是：

1. 先从真实来源抽取负例候选
2. 再按来源证据强弱标成 `strong / medium / weak GT`
3. 最终严格黄金集只保留 `strong GT`
4. `medium / weak GT` 进入待审池，不参与最终打分

这样可以保证 GT 继续以来源证据为主，而 baseline / actual 只承担历史对照和本次结果记录。

## 3. 解析能力封装

当前解析链路是：

`ParseDriver -> Java SDK -> Python Adapter -> Evaluator`

- Java 侧
  - [HiveParseSdkCli.java](file:///C:/Users/INT/Desktop/工程训练营-构建大数据开发套件智能体评估体系/sdk/hive_parse_sdk/src/main/java/com/trainingcamp/hive/HiveParseSdkCli.java)
  - 直接调用 Apache Hive `ParseDriver`
- Python SDK 侧
  - [hive_parser_sdk.py](file:///C:/Users/INT/Desktop/工程训练营-构建大数据开发套件智能体评估体系/src/adapters/hive_parser_sdk.py)
  - 负责编译 Java CLI、组装 classpath、批量提交 SQL
- Agent 侧
  - [agent_adapter.py](file:///C:/Users/INT/Desktop/工程训练营-构建大数据开发套件智能体评估体系/src/adapters/agent_adapter.py)
  - 统一把 SDK 输出适配成项目评测需要的结构

## 4. 与课题阶段任务的映射

### T1 评测集设计

已覆盖：

- 一级分类
- 二级分类
- 难度
- GT 状态与错误粒度
- GT 强度分层
- 来源追踪字段

### T2 评测集建设

已覆盖：

- 多源自动化采集
- 高可信候选池与待审池分层
- 最终 100 条按比例沉淀
- 正负样本接近平衡
- GT / baseline / actual 字段分工清晰

### T3 解析能力封装

已覆盖：

- 真实 `ParseDriver` 接入
- 本地 Java Hive Parse SDK
- Python 调用封装
- Agent 返回结构适配

### T4 评测框架开发

已覆盖：

- 数据集加载
- baseline / actual 双对照
- 0 / 1 / 2 评分
- 结果 CSV 导出
- 自动报告生成

### T5 报告输出

已覆盖：

- 真实来源黄金集报告
- 能力分析报告
- GT 评判标准说明
- 自动维护报告

### T6 项目沉淀

已覆盖：

- 版本快照
- manifest
- 黄金集样本约束说明
- 黄金集稳定性分析
- 黄金集迭代报告

## 5. 历史版本对比和黄金集稳定性分析

这一项**已经完成**，不再是未完成项。

当前对应产物与代码如下：

- [gold_stability.py](file:///C:/Users/INT/Desktop/工程训练营-构建大数据开发套件智能体评估体系/src/reporting/gold_stability.py)
  - 负责历史版本重叠率、分布漂移、特性漂移分析
- [gold_iteration.py](file:///C:/Users/INT/Desktop/工程训练营-构建大数据开发套件智能体评估体系/src/reporting/gold_iteration.py)
  - 负责稳定核心、待审池、停止标准与迭代规则说明
- [gold_stability_analysis.md](file:///C:/Users/INT/Desktop/工程训练营-构建大数据开发套件智能体评估体系/outputs/gold_stability_analysis.md)
- [gold_iteration_report.md](file:///C:/Users/INT/Desktop/工程训练营-构建大数据开发套件智能体评估体系/outputs/gold_iteration_report.md)

这一项**需要做，而且已经做了**，因为没有历史版本比对，就无法判断当前 100 条到底是“稳定黄金集”，还是“每次重跑都会换掉一大批样本”的偶然结果。

## 6. 当前仍未完成的部分

- 还没有接入更多第三方真实来源，如更多 Hive 社区样本或其他开源评测集
- 还没有做语义级校验，如表存在性、字段存在性、权限和执行环境
- 仍有 `medium / weak GT` 待审池尚未人工升标，部分特性覆盖仍依赖后续审校补洞
