# Hive Parse 多源黄金集能力分析

## 目标定位

- 项目目标不是做执行语义验证平台，而是沉淀 Hive SQL 评测集、封装 Hive Parse SDK，并验证纯语法解析能力。
- 当前分析对象: 评测 real-source 多源黄金集，来源于 Hive 官方文档、Apache Hive 开源 benchmark、Apache Hive parser unit tests。
- 当前解析后端: sdk

## 当前能力结论

- 数据集规模: 100
- 解析通过率: 48.00%
- 正样本通过率: 94.12%
- 负样本命中率: 100.00%
- GT 严格一致率: 94.00%
- GT 可用匹配率(1分及以上): 97.00%
- 解析失败样本数: 52
- 失败类型数: 1
- 失败子类型数: 5
- 已覆盖典型特性数: 26
- baseline 2/1/0: 94/3/3
- actual 2/1/0: 94/3/3

## 二级类型覆盖摘要

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

## 典型语法特性摘要

- join: 11
- window: 8
- cte: 4
- union: 10
- subquery: 46
- lateral_view: 2
- group_by: 12
- having: 11
- order_sort: 30
- limit: 17
- transform: 5
- insert_from: 4
- insert_overwrite: 9
- insert_into: 7
- update: 1
- delete: 1
- create_table: 8
- alter_table: 2
- drop_table: 3
- merge: 1
- partition: 17
- bucketing: 1
- transactional: 2
- serde: 5
- explain: 2
- describe: 3
- 尚未覆盖特性: within_group

## 失败类型摘要

- parse_error: 52

## 失败子类型摘要

- quoted_identifier_path_syntax: 44
- quoted_database_identifier_syntax: 3
- window_clause_syntax: 2
- reserved_keyword_table_name: 2
- generic_parse_failure: 1

## 来源贡献

- apache_hive_clientpositive: 46
- apache_hive_parser_unit: 49
- apache_hive_positive: 2
- hive_official_docs: 3

## GT 强度摘要

- strong: 100

## 典型失败样本

- HIVE_REAL_001 | QUERY/JOIN | parse_error/quoted_identifier_path_syntax | select "cbo_/t3////".c_int, c, count(*) from (select key as a, c_int+1 as b, sum(c_int) as c from "c/b/o_t1" where ("c/b/o_t1".c_int + 1 >= 0) and ("c/b/o_t1...
- HIVE_REAL_003 | QUERY/WHERE_FILTER | parse_error/quoted_identifier_path_syntax | select * from (select "//cbo_t2".key as x, c_int as c_int, (((c_int+c_float)*10)+5) as y from "c/b/o_t1" as "//cbo_t2" where "//cbo_t2".c_int >= 0 and c_floa...
- HIVE_REAL_005 | QUERY/GROUP_BY | parse_error/quoted_identifier_path_syntax | select p_mfgr, p_name, avg(p_size) from "p/a/r/t" group by p_mfgr, p_name having p_name in (select first_value(p_name) over(partition by p_mfgr order by p_si...
- HIVE_REAL_007 | QUERY/SELECT_BASIC | parse_error/quoted_identifier_path_syntax | select x from (select count(c_int) over() as x, sum(c_float) over() from "c/b/o_t1") "c/b/o_t1"
- HIVE_REAL_009 | QUERY/ORDER_SORT | parse_error/quoted_identifier_path_syntax | select * from (select count(c_int) over(partition by c_float order by key), sum(c_float) over(partition by c_float order by key), max(c_int) over(partition b...
- HIVE_REAL_011 | QUERY/UNION | parse_error/quoted_identifier_path_syntax | select r2.key from (select key, c_int from (select key, c_int from "c/b/o_t1" union all select key, c_int from "cbo_/t3////" )r1 union all select key, c_int ...
- HIVE_REAL_013 | QUERY/CTE | parse_error/quoted_identifier_path_syntax | with q1 as ( select "c/b/o_t1".c_int c_int from q2 join "c/b/o_t1" where q2.c_int = "c/b/o_t1".c_int and "c/b/o_t1".dt='2014'), q2 as ( select c_int,c_boolea...
- HIVE_REAL_015 | QUERY/WINDOW | parse_error/quoted_identifier_path_syntax | select i, a, h, b, c, d, e, f, g, a as x, a +1 as y from (select max(c_int) over (partition by key order by value range UNBOUNDED PRECEDING) a, min(c_int) ov...
- HIVE_REAL_016 | QUERY/WINDOW | parse_error/window_clause_syntax | SELECT a, SUM(b) OVER (PARTITION BY c ORDER BY d ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) FROM T;
- HIVE_REAL_017 | QUERY/LIMIT | parse_error/quoted_identifier_path_syntax | select key from(select key from (select key from "c/b/o_t1" limit 5)"//cbo_t2" limit 5)"cbo_/t3////" limit 5
- HIVE_REAL_018 | QUERY/LATERAL_VIEW | parse_error/generic_parse_failure | SELECT adid, count(1) FROM pageAds LATERAL VIEW explode(adid_list) adTable AS adid GROUP BY adid;
- HIVE_REAL_019 | QUERY/JOIN | parse_error/quoted_identifier_path_syntax | select a, c, count(*) from (select key as a, c_int+1 as b, sum(c_int) as c from "c/b/o_t1" where ("c/b/o_t1".c_int + 1 >= 0) and ("c/b/o_t1".c_int > 0 or "c/...

## 阶段结论

- 当前项目采用来源侧 GT、历史 baseline 与本次 actual 分层展示的结果口径。
- 当前项目对 T5 的实现已从运行摘要升级为覆盖分析、GT 强度分析和 baseline 对照分析。
- 当前项目对 T6 的实现体现在：公开 0/1/2 分布、沉淀典型失败样本，并显式暴露残余 GT 风险，而不是追求虚高一致率。
