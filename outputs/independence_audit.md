# 黄金集样本约束说明

## 当前结果

- 最终黄金集样本数: 100
- 选样前高可信候选池样本数: 3488
- 去重后高可信候选池样本数: 2457
- 最终黄金集非高可信真值样本数: 0
- 当前约束结论: 最终黄金集只保留高可信真值样本。

## GT 来源分布

- official_doc_example: 3
- open_benchmark_clientpositive_directory: 46
- open_benchmark_positive_directory: 2
- parser_unit_explicit_negative: 2
- parser_unit_file_heuristic:TestSpecialCharacterInTableNamesQuotes.java: 47

## GT 强度分布

- strong: 100

## 当前约束

- 约束 1: 最终 real-source 黄金集只保留高可信真值样本。
- 约束 2: baseline 在原始多源候选池首次冻结时写入，后续评测只生成 actual。
- 约束 3: 选样逻辑按固定排序、目标分布和覆盖补洞规则执行，不使用随机抽样。
