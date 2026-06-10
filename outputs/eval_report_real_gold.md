# 发布Agent - Hive SQL 多源真实来源黄金集评测报告

## 评测闭环

- Agent 层: 当前使用 sdk 后端承载发布 Agent / Hive Parser 返回结构。
- 数据层: 评测 real-source 多源黄金集，来源于 Hive 官方文档、Apache Hive 开源 benchmark、Apache Hive parser unit tests。
- 评测层: 自动执行 SQL 提交、结果比对、错误聚类和报告输出。

## 解析器表现

- 样本总数: 100
- 解析通过率: 48.00% (48/100)
- 解析失败率: 52.00% (52/100)
- 正样本通过率: 94.12% (48/51)
- 负样本命中率: 100.00% (49/49)
- GT 严格一致率: 94.00% (94/100)
- GT 可用匹配率(1分及以上): 97.00% (97/100)

## 评分分布

- 2 分: 94
- 1 分: 3
- 0 分: 3

## 黄金集质量

- 最终黄金集样本数: 100
- GT 正样本数: 51
- GT 负样本数: 49

## 结果字段说明

- GT 记录来源侧真值，baseline 记录历史对照，actual 记录本次运行结果；三者职责不同。
- baseline 与 actual 现在同时保留两层错误字段：对齐 GT 口径的 `*_error_type` / `*_error_subtype`，以及保留 SDK 原始归一化结果的 `*_error_type_raw` / `*_error_subtype_raw`。
- 评分、严格一致率和报告统计使用对齐 GT 口径的字段；问题排查时再回看 raw 字段，判断是 SDK 原始报错差异还是评测 taxonomy 对齐差异。
- GT 严格一致率不是解析通过率；前者衡量“与 GT 是否一致”，后者只衡量“是否返回 pass”。
- “评测集分布”描述的是题目构成是否满足目标配比；“一级分类严格一致率”描述的是解析器在该分类上拿到完全一致的比例，两者含义不同，数值不应相同。
- `2 分`：与 GT 完全对齐。正样本要求成功解析；负样本要求在 GT 已提供的细节粒度上完全一致。
- `1 分`：部分正确。状态正确，但负样本细节只达到错误家族或错误子类型部分命中。
- `0 分`：完全错误。状态判断错误，或 GT 已给出的关键细节完全未命中。

## GT 强度分布

- strong: 100

## Baseline 对照

- baseline 标签来源: local_hive_parse_sdk
- baseline 2 分: 94
- baseline 1 分: 3
- baseline 0 分: 3
- baseline 严格一致率: 94.00%

## Actual 对照

- 2 分: 94
- 1 分: 3
- 0 分: 3

## 发布Agent评测集分布

- QUERY_50: 50/50
- DDL_CREATE_ALTER_20: 20/20
- DML_WRITE_UPDATE_20: 20/20
- UTILITY_OTHER_10: 10/10

## 一级分类严格一致率

- DDL: 18/20
- DML: 20/20
- QUERY: 47/50
- UTILITY: 9/10

## 二级类型覆盖

- ALTER_TABLE_SYNTAX: 2/2
- CREATE_DATABASE_SYNTAX: 4/5
- CREATE_TABLE_SYNTAX: 8/8
- CTE: 3/3
- DROP_DATABASE_SYNTAX: 1/2
- DROP_TABLE_SYNTAX: 3/3
- EXPLAIN: 2/2
- GROUP_BY: 5/5
- INSERT_FROM: 2/2
- INSERT_INTO_SYNTAX: 7/7
- INSERT_OVERWRITE_SYNTAX: 5/5
- JOIN: 7/7
- LATERAL_VIEW: 0/1
- LIMIT: 2/2
- LOAD_DATA_SYNTAX: 8/8
- ORDER_SORT: 6/6
- OTHER: 6/6
- SELECT_BASIC: 6/6
- TRANSFORM: 2/2
- UNION: 5/5
- USE_DB: 1/2
- WHERE_FILTER: 7/7
- WINDOW: 2/4

## 典型语法特性覆盖

- join: 11/11
- window: 6/8
- cte: 4/4
- union: 10/10
- subquery: 46/46
- lateral_view: 1/2
- group_by: 11/12
- having: 11/11
- order_sort: 28/30
- limit: 17/17
- transform: 5/5
- insert_from: 4/4
- insert_overwrite: 9/9
- insert_into: 7/7
- update: 1/1
- delete: 1/1
- create_table: 8/8
- alter_table: 2/2
- drop_table: 3/3
- merge: 1/1
- partition: 17/17
- bucketing: 1/1
- transactional: 2/2
- serde: 5/5
- explain: 2/2
- describe: 3/3
- 未覆盖特性: within_group

## 来源分布

- source_tier=real: 100
- apache_hive_clientpositive: 46
- apache_hive_parser_unit: 49
- apache_hive_positive: 2
- hive_official_docs: 3

## 错误类型分布

- parse_error: 52

## 错误子类型分布

- quoted_identifier_path_syntax: 44
- quoted_database_identifier_syntax: 3
- window_clause_syntax: 2
- reserved_keyword_table_name: 2
- generic_parse_failure: 1

