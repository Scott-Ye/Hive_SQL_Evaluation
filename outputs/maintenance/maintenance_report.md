# 评测集自动维护报告

## Real Source 数据集

- 当前有效样本: 100
- 去重移除样本: 0
- GT pass 样本: 51
- GT fail 样本: 49
- 当前最终黄金集口径: 只保留高可信真值样本
- 已隔离待审样本数: 455

### 原始抓取与过滤规模

- Hive 官方文档原始抽取: 224
- Apache Hive benchmark 原始抽取: 3186
- Apache Hive parser unit 原始抽取: 651
- 清洗后真实候选总数: 3943
- 选样前高可信候选池样本数: 3488
- 去重后高可信候选池样本数: 2457
- 待审池数量(不是原始抓取总量): 455

### 来源分布

- apache_hive_clientpositive: 46
- apache_hive_parser_unit: 49
- apache_hive_positive: 2
- hive_official_docs: 3

### 目标分布校准

- QUERY_50: 50/50
- DDL_CREATE_ALTER_20: 20/20
- DML_WRITE_UPDATE_20: 20/20
- UTILITY_OTHER_10: 10/10

### 二级类型分布

- ALTER_TABLE_SYNTAX: 2
- CREATE_DATABASE_SYNTAX: 5
- CREATE_TABLE_SYNTAX: 8
- CTE: 3
- DROP_DATABASE_SYNTAX: 2
- DROP_TABLE_SYNTAX: 3
- EXPLAIN: 2
- GROUP_BY: 5
- INSERT_FROM: 2
- INSERT_INTO_SYNTAX: 7
- INSERT_OVERWRITE_SYNTAX: 5
- JOIN: 7
- LATERAL_VIEW: 1
- LIMIT: 2
- LOAD_DATA_SYNTAX: 8
- ORDER_SORT: 6
- OTHER: 6
- SELECT_BASIC: 6
- TRANSFORM: 2
- UNION: 5
- USE_DB: 2
- WHERE_FILTER: 7
- WINDOW: 4

### GT 强度分布

- strong: 100

### 待审池原因分布

- medium_gt_requires_manual_review: 260
- weak_gt_excluded_from_strict_gold: 195

### 典型语法特性覆盖

- alter_table: 2
- alter_table_syntax: 2
- bucketing: 1
- create_database_syntax: 5
- create_table: 8
- create_table_syntax: 8
- cte: 4
- ddl: 20
- delete: 1
- describe: 3
- dml: 20
- drop_database_syntax: 2
- drop_table: 3
- drop_table_syntax: 3
- explain: 2
- group_by: 12
- having: 11
- insert_from: 4
- insert_into: 7
- insert_into_syntax: 7
- insert_overwrite: 9
- insert_overwrite_syntax: 5
- join: 11
- lateral_view: 2
- limit: 17
- load_data_syntax: 8
- merge: 1
- order_sort: 30
- other: 6
- partition: 17
- query: 50
- select_basic: 6
- serde: 5
- subquery: 46
- transactional: 2
- transform: 5
- union: 10
- update: 1
- use_db: 2
- utility: 10
- where_filter: 7
- window: 8

### 负样本错误类型

- parse_error: 49

### 负样本错误子类型

- quoted_identifier_path_syntax: 47
- reserved_keyword_table_name: 2

### Baseline 标签分布

- fail: 52
- pass: 48

## 分层说明

- real-source 黄金集来自可追溯的多源候选池，当前包括 Hive 官方文档、Apache Hive 开源 benchmark、Apache Hive parser unit tests。
- GT 标签来自原始来源断言、目录语义和保守规则；baseline 只单独记录历史对照结果。
- baseline 标签记录当前本地 Hive Parse SDK 的冻结结果，不参与真实黄金集选样。
- 当前 real-source 黄金集只保留高可信真值样本，中低可信样本会进入待审池，不参与最终评分。
- 所有样本均要求 source_tier 和 source_ref 明确可追踪。
