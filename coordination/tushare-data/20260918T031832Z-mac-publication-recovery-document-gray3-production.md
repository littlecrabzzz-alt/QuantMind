# Mac Tushare 固定版发布恢复与附件三路灰度生产结果

- 时间、节点、任务：2026-09-18T03:18:32Z，Mac 全量归档所有者，publication-recovery-document-gray3。
- 代码：`7aba47a9b2057db6fbbe6c2250a95d4d290e897f` 将附件下载合法并发扩至 3；`12d16c42d7dbf66833fcc0470811d98600f49607` 修复 capability 探针退休回执的固定版发布覆盖。两项均已合入并推送 `master`。
- 验证：附件/worker 专项 44 项通过；固定版回执与时序专项 16 项通过；使用归档运行时依赖的完整 pipeline 23 项通过；Ruff 与 `git diff --check` 通过。生产 12 条 capability 退休覆盖逐项满足严格条件，两个生产 SQLite 的 `PRAGMA quick_check` 均为 `ok`。

到期六小时发布先在旧运行代码中两次安全失败：约 197 秒完成 attempt/artifact 扫描后，`contract_reassessment_overlays` 不认识新增的 `capability_probe_retirement` 标记并抛出 `ValueError`。两次均未切换 `CURRENT`，没有上游调用，也没有改写源尝试或 artifact。修复只接受版本 1、`quality` 前态、状态未提升、`coverage_proven=false`、源尝试与 artifact 保留、当前 capability 可用且已有正式生产尝试的退休覆盖；普通 reassessment 规则保持不变。部署后发布成功，`CURRENT` 原子切到 `data-afcd3fbe300c1e2082c1a172c37d6a8f9c9343b14a2b938302a39da7f1e51e23`，下一次发布按 21600 秒周期执行。

Mac 私有配置只把 `document_download_workers` 从 2 调到 3，配置 SHA-256 为 `892614d682f4b3ad4e12b85f2c01c600b5555b9a621ffbb8655b7b219782dffa`；仍为单 Tushare HTTP worker、800 请求批次上限、100 秒 acquisition、105 秒周期、500 次/分钟账户/灰度上限，附件批次 240 阶段/90 秒。安装副本的 pipeline、documents 与 archive worker 文件 SHA-256 均与仓库一致。

真实生产验收：

- 发布周期后的首批附件为 120 下载 + 120 解析，240 阶段在 66.345 秒完成；下一次 planning-only 周期同样为 120 + 120，45.533 秒完成。planning-only 只整理本地队列，不访问 Tushare。
- 首个 acquisition 与附件并行周期在 103.256 秒完成 753 次真实 Tushare 请求，约 437.5 次/分钟；无 failed stage、dispatch rejection 或本地 quota deferral。同时完成 117 下载 + 115 解析，共 232 阶段。对比两路代表轮 104 下载 + 103 解析、207 阶段/101.15 秒，三路在保留 API 吞吐时提高了附件阶段产出。
- 灰度观察内 `source_challenge` 保持 5275，没有新增挑战；当前 `download_timeout` 75、retry 18。新增终态包含实际 PDF 内容不匹配或不支持文档，原始证据与分类保留，不执行挑战或绕过来源保护。
- 验收边界的结构化队列为 done 286153、empty 251466、pending 2883549、split_pending 7732、blocked 871、permission_blocked 4694；pending 会因 15 分钟规划继续展开而短时增加，不能只用相邻总数计算完成量。

Mac LaunchAgent 保持自动运行并继续全量本地采集。云端只读研究缓存 timer 仍 active/enabled，`ARCHIVE_RELOCATED.json` 仍存在且没有全量 Tushare writer；本记录提交后再做 Git 交接，不改变该数据拓扑。
