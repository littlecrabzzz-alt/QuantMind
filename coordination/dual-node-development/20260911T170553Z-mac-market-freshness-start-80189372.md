# 页面数据新鲜度补查

- 用户实际market-analysis页面仍2026-09-04，真实QuantDB已20260911；快照读取层优先data/market-analysis旧衍生结果。
- 本任务在/private/tmp/quantmind-market-freshness（codex/market-freshness）修复市场分析结果的更新入口，并检查其他A股页面引用的行情/缓存。保留固定研究输入和用户业务结果，不重跑研究。
- 云端Beat/Tushare正在另一任务精确补数维护中，不操作云端运行服务和authority数据。代码候选通过后协调同一集成人。
- 验收须覆盖用户Chrome实际页面，不能以QuantDB日期或脚本exit0替代。
