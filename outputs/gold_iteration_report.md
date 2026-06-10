# 黄金集迭代方案

## 当前策略

- 最终黄金集只保留高可信真值样本。
- 中等可信和低可信样本全部进入待审池，不参与最终打分。
- 通过率只能通过两种诚实方式提升：提升 GT 质量，或提升解析器能力；不能通过删难题、贴合当前 SDK 标签来提升。

## 初始黄金集与最终黄金集

- 初始黄金集更准确地说是“初始黄金候选集”：它由当时可获得的高可信候选池按目标分布、正负平衡、去重和覆盖补洞规则选出。
- 初始黄金集已经具备来源可追溯、结构分布达标和 baseline 对照可用等基础条件，但它还没有经过多轮版本演进来验证哪些 case 是稳定核心。
- 最终黄金集是在初始候选集基础上，继续经历版本快照比对、稳定核心保留、边缘样本替换和待审池升标后收敛得到的版本。
- 因此，二者的差别不只是“最终版多了稳定核心验证”，还包括：最终版对历史漂移更敏感、对覆盖缺口更清楚、对待审样本边界更清楚。

## 当前迭代状态

- 当前最终黄金集规模: 100
- 选样前高可信候选池样本数: 3488
- 去重后高可信候选池样本数: 2457
- 当前待审池规模: 455
- 最近 3 个快照稳定核心数: 100
- 当前非稳定核心样本数: 0
- 当前 actual 低于 2 分样本数: 6
- 当前 actual 1/0 分分布: 1分=3, 0分=3

## 待审池画像

- GT 强度 medium: 260
- GT 强度 weak: 195
- 待审原因 medium_gt_requires_manual_review: 260
- 待审原因 weak_gt_excluded_from_strict_gold: 195
- 待审来源 apache_hive_clientnegative: 170
- 待审来源 apache_hive_negative: 25
- 待审来源 apache_hive_parser_unit: 260

## 稳定核心策略

- DDL/ALTER_TABLE_SYNTAX | apache_hive_clientpositive | ALTER TABLE alter_file_format_test SET FILEFORMAT INPUTFORMAT 'org.apache.hadoop.mapred.TextInputFor
- DDL/ALTER_TABLE_SYNTAX | apache_hive_clientpositive | alter table tst1_n1 partition (ds = '1') into 6 buckets
- DDL/CREATE_DATABASE_SYNTAX | apache_hive_clientpositive | create view v3 as with t as (select * from v1) select * from t
- DDL/CREATE_DATABASE_SYNTAX | apache_hive_parser_unit | create database "db~!@#$%^&*(),<>"
- DDL/CREATE_DATABASE_SYNTAX | apache_hive_parser_unit | create view v1_n7 as select c_int, value, c_boolean, dt from "c/b/o_t1"
- DDL/CREATE_DATABASE_SYNTAX | apache_hive_parser_unit | create view v2_n2 as select c_int, value from "//cbo_t2"
- DDL/CREATE_DATABASE_SYNTAX | apache_hive_parser_unit | create view v3_n0 as select v1_n7.value val from v1_n7 join "c/b/o_t1" on v1_n7.c_boolean = "c/b/o_t
- DDL/CREATE_TABLE_SYNTAX | apache_hive_clientpositive | CREATE TABLE IF NOT EXISTS test_update_partition_parquet_mmctas PARTITIONED BY (id) STORED AS PARQUE
- DDL/CREATE_TABLE_SYNTAX | apache_hive_clientpositive | CREATE TABLE IF NOT EXISTS test_update_partition_textfile_mmctas PARTITIONED BY (id) STORED AS TEXTF
- DDL/CREATE_TABLE_SYNTAX | apache_hive_parser_unit | CREATE TABLE "line/item" (L_ORDERKEY INT, L_PARTKEY INT, L_SUPPKEY INT, L_LINENUMBER INT, L_QUANTITY
- DDL/CREATE_TABLE_SYNTAX | apache_hive_parser_unit | CREATE TABLE HAVING (col STRING)
- DDL/CREATE_TABLE_SYNTAX | apache_hive_parser_unit | CREATE TABLE PARTITION (col STRING)

## 初始黄金集构建原理

- 第一步: 从真实来源抽取候选样本，并为每条样本写入独立 GT 标签。
- 第二步: 在原始多源候选池上统一冻结 baseline，对后续版本保留原始对照。
- 第三步: 过滤到高可信候选池，只保留 gt_status 明确且 GT 强度足够高的样本。
- 第四步: 按 QUERY 50 / DDL 20 / DML 20 / UTILITY 10 做结构选样，并尽量维持正负样本均衡。
- 第五步: 做去重、特性补洞和错误类型补洞，形成第一版可用黄金候选集。
- 第六步: 选样逻辑按固定排序、历史偏好和覆盖补洞规则确定，不使用随机抽样；因此固定输入下会收敛到同一版黄金集。

## 解析器改进 Backlog

- WINDOW: 2
- LATERAL_VIEW: 1
- DROP_DATABASE_SYNTAX: 1
- CREATE_DATABASE_SYNTAX: 1
- USE_DB: 1

## 特性补洞方向

- 当前最终黄金集未覆盖特性: within_group

## 升级规则

- 规则 1: 新样本先入候选池，不直接进最终黄金集。
- 规则 2: 只有 GT 来源足够强，或完成人工审校后，样本才能从待审池提升为高可信真值。
- 规则 3: 样本进入最终黄金集时优先满足当前覆盖缺口；若同一样本同时也是当前解析器容易通过的 case，可以同时满足，但覆盖缺口优先级更高，不能把“容易通过”作为主导入选条件。
- 规则 4: 样本进入最终黄金集后，尽量连续保留多个版本；只有重复、失真或被更强 GT 替代时才移除。
- 规则 5: 每次迭代同时看四个指标：GT 强度、覆盖率、稳定核心比例、真实 0/1/2 分布。
- 规则 6: 当前没有进入最终黄金集的重点特性（例如 within_group）必须保留在待审池并优先审校，不能因未覆盖就直接忽略。

## 停止标准

- 标准 1: 最终黄金集全部为高可信真值样本。
- 标准 2: 结构分布稳定满足 QUERY 50 / DDL 20 / DML 20 / UTILITY 10，且正负样本接近平衡。
- 标准 3: 最近多个版本的稳定核心比例足够高，当前 gold 只发生小规模轮换，而不是大范围抖动。
- 标准 4: 已知重点特性没有被“遗忘”；若仍未入最终黄金集，必须在待审池中有明确补洞计划。
- 标准 5: 新增样本主要来自 GT 升级或覆盖补洞，而不是为了迎合当前解析器结果去改题。

## 不允许的做法

- 不允许因为某类 case 通过率低，就系统性删掉这类 case。
- 不允许只追求高通过率，而牺牲负样本、多样性或来源可追溯性。
- 不允许把还未升到 strong 的样本直接塞进最终 gold，只为了让报告看起来更全面。

## 当前执行流程

- 第一步: 从待审池中按覆盖缺口挑样本做人工审校。
- 第二步: 把审校通过的样本升级成高可信真值，再进入下一版候选池。
- 第三步: 运行版本对比，优先保留稳定核心，少量替换非稳定边缘样本。
- 第四步: 单独跟踪 1 分和 0 分 case，把它们作为解析器优化 backlog，而不是修改 GT 去迁就当前结果。
