# 接口覆盖审计更新

Mac 只读核验，补采 PID 25110 正常运行。替代 20260918T073335Z 记录中的旧范围数字：270 个基线页面、25 个发现页面、258 个命名义务、254 个注册接口，registered_without_reader=[]。未注册仍为 ggt_monthly、p_save、p_delete、pro_bar，不能把注册数量当成历史完成率。

较旧范围新增 etf_auction、fut_inv_weekly、fut_rcpt_mat、fut_trade_param、rt_hk_k、stk_seasoned、vix_index。生产配置已启用后六项，逐接口索引读取证实均有真实请求结果；部分早期历史结果为 empty_unverified，不推断完整。etf_auction 的真实权限拒绝见 docs/tushare-catalog-delta-production-20260919.json，因此维持关闭。没有发现额外可执行的注册遗漏。

审计产物 /Users/lizeyu/Library/Application Support/QuantMind/tushare/validation/scope-audit-20260919.json
SHA256 21288505da98848a3c15c906c774f14e3b87033d8609981be8fb1628f0ccea54

另更正旧审计 share_float 无更细轴的结论：float_date 合法，已真实补采三个观察日期并新增保存 2868 条不同记录，见 20260919T024000Z-mac-share-float-observed-recovery.md；一个精确日期仍饱和，日期全集未证明。

最新 worker 时间 2026-09-19T02:48:20.520076+00:00，status=completed_cycle；全量目标未完成，继续实际补采，不重跑已通过的全套测试。
