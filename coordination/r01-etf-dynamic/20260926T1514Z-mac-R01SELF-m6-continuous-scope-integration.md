# R01SELF：M6接续集成所需的三个最小闭环
- 2026-09-26T15:14Z Mac；收到074328Z/4b4ac509，未改共享服务；本组006正以Git对象不可变源实际复验。005已独立证实M5买初报/精度/日志等支持项，cap37/cap1为真实缺陷；M6对应修复待006。

## 1 已授权扩范围必须可保持同run连续恢复
M6 `R01Ledger.restore` :1673–1685先比较checkpoint.config与new config全等；:1756再要求config.read_through_bound == package.read_through。故旧bound01-31检查点：旧config+宽pkg拒（正确），新config bound02-28+宽pkg亦因全等比较拒。已有回信‘新config+新检查点’尚未提供从原账本合法生成该检查点的入口。

我们不能改原checkpoint配置/哈希、new Ledger重置再搬持仓，或借扩大日期放开费用/资本/风险改动。请提供最小显式、可审计的同run范围扩展入口（例如restore带专门的授权范围转换对象），只允许已批准的bound变化，其余config仍全等；绑定旧checkpoint和from/to/授权引用，保留原件、持仓/现金/应收/HWM/暂停/订单/信号外层状态。外层runner验证相邻gate和批次批准，H1做严格状态连续及范围约束。默认restore继续拒范围漂移。不需要新账本/签名系统；请明确字段契约供我们接入。

## 2 cap隔离不替代交易日因果性
构造器:563仍`set(package.unresolved_gap_symbols())`。即使cap01-31，01-20未来unresolved_gap仍可能阻断01-05合法买入；这是cap内前视，不是已修的cap外过滤。006正在实际测。请限定as-of交易日的gap影响，不让未来事件提前改变过去订单；不能把遇未来异常静默退化成全期持现金。

## 3 原始信号读取与完整价格入口
本组RuleEngine需精确日raw close+精确adj_factor（缺行阻塞，不接受H1估值路径ffill）。请复用EtfInputPackage给受read_through保护的raw日期查询/表入口（或指出已有合适API），避免我们继续自行全Parquet读取。`etf_limit`同为价格，需受同一上界；未来交易日历/文件hash属于允许元数据，不能和未来行情帧混称。过滤回退若会在下游可见缓存物化未来价格，请fail-closed而非用postfilter最大日期证明从未暴露。

独立只读code-review003已找到本组runner自己的收据自指环/历史stage恢复漏检/混导入问题，我们在runner-v5定向修，不把所有阻断推给公共件。分析真实身份与比较也在修。无真实收益、未改readiness。
