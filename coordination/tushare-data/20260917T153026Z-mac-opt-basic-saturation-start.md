# Tushare opt_basic 饱和目录恢复开始
- 时间、节点、任务标识：2026-09-17，Mac，opt-basic-saturation
- 状态：进行中
- 分支、worktree：codex/tushare-opt-basic-saturation，/tmp/quantmind-opt-basic-saturation
- 分工：仅修改 backend/shared/tushare_pipeline.py、backend/shared/tushare_other_contracts.py 和对应离线测试；保留主工作树已有 RRG/研究修改。
- 接续：4e295815 后的本地全量 Tushare 补采。

只读生产审计确认 50 个旧 opt_basic 饱和父任务保留原始响应，观测交易所含当前配置遗漏的 INE；call_put 仅 C/P，opt_code 均通过供应商文本校验。候选实现按 exchange、call_put、opt_code 依次拆分，旧父任务只复用本地响应，不重发父请求。
验证：尚未执行；生产采集继续运行，未停止 QuantDB 或云端缓存。
下一步：隔离实现、离线回归，再等待本地采集自然周期边界发布。
