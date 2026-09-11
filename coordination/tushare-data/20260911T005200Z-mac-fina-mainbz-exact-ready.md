# Tushare fina_mainbz exact batch ready

- 时间、节点、任务标识：2026-09-11 00:52 UTC，Mac，`fina_mainbz_exact_runner`
- 状态：完成，待集成人部署与生产执行
- 分支、worktree、提交：master；本记录所在独立提交
- 分工：仅新增 `fina_mainbz` prepare、runner、聚焦测试及本记录；未修改共享进度文档、注册表和其他并行文件
- 接续：固定 release `data-512b55ad...` 发布后的历史缺口批次准备

完成：新增生产 exact prepare/runner。prepare 在共享锁内固定 CURRENT、release manifest、配置、完整 eligible 任务库存和选中任务哈希，只选择 `history/pending/tries=0/attempts=0` 的固定报告期窗口；按 P/D/I 与 SH/SZ/BJ 轮转。runner 执行前重验库存、任务、配置、release 与代码哈希，并保留 authority、schema 6、ENABLED、100 GiB、账户/API 500 rpm、360 请求和 90 秒门控。执行不发布，也不切换 CURRENT。

验证：`python3 -m unittest scripts.test_tushare_fina_mainbz_batch scripts.test_tushare_research_extra_contracts` 为 14/14；`python3 scripts/test_tushare_rate_policy.py` 为 21/21；`compileall`、88 字符扫描和 `git diff --check` 通过。本机无 ruff 命令。未访问凭据、上游或生产 authority，未部署、未运行生产采集。

边界：报告期窗口、请求类型和供应商公司代码已固定并保留；Tushare 输出无公告时间，`known_at`、PIT、完整历史和空响应代表缺失均未验证。后续必须在云端安全排空采集 worker 后，用新固定 manifest 的全部显式哈希执行并生成验收证据。
