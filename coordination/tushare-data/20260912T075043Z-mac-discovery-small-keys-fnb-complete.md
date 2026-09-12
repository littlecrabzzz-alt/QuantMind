# Tushare identifier discovery small-key candidate complete

- 时间、节点、任务标识：2026-09-12T07:50:43Z，Mac，`/root/financial_next_batch`
- 状态：待交接
- 分支、worktree、提交：`codex/tushare-discovery-small-keys`，`/private/tmp/quantmind-discovery-small-keys`，`3127facd662d5ca4162615aab4a8e352888181ec`
- 分工：候选仅修改 `backend/shared/tushare_pipeline.py` 和 `scripts/test_tushare_discovery_timing.py`；未集成、部署或接触权威数据。
- 接续：`20260912T074347Z-mac-discovery-small-keys-fnb.md`

普通、非请求敏感的发现证据按 API、对象 SHA、状态和响应格式小键聚合；完整 raw result 的去重计数保持原 `UNION` 语义。请求身份依赖接口继续逐项读取完整 result/observation。对象读取前后核对 inode、大小及时间戳，读取期间缺失或替换均 fail closed。

验证：179 个 `test_tushare_*pipeline.py` 测试、13 个 discovery timing 测试、5 个 discovery projection 测试全部通过；Ruff、`py_compile`、`git diff --check` 通过。固定夹具包含 100000 attempts、1000 jobs、400 行×20列对象；基线两次 0.6992/0.6623 秒，候选 0.3042/0.3159 秒，规范标识符 SHA 均为 `affcef65257554f20b9f71040d624039639c2cf788d88842dfb97829b382cc2c`，发现计数完全一致。临时可复现脚本 `/tmp/benchmark_tushare_identifiers_full.py` SHA256 `633a5e235bffdf6b846b6cf8ebf90f38afe6c97ec61ed62b36287921e5d47204`。

下一步：根任务独立复审提交；真实不可变副本验收仍须比较旧/新 identifier family 与 planning input hashes，并观察 SQL/identifier 阶段耗时。候选没有处理 initialize 的 fund-quarter 重放。
