# 策略研究室

这里是主控和所有研究agent的统一主题目录。目标：研究几套可解释、可复查的策略，经过历史测试后接入虚拟盘持续观察，未来再按实盘准入条件评估。

用户已同意第一波测试，并要求比较策略风格与不同资金规模。第一波具体范围见 [试验方案](waves/wave-001.md) 和 [冻结合同](waves/wave-001-contract.json)。实盘始终关闭；本轮还不是持续虚拟盘运行。

| 编号 | 研究主题 | 第一波安排 | 主题说明 |
|---|---|---|---|
| S01 | ETF趋势轮动 | 数据与执行准入，满足条件才回测 | [S01](topics/S01-etf-trend.md) |
| S02 | 八因子模型选股 | 同模型、同信号下完成风格×资金测试 | [S02](topics/S02-eight-factor-model.md) |
| S03 | A股低波动＋趋势 | 记录方案与依赖，后续独立实现/测试 | [S03](topics/S03-low-volatility-trend.md) |

| 负责人 | 工作 | 独立主题记录 |
|---|---|---|
| Astra主控 | 冻结范围、审阅证据、协调计算、汇总和阶段裁决 | [主控](agents/controller.md) |
| DeepSeek Flash | ETF数据与已有执行器准入调查 | [ETF调查](agents/deepseek-etf.md) |
| GLM-5.3 | 风格/资金对比方法审查 | [方法审查](agents/glm-method.md) |
| GLM-5.3-Flash | 虚拟盘与未来实盘接入核查 | [执行接入](agents/glm-flash-execution.md) |

协作记录追加到 `records/`；每个agent只负责自己的主题文件，不共同覆盖一张CURRENT表。实验方案修改开新wave，保留旧合同和失败结果。

本机大产物放在同步范围外，入口见 [本地产物](ARTIFACTS.md)。本目录保存主题、职责、计划、证据摘要与报告链接；数据库/模型/成交明细不通过源码同步回灌云端。
