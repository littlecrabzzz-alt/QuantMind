# Tushare 三大财务表精确批次候选就绪

- 基线 `3615bebae57d7e5fa9d6ae2a789433b267304d7b`；独立 worktree，只读权威队列，无 Token、无上游、无生产写入或发布。
- 选择 `income_vip`、`balancesheet_vip`、`cashflow_vip`：当前 pending 42,164，其中代码级叶任务 41,981；三项 capability 均为 available。
- 真实队列清单固定同一 120 股票、20260630、report type 1 的三表任务，共 360 请求；manifest 811,554 字节，SHA256 `07a7eb666e9302e8eb4fbce956113f0059621b04e87126bb18d488732ed63390`，任务集合 SHA256 `1ef0e80551582d911d778e6943bd1ad113f32b9b5a3cb284af9d993887b88810`。plan-only 为 0 authority、0 凭据、0 网络。
- 首批预计 48–90 秒、10–30 MB；全部当前叶任务调用下限约 84–93 分钟、1–4 GiB，但 183 个未请求父任务仍可继续扇出，不能作为最终历史 ETA。
- 新准备器只选现有共同 pending 叶任务；新执行器固定清单/任务/配置/工具哈希，复用 exact scope、共享限流、共享锁、100 GiB 门槛与不可变存储，不扩展全局队列、不发布或切换 CURRENT。
- 非阻塞缺口：公告字段不证明首次可知时间；1990 起点是请求范围；迟到修订、完整股票全集及未来父任务扇出仍需后续审计。`index_member_all` known_at、`index_weight` 饱和/全集、`fund_nav` 完整历史留作后续独立批次。
