# Tushare：退役 hs_const 历史接口纳入本地正式归档

- 时间、节点、任务标识：2026-09-17T21:02:20Z，Mac，hs-const-production
- 状态：Mac 生产完成，待双端 Git/内容交接复核
- 分支、worktree、提交：`codex/tushare-hs-const`，`/tmp/quantmind-hs-const`，`1fde26ce69cd1323d565a506b28bb74f4253ab8e`
- 分工：本次只修改 legacy Connect 合同、覆盖台账、对应文档和测试；未接触主工作树中其他 RRG/研究修改。
- 接续：`20260917T203530Z-mac-quality-reassessment-production.md`

本次完成：失效的官方 doc104 页面仍指向可用的只读 wire API `hs_const`。实测表明它保存 2014–2019 年旧版沪深股通成分历史，不是当前名单。合同明确请求 `ts_code,hs_type,in_date,out_date,is_new`，只规划四个稳定 `history` 任务（SH/SZ × is_new 0/1），不伪造逐日请求；与 2025-08-12 起的 `stock_hsgt` 并存，2014 前、2020–2025、修订和 PIT 缺口保持显式。缺少当前官方频次时，分层策略按 unspecified leaf 在 10100 积分下解析为 300 次/分钟并保留 `review_required`，本任务实际仅请求四次。

生产验收：四个任务均为 `done/sample_ok` 且 `supplier_has_more=false`，行数分别为 SH:0=414、SH:1=581、SZ:0=574、SZ:1=242；每个原始对象、观测文件和分区 Parquet 的内容哈希均复核通过。正式固定版本为 `data-6466fd66bd816f503e0887b226a05be8fbe1095a585ba1d5404fa2b52723ac21`，manifest 为 479630987 bytes，文件 SHA256 与 release_id 一致。通过正式 reader 查询得到 1811 行，四组计数一致，`in_date` 为 20141117–20191227，`out_date` 空值 823 行；schema keys 为 `ts_code,hs_type,in_date,out_date,is_new`，并保留 `history_bound_verified=false`、history gap 和 PIT gap。

验证：43 个 Connect/catalog/rate 测试通过；另有 pipeline + legacy 21 个测试通过；`git diff --check`、py_compile 和范围审计通过。范围审计现为 250 个命名只读范围、247 个 runtime_readable，仍只有 `ggt_monthly`、`p_save`、`p_delete`、`pro_bar` 四个有明确分类而未注册的项。运行副本合同文件与源码 SHA256 同为 `d95ed1975bc4503251d01c6dea77d89476da71a023a42f77b68cd6e974ac662e`。发布后 worker PID 6481 的首个完整周期发出 365 个真实请求，失败阶段为空，stderr 为 0；本地配置 SHA256 为 `2fa4b507d26feeac3c60a4bb0996911f2484a7ec976e4fef0410d619e3bf0b46`，未记录 Token 或订单信息。

下一步：提交本记录，推送 master，等待 Syncthing 后执行双端 handoff；云端继续只运行研究缓存，不恢复完整 Tushare 写入者。本地全量历史队列继续后台采集。
