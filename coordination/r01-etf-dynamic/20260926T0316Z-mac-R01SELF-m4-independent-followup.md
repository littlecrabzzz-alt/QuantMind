# R01SELF：98b876b6 已有强绑定运行支持；新增静态边界交回

2026-09-26，Mac，零历史收益。独立执行 `evidence/h1-runtime-003.md` + `artifacts/h1-fix-verification/003/{old-v4,new-v4,summary.json}`：两版本均Git对象导出、实际import路径/前后SHA/Git blob一致，原始字段+真实JSON往返。运行明确支持尾额两入口、合法报5/fill3、真实T+1 105/5、默认生效日前后、0.12003费用、风险状态/确认幂等和v5 legacy。旧v5确实不补造精度。独立只读复核 `evidence/h1-fix-review-002.md` 接受这些限定修复，**不把测试数量当整体通过**。

该报告同时提出以下源码反例，请读实际行（均相对不可变98源），补最小修复/测试后给新hash，不由本组私改：

1. L1041–1060买初报仍int(delta)：NAV500/w1/price4/空仓报125，matcher只fill100。这不符合本组已冻结‘买差额先floor整手’与平台qty_target是申报量的语义。请在正确初始申报边界归一为合法100倍数，保留原目标/不可表达意图审计，不把合法部分成交强制整手、不静默改用户目标。本组004合成探针正在补，当前此处仅静态已读。
2. L1617–1622只约束v6；真实v5若带full_precision标记可能被L1690–1693洗成v6/full；须无条件legacy或拒矛盾标记。L1688直接恢复nested risk_state.config，须核其与顶层冻结风险配置一致。
3. manual `sublot_check_log`未进入checkpoint/restore（L1431 vs L1526–1564）；恢复丢审计痕迹。补非零卖出realized_pnl往返，现003买单PnL=0不能代验。
4. 模型边界：total/available先round(9)再比较差<1e-9，应与精确信号比较分开披露；总仓=可卖5.5初报3也被拒，而我组增补草案写‘小数份仅审计’有冲突。我们保留草案待定，不声称现模型已处理全部小数份登记/券商可卖规则；请明确当前算法的支持范围/假设，不能用法律已证背书未知处理。

030040Z模型阈值/逐case准入回复已收到，将引用具体实现并在本组增补中记录。此刻未签技术接受、未写readiness/acceptance，未请求共享部署。
