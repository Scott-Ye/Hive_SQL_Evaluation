# 3 个 0 分样本补充说明

## 结论摘要

- 当前 3 个 0 分样本全部来自最终黄金集中的高可信正样本。
- 这 3 条样本的共同特征是：GT 明确为 `pass`，但 baseline 与 actual 都返回 `fail`，因此 `baseline_score=0` 且 `actual_score=0`。
- 它们不是版本轮换边缘引入的问题样本，而是当前 Hive Parse SDK 仍未覆盖的真实能力缺口。
- 它们都满足“关键特性覆盖必须保留”，但不满足“当前解析器容易通过”，因此属于覆盖优先保留的能力缺口样本。

## 样本 1：HIVE_REAL_016

- 一级/二级类别：`QUERY / WINDOW`
- GT：`pass`
- baseline：`fail / cannot_recognize_input / window_clause_syntax`
- actual：`fail / cannot_recognize_input / window_clause_syntax`
- 报错位置：`1:105`
- 来源：Hive 官方文档 `LanguageManual WindowingAndAnalytics`
- SQL 片段：

```sql
SELECT a, SUM(b) OVER (
  PARTITION BY c ORDER BY d
  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
) FROM T;
```

- 说明：该样本是官方文档中的标准窗口函数示例，GT 为高可信 pass。
- 当前本地 SDK 在 `FROM T;` 结尾附近报 `window_clause_syntax`，说明窗口子句解析仍存在缺口。
- 该样本被保留，是因为 `WINDOW` 属于黄金集必须覆盖的核心特性，不会因为当前解析器暂时过不了就移出黄金集。

## 样本 2：HIVE_REAL_038

- 一级/二级类别：`QUERY / WINDOW`
- GT：`pass`
- baseline：`fail / cannot_recognize_input / window_clause_syntax`
- actual：`fail / cannot_recognize_input / window_clause_syntax`
- 报错位置：`1:105`
- 来源：Hive 官方文档 `LanguageManual WindowingAndAnalytics`
- SQL 片段：

```sql
SELECT a, AVG(b) OVER (
  PARTITION BY c ORDER BY d
  ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING
) FROM T;
```

- 说明：该样本与 HIVE_REAL_016 同属窗口语法正样本，但覆盖的是另一类窗口边界写法。
- 当前本地 SDK 同样在结尾附近报 `window_clause_syntax`，说明这不是偶发噪声，而是窗口解析能力还未完整覆盖。
- 该样本被保留，是因为它既有官方文档强证据，又补足了窗口语法的边界覆盖。

## 样本 3：HIVE_REAL_040

- 一级/二级类别：`QUERY / LATERAL_VIEW`
- GT：`pass`
- baseline：`fail / cannot_recognize_input / generic_parse_failure`
- actual：`fail / cannot_recognize_input / generic_parse_failure`
- 报错位置：`1:96`
- 来源：Hive 官方文档 `LanguageManual LateralView`
- SQL 片段：

```sql
SELECT adid, count(1)
FROM pageAds
LATERAL VIEW explode(adid_list) adTable AS adid
GROUP BY adid;
```

- 说明：该样本是官方文档中的标准 `LATERAL VIEW explode` 示例，GT 为高可信 pass。
- 当前本地 SDK 在 `adid` 与结尾分号附近报 `generic_parse_failure`，说明 `LATERAL VIEW` 相关解析仍有缺口。
- 该样本被保留，是因为 `LATERAL_VIEW` 是当前黄金集必须保留的关键特性覆盖点。

## 为什么没有因为 0 分而移除

- 黄金集的首要目标是保留真实来源高可信真值与关键覆盖，不是筛出“当前解析器最容易通过”的样本。
- 这 3 条样本都来自官方文档，来源强、真值强、特性关键，删除它们会把真实能力缺口从评测集中抹掉。
- 因此，当前版本的做法是保留这 3 条样本，把它们作为明确的残余能力缺口，而不是通过替换样本来抬高通过率。

## 与升级规则第 3 条的关系

- 升级规则第 3 条的真实含义是：样本进入黄金集时，优先满足覆盖缺口；若同一样本同时也是当前解析器容易通过的 case，可以同时满足。
- 当“覆盖缺口”和“容易通过”不能同时满足时，覆盖缺口优先。
- 这 3 条 0 分样本就是这条规则的直接体现：它们满足关键覆盖，但不满足当前解析器容易通过，因此仍然保留在最终黄金集里。
