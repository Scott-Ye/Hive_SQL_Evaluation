from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Dict, List

from src.core.project_config import EVALUATION_STANDARD_MD
from src.reporting.evaluator import _safe_rate


def build_evaluation_standard_report(
    rows: List[Dict[str, str]],
    *,
    output_path: Path = EVALUATION_STANDARD_MD,
) -> str:
    total = len(rows)
    gt_pass_total = sum(1 for row in rows if row["gt_status"] == "pass")
    gt_fail_total = sum(1 for row in rows if row["gt_status"] == "fail")
    parser_pass_total = sum(1 for row in rows if row["actual_status"] == "pass")
    parser_fail_total = total - parser_pass_total
    positive_pass_total = sum(
        1 for row in rows if row["gt_status"] == "pass" and row["actual_status"] == "pass"
    )
    negative_hit_total = sum(
        1 for row in rows if row["gt_status"] == "fail" and row["actual_status"] == "fail"
    )
    actual_score_counter = Counter(int(row["actual_score"]) for row in rows)
    gt_exact_total = actual_score_counter[2]
    gt_usable_total = actual_score_counter[2] + actual_score_counter[1]

    lines = [
        "# Hive Parse 评判标准与原理说明",
        "",
        "## Hive Parse 在本项目中的验证原理",
        "",
        "- 本项目调用的是 Apache Hive 的 ParseDriver。",
        "- ParseDriver 的职责是做词法分析与语法分析：把一条 SQL 按 Hive 语法规则解析为语法树，或者在语法不合法时抛出解析错误。",
        "- 因为当前数据集中的每个 case 都是单条 SQL，没有真实表结构、字段血缘、权限和运行环境上下文，所以本项目只能严肃评测“语法解析能力”，不能严肃评测“执行语义正确性”。",
        "- 因此，本项目中的 GT 不是语义执行结果 GT，而是“这条 SQL 在 Hive 语法层面应当 pass 还是 fail，以及失败时的错误粒度标签”。",
        "",
        "## 参考评分图在本项目中的适配",
        "",
        "- 参考的 2/1/0 评分图是通用参考，不是要求逐字逐句照搬到纯语法 Parse 任务。",
        "- 对于本项目这种单条 SQL、无上下文的 Parse 任务，'语义等价于 GT' 需要收缩解释为 '语法判断与错误定位等价于 GT'。",
        "- 因此本项目采用如下适配：",
        "- 2 分：GT 与实际完全一致。正样本要求成功解析；负样本要求状态一致，且错误类型/子类型在 GT 已提供的粒度上完全一致。",
        "- 1 分：部分正确。状态一致，但负样本细节只达到错误家族一致或错误子类型部分命中。",
        "- 0 分：完全错误。状态判断错误，或 GT 已给出的关键细节完全未命中。",
        "- 为了同时保留评测一致性和 SDK 原始诊断信息，项目在 baseline / actual 中同时保留对齐字段与 raw 字段：对齐字段参与评分，raw 字段用于排查解析器原始报错。",
        "",
        "## 必须区分的两类指标",
        "",
        "- 第一类是“黄金集质量指标”，衡量数据集是不是一个合格的黄金集。",
        "- 第二类是“解析器表现指标”，衡量当前 Hive Parse SDK 在这套黄金集上表现如何。",
        "- 这两类指标不能混为一谈，否则就会把“通过率高”误当成“黄金集质量高”。",
        "",
        "## 难度分组原理",
        "",
        "- 本项目的难度不是由模型打分得到，而是由样本构建阶段按语法结构复杂度做启发式分组。",
        "- easy: 基础语法骨架较短、嵌套和组合特性少，例如 USE、SELECT_BASIC、LIMIT、简单 CREATE / DROP。",
        "- medium: 需要组合常见语法块，但通常仍是单层结构，例如 JOIN、GROUP BY、HAVING、INSERT INTO、普通函数与部分 ALTER。",
        "- hard: 通常包含嵌套、窗口、CTE、TRANSFORM、INSERT FROM、UNION、LATERAL VIEW 等复杂结构。",
        "- 当前项目主路径只保留真实来源黄金集，difficulty 主要由 [official_doc_pipeline.py](file:///C:/Users/INT/Desktop/工程训练营-构建大数据开发套件智能体评估体系/src/pipelines/official_doc_pipeline.py#L172-L245) 按 SQL 结构复杂度做启发式推断。",
        "",
        "## 难度分层为什么只适合作为辅助诊断",
        "",
        "- 难度分层不会改变 GT 本身，它只是把样本按语法结构复杂度做一个切片，帮助开发者观察错误是否集中在复杂语法。",
        "- 当前项目里只剩少量负样本会拿到 1 分：状态判断正确，但数据库标识符类 case 的 GT 子类型与 SDK 对齐子类型仍存在少量差异；这会让“按难度统计的 2 分比例”略低于最终命中率。",
        "- 因此，难度分层更适合做研发诊断，不适合放在主评测报告里当核心指标；主报告应优先展示分类分布、特性覆盖、0/1/2 分布、一级分类严格一致率。",
        "- 当前项目已经将难度分层从主报告中移除，仅在方法说明中保留这一解释。",
        "",
        "## 解析器表现指标",
        "",
        f"- 解析通过率: {_safe_rate(parser_pass_total, total)} = {parser_pass_total}/{total}",
        f"- 解析失败率: {_safe_rate(parser_fail_total, total)} = {parser_fail_total}/{total}",
        f"- 正样本通过率: {_safe_rate(positive_pass_total, gt_pass_total)} = {positive_pass_total}/{gt_pass_total}",
        f"- 负样本命中率: {_safe_rate(negative_hit_total, gt_fail_total)} = {negative_hit_total}/{gt_fail_total}",
        f"- GT 严格一致率: {_safe_rate(gt_exact_total, total)} = {gt_exact_total}/{total}",
        f"- GT 可用匹配率(1分及以上): {_safe_rate(gt_usable_total, total)} = {gt_usable_total}/{total}",
        "",
        "## 黄金集质量指标",
        "",
        "- GT 可信度：最终黄金集应优先由高可信真值样本构成。",
        "- 结构平衡性：正负样本数量尽量均衡，且遵循 QUERY 50 / DDL 20 / DML 20 / UTILITY 10。",
        "- 覆盖广度：要覆盖典型语法类型与关键特性，而不是只保留容易通过的 case。",
        "- 历史稳定性：连续多版保留稳定核心 case，避免每次换一批题。",
        "",
        "## 为什么 GT 严格一致率不等于解析通过率",
        "",
        "- 解析通过率只统计实际返回 pass 的比例。",
        "- GT 严格一致率统计的是“实际结果是否与 GT 完全一致”，它同时考察正样本 pass 和负样本 fail。",
        "- 如果一套黄金集里负样本很多，那么解析通过率天然不会很高；这不代表解析器一定差，而是说明黄金集里本来就包含大量应当失败的样本。",
        "- 因此，在正负样本平衡的数据集中，不能用“解析通过率高”直接定义黄金集质量。",
        "",
        "## 正确的项目口径",
        "",
        "- 黄金集构建目标：高可信、覆盖广、结构平衡、历史稳定。",
        "- 解析器优化目标：提高正样本通过率、提高负样本命中率、提高 GT 严格一致率。",
        "- 如果要追求“通过率高”，正确做法是优化解析器，而不是把黄金集改成更容易通过。",
        "",
        "## 当前项目口径落地",
        "",
        "- 当前说明采用“参考评分图 + 纯语法 Parse 任务适配”的口径，明确展示本项目对通用 2/1/0 评分图的收缩解释。",
        "- 解析文档同时展示解析通过率、正样本通过率、负样本命中率、GT 严格一致率、GT 可用匹配率。",
        "- baseline / actual 的错误字段同时保留对齐口径与 raw 口径，便于老师审阅时区分“评分用字段”和“SDK 原始报错字段”。",
        "- 难度分层保留在方法说明中作为辅助诊断视角，不作为主报告核心评估项。",
        "- 黄金集文档同时展示 GT 强度分布、覆盖率、结构分布、稳定核心与待审池。",
        "",
        "## 为什么同时保留 baseline 与 actual",
        "",
        "- `actual` 单独存在时，已经足够完成“本次运行结果 vs GT”的评分。",
        "- `baseline` 在当前项目中被定义为“原始多源候选池首次冻结时的 SDK 对照结果”，不是同一次评测里临时补写的副本。",
        "- 后续无论黄金集如何重新选样、评测如何重复执行，`actual` 都是在和更早冻结下来的 `baseline` 对照；只有新增样本才会在进入候选池时首次生成 baseline。",
        "- 因此，`baseline + actual` 的组合服务于跨版本回归、版本维护和变化定位；如果只保留 `actual`，当前评分仍成立，但会失去历史对照能力。",
        "",
    ]
    report = "\n".join(lines)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report + "\n", encoding="utf-8")
    return report + "\n"
