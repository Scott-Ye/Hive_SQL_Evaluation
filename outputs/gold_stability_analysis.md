# 黄金集稳定性分析

## 当前黄金集画像

- 样本总数: 100
- 正样本数: 51
- 负样本数: 49
- 正负样本差值: 2
- 负样本错误类型数: 1
- 负样本错误子类型数: 2
- 来源类型数: 4
- GT 强度类型数: 1
- 二级类型数: 23
- 典型语法特性数: 42
- 2/1/0 评分分布: 2分=94, 1分=3, 0分=3

## 黄金集代表性

- QUERY_50: 50/50
- DDL_CREATE_ALTER_20: 20/20
- DML_WRITE_UPDATE_20: 20/20
- UTILITY_OTHER_10: 10/10

## 黄金集来源与错误类型

- 来源 apache_hive_clientpositive: 46
- 来源 apache_hive_parser_unit: 49
- 来源 apache_hive_positive: 2
- 来源 hive_official_docs: 3
- GT 强度 strong: 100
- 错误类型 parse_error: 49
- 错误子类型 quoted_identifier_path_syntax: 47
- 错误子类型 reserved_keyword_table_name: 2

## 历史版本对比

- 上一版本快照: hive_cases_real_multisource_gold_20260610_133546.csv
- 当前版本快照: hive_cases_real_multisource_gold_20260610_133854.csv
- Case 重叠数: 100
- Case 重叠率: 100.00%
- 新增 Case 数: 0
- 移除 Case 数: 0
- 状态分布变化: {'fail': 0, 'pass': 0}

## 分布漂移

- DDL_CREATE_ALTER_20: +0
- DML_WRITE_UPDATE_20: +0
- QUERY_50: +0
- UTILITY_OTHER_10: +0

## 特性漂移 Top

- 当前与上一版在特性覆盖上没有变化

## 稳定核心 Case

- DDL/ALTER_TABLE_SYNTAX | apache_hive_clientpositive | ALTER TABLE alter_file_format_test SET FILEFORMAT INPUTFORMAT 'org.apache.hadoop.mapred.TextInputFormat' OUTPUTFORMAT 'o
- DDL/ALTER_TABLE_SYNTAX | apache_hive_clientpositive | alter table tst1_n1 partition (ds = '1') into 6 buckets
- DDL/CREATE_DATABASE_SYNTAX | apache_hive_parser_unit | create database "db~!@#$%^&*(),<>"
- DDL/CREATE_TABLE_SYNTAX | apache_hive_parser_unit | create table "//cbo_t2"(key string, value string, c_int int, c_float float, c_boolean boolean) partitioned by (dt string
- DDL/CREATE_TABLE_SYNTAX | apache_hive_parser_unit | create table "c/b/o_t1"(key string, value string, c_int int, c_float float, c_boolean boolean) partitioned by (dt string
- DDL/CREATE_TABLE_SYNTAX | apache_hive_parser_unit | create table "cbo_/t3////"(key string, value string, c_int int, c_float float, c_boolean boolean) row format delimited f
- DDL/CREATE_TABLE_SYNTAX | apache_hive_parser_unit | CREATE TABLE "line/item" (L_ORDERKEY INT, L_PARTKEY INT, L_SUPPKEY INT, L_LINENUMBER INT, L_QUANTITY DOUBLE, L_EXTENDEDP
- DDL/CREATE_TABLE_SYNTAX | apache_hive_parser_unit | CREATE TABLE HAVING (col STRING)
- DDL/CREATE_TABLE_SYNTAX | apache_hive_clientpositive | CREATE TABLE IF NOT EXISTS test_update_partition_parquet_mmctas PARTITIONED BY (id) STORED AS PARQUET TBLPROPERTIES('tra
- DDL/CREATE_TABLE_SYNTAX | apache_hive_clientpositive | CREATE TABLE IF NOT EXISTS test_update_partition_textfile_mmctas PARTITIONED BY (id) STORED AS TEXTFILE TBLPROPERTIES('t
- DDL/CREATE_TABLE_SYNTAX | apache_hive_parser_unit | CREATE TABLE PARTITION (col STRING)
- DDL/CREATE_DATABASE_SYNTAX | apache_hive_parser_unit | create view v1_n7 as select c_int, value, c_boolean, dt from "c/b/o_t1"

## 稳定性结论

- 黄金集的稳定性主要看四个维度：结构分布是否稳定、正负样本是否平衡、典型特性是否持续覆盖、历史版本重叠率是否可接受。
- 当前报告将历史重叠率与分布漂移显式输出，避免只用“通过率高”来定义黄金集。
- 后续扩集阶段优先补足 window、cte 等短板，同时保持新增 case 的来源可追溯与类型均衡。