## 典型失败 Case

- HIVE_REAL_001 | QUERY/JOIN | parse_error/quoted_identifier_path_syntax | apache_hive_parser_unit | select "cbo_/t3////".c_int, c, count(*) from (select key as a, c_int+1 as b, sum(c_int) as c from "c/b/o_t1" where ("...
- HIVE_REAL_003 | QUERY/WHERE_FILTER | parse_error/quoted_identifier_path_syntax | apache_hive_parser_unit | select * from (select "//cbo_t2".key as x, c_int as c_int, (((c_int+c_float)*10)+5) as y from "c/b/o_t1" as "//cbo_t2...
- HIVE_REAL_005 | QUERY/GROUP_BY | parse_error/quoted_identifier_path_syntax | apache_hive_parser_unit | select p_mfgr, p_name, avg(p_size) from "p/a/r/t" group by p_mfgr, p_name having p_name in (select first_value(p_name...
- HIVE_REAL_007 | QUERY/SELECT_BASIC | parse_error/quoted_identifier_path_syntax | apache_hive_parser_unit | select x from (select count(c_int) over() as x, sum(c_float) over() from "c/b/o_t1") "c/b/o_t1"
- HIVE_REAL_009 | QUERY/ORDER_SORT | parse_error/quoted_identifier_path_syntax | apache_hive_parser_unit | select * from (select count(c_int) over(partition by c_float order by key), sum(c_float) over(partition by c_float or...
- HIVE_REAL_011 | QUERY/UNION | parse_error/quoted_identifier_path_syntax | apache_hive_parser_unit | select r2.key from (select key, c_int from (select key, c_int from "c/b/o_t1" union all select key, c_int from "cbo_/...
- HIVE_REAL_013 | QUERY/CTE | parse_error/quoted_identifier_path_syntax | apache_hive_parser_unit | with q1 as ( select "c/b/o_t1".c_int c_int from q2 join "c/b/o_t1" where q2.c_int = "c/b/o_t1".c_int and "c/b/o_t1".d...
- HIVE_REAL_015 | QUERY/WINDOW | parse_error/quoted_identifier_path_syntax | apache_hive_parser_unit | select i, a, h, b, c, d, e, f, g, a as x, a +1 as y from (select max(c_int) over (partition by key order by value ran...

## 评测偏差 Case

- HIVE_REAL_016 | gt=pass// | baseline=fail/parse_error/window_clause_syntax | actual=fail/parse_error/window_clause_syntax | score=0 | SELECT a, SUM(b) OVER (PARTITION BY c ORDER BY d ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) FROM T;
- HIVE_REAL_018 | gt=pass// | baseline=fail/parse_error/generic_parse_failure | actual=fail/parse_error/generic_parse_failure | score=0 | SELECT adid, count(1) FROM pageAds LATERAL VIEW explode(adid_list) adTable AS adid GROUP BY adid;
- HIVE_REAL_038 | gt=pass// | baseline=fail/parse_error/window_clause_syntax | actual=fail/parse_error/window_clause_syntax | score=0 | SELECT a, AVG(b) OVER (PARTITION BY c ORDER BY d ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING) FROM T;
- HIVE_REAL_055 | gt=fail/parse_error/quoted_identifier_path_syntax | baseline=fail/parse_error/quoted_database_identifier_syntax | actual=fail/parse_error/quoted_database_identifier_syntax | score=1 | drop database "db~!@#$%^&*(),<>" cascade
- HIVE_REAL_069 | gt=fail/parse_error/quoted_identifier_path_syntax | baseline=fail/parse_error/quoted_database_identifier_syntax | actual=fail/parse_error/quoted_database_identifier_syntax | score=1 | create database "db~!@#$%^&*(),<>"
- HIVE_REAL_093 | gt=fail/parse_error/quoted_identifier_path_syntax | baseline=fail/parse_error/quoted_database_identifier_syntax | actual=fail/parse_error/quoted_database_identifier_syntax | score=1 | use "db~!@#$%^&*(),<>"

## Baseline 差异 Case

- 当前 actual 与 baseline 在 GT 评分上没有差异

## 当前说明

- 当前 T3 解析能力封装后端: sdk。
- 当前报告对象: 评测 real-source 多源黄金集，来源于 Hive 官方文档、Apache Hive 开源 benchmark、Apache Hive parser unit tests。
- 当前报告同时展示 GT、baseline 和 actual，便于区分来源侧真值、历史对照和本次运行结果。
- 当前负样本中已有 46/49 条达到严格一致；剩余 3 条 partial 都集中在数据库标识符类 case，GT 子类型与 SDK 对齐子类型仍存在少量 taxonomy 差异。
- 当前报告同时展示“黄金集质量指标”和“解析器表现指标”，避免把二者混为一谈。
- 难度分层画像同时展示 2 分完全一致和 1 分及以上可用匹配，避免把负样本细节掉分误读为整体失效。
- 当前最终黄金集只保留高可信真值样本；覆盖扩展通过待审池与历史迭代完成，而不是通过放宽 GT 获得虚高结果。
