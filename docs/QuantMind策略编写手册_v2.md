# 策略模板使用与编写

用途：选择现有 Qlib 模板、编写可加载模板并避免无效参数与前视偏差。交互式 `setup/on_bar` 脚本请读 [Strategy Lab 用户手册](Strategy_Lab用户手册.md)，它与本文的模板接口不同。

## 选择与运行现有模板

在 AI-IDE 的策略模板面板选择模板，检查代码、市场、股票池、模型、日期和成本后再回测。模板列表由 `strategy_templates/` 中实际存在的 `.json` 与同名 `.py` 加载；名称或描述不证明策略已有独立实现、数据可用或盈利能力。

- Top-K 类按预测排名选择持仓；`topk` 是持仓目标数，`n_drop` 控制调仓替换。
- 权重类从分数生成目标权重；检查负分处理、归一化、单票上限及实际可交易约束，不能把分数直接当资金比例。
- 动量、价值、风险、止损和时序类模板应逐项核对源码依赖与参数；显示为不同模板不代表使用不同模型。
- 多空模板不等于 A 股账户具备融券能力。T+1、停牌、涨跌停、整手、交易成本与成交时点均需在目标回测/交易引擎中核实。

A 股 `as01_*` 至 `as50_*` 模板由 `scripts/gen_ashare_strategy_templates.py` 维护。改生成模板时应改生成器再生成，避免下次覆盖。历史回测记录不是当前收益承诺，不应为了使用模板自动重跑全量研究。

## 文件合同

`backend/services/engine/qlib_app/services/strategy_templates.py` 只扫描模板目录顶层 `.json`。JSON 包含 `id/name/description/category/difficulty`，可带 `params`、`markets`、`dir`、执行默认值等；`dir` 是界面的虚拟分类，不是递归加载目录。

Python 文件声明：

```python
STRATEGY_CONFIG = {
    "class": "RedisRecordingStrategy",
    "kwargs": {
        "signal": "<PRED>",
        "topk": 30,
        "n_drop": 5,
        "rebalance_days": 5,
        "f_total_mv_min": 3e9,
        "f_pe_ttm_max": 30,
    },
}
```

`<PRED>` 由运行时替换为所选模型的预测结果。模板并不自带可用模型；模型解析见 [推理合同](模型推理服务设计与链路文档.md)。JSON 参数面板默认值应与代码一致。当前 Builder 对用户代码显式声明的参数保持原值，对缺失且类支持的参数回填；不要沿用旧指南“UI 总会覆盖 kwargs”的说法。最终以请求和落盘配置核对生效值。

自定义类可直接定义在模板 `.py` 中；不要为其填写不存在的 `module_path`。内置类映射与动态加载规则见 `strategy_builder.py`。

## 基本面过滤

只有接入 `FundamentalFilterMixin` 的类才解释 `f_*`。约束读取 QuantDB `features_daily` 的日期快照，不读取旧的 `fundamental_aligned.parquet`。

| 参数 | 比较 |
| --- | --- |
| `f_<field>_max` | 小于等于 |
| `f_<field>_min` | 大于等于 |
| `f_<field>_not` | 不等于 |
| `f_<field>_in` | 属于集合 |
| `f_<field>` | 等于 |

必须核对实际列名、单位和历史可得性，不能照搬“88 个字段”或“169 个特征”的固定清单。尤其不要假设 `roe/is_st/listed_days/industry` 在当前数据源中存在。

**当前缺失行为不是 fail-closed：** 整体快照为空会返回原股票池；单个约束列不存在会记录警告并跳过；数值比较会排除无法转为数字的值。因此 `f_*` 不能独立承担实盘强制风控。先查看数据覆盖与日志，不能把没有报错视为筛选生效。

快照可向前查找最多 250 天的候选日期；这不是“最新且及时”的保证。财务数据仍需独立核对公告可得时点。

## 自定义选股钩子

`TopkDropoutStrategy` 在 `generate_trade_decision` 中读信号，不调用权重策略的 `generate_target_weight_position`。基于当前 `RedisRecordingStrategy` 扩展时：

- `_adjust_signal(score, ref_date)` 调整排序/过滤，`ref_date` 为上一交易日。
- `_dynamic_risk_degree(base, ref_date)` 调整风险仓位。
- 行情使用基类 `_close_matrix()` / `_price_frame()` 的缓存路径，避免每个调仓步反复拉全量行情。

权重类走另一条调用链，不能将上述钩子机械套用。`_adjust_signal` 异常时当前实现记录日志并沿用原信号，必须检查日志，不能认为异常会自动阻断交易。

## 使用前检查

- 训练特征、标签和策略筛选分开：`return_Nd` 等未来收益标签不能用作当时选股输入。
- 明确信号可得时刻与成交时刻；收盘后得到的信号不能按同日已知收盘价成交。
- 核对每项约束实际改变了候选池，并保存模型、日期、股票池、参数、成本和数据版本。
- 样本外比较和交易能力验证独立进行。模板、回测、扫描通过均不自动授权实盘。

费用口径见 [回测费用](回测费用配置说明.md)。本项目仅供研究，不构成投资建议。
