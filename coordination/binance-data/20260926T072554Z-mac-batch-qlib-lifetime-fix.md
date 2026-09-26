# 批量验收发现并修复 Qlib 上市边界
- 状态：候选修复中；Mac isolated worktree `codex/binance-data-20260926`。
- 新发现：10币所有H5/Qlib数值、偏移和来源绑定通过，但 `instruments/all.txt` 将8个后上市币种起点错误写成全局首日2017-08-17。独立失败证据保留 `output/binance-batch-20260926/derived-value-audit.json`。
- 范围增加：仅 `backend/services/engine/qlib_data_builder.py` 的CRYPTO标的起止范围及 `backend/tests/data_platform/test_crypto_research_release.py` 相关回归测试，由本任务负责。其他市场逻辑不改。
- 已停止本任务临时验收容器（非共享服务），避免完成未验收的研究输入拷贝。只重建新batch派生；旧BTC/ETH池、旧研究及其他任务输入保留。
- 云端新数据仍在独立暂存目录，4010传输文件校验通过，旧正式CURRENT未改。修复验收后做独立数据根发布和CLI消费，不启用策略、交易或新调度；无共享API/worker重启。
