# Tushare fund_nav 空响应第一轮 runner 候选

- 时间、节点、任务：2026-09-10T18:12:08Z，Mac，`fund_nav_empty_runner`。
- 分支/worktree/基线：`codex/tushare-fund-nav-empty-runner`；`/Users/lizeyu/.codex/worktrees/quantmind-fund-nav-empty-runner`；`98763f47e67e640e572d7ef990aa404bffa30faf`。
- 文件范围：新增 `scripts/run_tushare_fund_nav_empty_review.py`、`scripts/test_tushare_fund_nav_empty_review_runner.py` 及本记录；未改 prepare、pipeline/schema、配置、进度文档或数据。

runner 默认只离线校验 plan。执行要求显式固定 manifest、任务集合、authority SQLite、固定 release manifest、配置及组合代码哈希；宿主机操作人必须先停止 `quantmind-celery-beat` 与 `quantmind-tushare-worker`，runner 不在容器内伪装验证这项操作前提，也不依赖 Docker CLI/socket。runner 用非阻塞共享 `pipeline.lock` 原子阻止其他 writer，再检查 schema 6、100 GiB 余量、成对请求数/90 秒/现有限速容量后才读取 Token。每个目标严格按 A 原请求、B 固定版单日正向控制调用，复用不可变 object/observation、标准化和分区核对。空复核只追加一条含 A/B 的 attempt，不把原任务改回 `pending`；合法非空 A 才更新原任务。首轮结果区分 `round1_valid_empty`、`review_inconclusive`、`review_conflict`、`manual_hold`，失败重冻结按 1 小时、24 小时门控且同 manifest 可无网络恢复收据。没有 round 2、`review_exhausted`、发布或 `CURRENT` 切换实现。

验证：`python3 -m unittest scripts.test_tushare_fund_nav_empty_review_runner scripts.test_tushare_fund_nav_empty_review` 共 10 项通过；`uvx ruff check`、`python3 -m py_compile`、`git diff --check` 通过。测试 HTTP 全部使用 `httpx.MockTransport`，未读取凭据或访问生产。runner SHA256 `1d9ef090ff4e4a5c3b3a9c879f1363543a39dae1df592545a4a2c44fefc2c721`；测试 SHA256 `c5f688c79c3df032de2f364e519e1ad63643b9c6ec838e13d674f218748026a8`。

残余边界：本候选只建立第一轮执行与重冻结失败语义；第二轮、七天门控、三次独立空观察后的 `review_exhausted`、发布/镜像验收仍需后续独立实现和授权。候选没有执行任何生产请求。
