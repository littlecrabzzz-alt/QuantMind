# GLM-5.3：S03 运行结果独立复核

- agent：`qr-glm-0b55` / `w1:p4`
- 实际模型：`zai-coding-cn/glm-5.3`
- 本地复核归档：`/Users/lizeyu/.local/share/quantmind/strategy-lab/wave-001-20260911T160311Z/reviews/qr-glm-0b55-s03-output-recheck-008.md`
- 结果：`conditional_pass`

## 已证

- 6 场景、18 control、54 非空 CSV，覆盖 57 个测试日。
- DeepSeek 对 18 组完整机械复算，收益、回撤、成本、turnover、exposure、cash idle、持仓和交易成本与 summary 一致，差异 0。
- GLM 抽验 10 万/50%/model：末账户 `100552.0483`、成本 `441.7766`、turnover_sum `1.67352`、最大 exposure 约 `26.0%`，与 CSV 和 summary 一致。
- 首个非零成交日均为 `2025-04-14`；model/single_factor 只有 12 个有效成交日；实际暴露低于目标，根因未定。
- 容器隔离、退出码、hash、paper/live 边界均符合记录。

## 待查 / 阻塞

- k=0 全部 `not_applicable`，未观察到真实清仓。
- 首日未成交、18 登记日与 12 有效成交日、持仓低于目标的原因未解决，不得归因整手/涨跌停/限价。
- trade_unit 未证实；独立非同路径 replay 未实现。
- 手工命令缺 research node label/launch-lock，已记录为编排缺口。
- GLM 未逐笔重算全部 18 组，完整机械复算依据 DeepSeek `s03-output-recheck-008.json`。

不能选 winner，不继承 optimize 门槛；虚拟盘/实盘均未启动。
