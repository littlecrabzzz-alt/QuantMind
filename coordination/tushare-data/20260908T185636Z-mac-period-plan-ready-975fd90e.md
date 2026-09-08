# 周月线请求优化及HK退市标识修复
- Mac / text_contracts，独立codex/tushare-text，delta a08f4ee5213d5246fa86f83df89a44bb85586ae5；只global_contracts及原global tests，已释放。接续185214 period-plan-start。
- 官方144/145/171/172复核：stock表ts_code/trade_date二选一，因此四类用code+start/end；index历史按code×年，stock历史按code完整显式范围，recent每code7日；全部API流交错，所有自然日期覆盖，不猜交易周五/月末。缺发现保留gap而不退回低效全市场日查询，不筛交易所/退市；未知历史边界仍保留。
- HK五位可选!退市标识保留distinct，00013!.HK不合并00013.HK，避免global验证异常阻断其他family。父负责pipeline前缀归一化。
- monthly guard5629，达到仍报警；row_cap_verified=False、官方4500/真实返回下界5629差异保留。真实性来自父validation/global-vip-probe.json，本子任务未接生产API。
- 19测试通过（global contracts12+global pipeline7），Ruff/diff check通过。无生产写/部署/配置改动。
- 父旧队列策略：持pipeline.lock仅将四类params含trade_date且pending的旧形状请求可逆defer并记录原因，包括旧fanout子；不删任务/成果/attempt，不关闭未证实父。新range形状另规划。enable_global=False只禁规划，next_job无group fallback仍可能消费旧global pending，不能当完全暂停。
- 后续性能风险：identifiers改变会重置anchor，stock整段历史end_date前进可能重新生成大范围请求；可进一步改为截至上年末稳定长窗+本年短窗，避免新增IPO使旧全历史重复。未在本轮自动扩范围。
