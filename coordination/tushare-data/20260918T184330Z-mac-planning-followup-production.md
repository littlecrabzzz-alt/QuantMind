# Mac Tushare 规划后续采集生产验收

- 节点与任务：Mac 全量归档唯一写入者，`planning-latency-review-20260919`
- 状态：代码、测试、master、Mac 生产部署和云端角色复核完成；全量回填继续运行
- 代码：`304499de`（`tushare: acquire after planning when cycle budget remains`）
- 配置：Mac 私有 `pipeline-config.json` 启用 `archive_worker_acquire_after_planning=true`；文件保持 `0600`，未记录任何凭据

变更保留原独立 `planning_only` 持久事务。规划成功且当前 105 秒 worker 周期仍有至少 1 秒安全预算时，原生 worker 用剩余预算再次调用同一 `tick` 做真实采集；最多 100 秒，保留 5 秒边界。预算不足、开关关闭或非规划周期都保持原行为。文档回调幂等，同周期只启动一个文档执行器；运行开关不进入规划指纹，不会因切换开关制造额外规划。

自然生产证据：

- 旧逻辑自然规划周期：总计 100.627 秒，结构化请求 0；规划 32.354 秒，`fina_mainbz_vip` 压缩 13.267 秒；文档仍处理 2,180 份。
- 新逻辑部署后的自然规划周期：总计 102.565 秒；前置规划 45.300 秒且 0 上游请求，随后剩余预算真实请求 426 次；文档处理 2,416 份，失败阶段为空。
- 新周期结束计数：done 426,105，empty 361,837，pending 2,831,111，blocked 871，split_pending 10,329，permission_blocked 5,847。`blocked` 与权限状态未被优化改写。
- LaunchAgent 重新安装后持续存活；源代码与运行副本的 pipeline/worker SHA-256 一致；`ENABLED` 内容哈希和 `0600` 权限在切换前后完全一致。

验证：独立 Python 3.10 环境运行全部 `test_tushare*.py`，1,365 项通过、5 项跳过、0 失败，测试日志 SHA-256 为 `7d1470a9cd7760a6e5d82024c0418a35c7f8fcc7e122f794293ef347bc66ed09`；`py_compile`、Ruff 和 `git diff --check` 通过。

云端已快进到同一代码提交，未运行全量归档 worker。`tushare-research-cache.timer` 为 active/enabled；最近验证只覆盖 12 个研究 API，缓存 3,317,837,768 字节，上游请求 0。Mac 继续保存和回填完整数据，云端继续只保存研究子集。
