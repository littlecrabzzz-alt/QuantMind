# QuantDB PG 内存修复及云端恢复完成
- 状态：完成；共享合并/服务重启窗口释放。代码 `7b5dcea5`，验收文档 `6a1569cc`，均已推送；双端 handoff passed，源码/Git 一致。保留既有 AGENTS、研究文档和 research_watch 未提交修改。
- 云端 job `qdb-recovery-20260926-111118` 已 completed/done，PG/Qlib 均为 9/24；38966 行、7 交易日与原始数据逐日一致。5570 个最新日 Qlib 标的逐一覆盖、还原价格通过；实际 D.calendar / D.features 读取通过。
- 11 项离线检查通过；隔离真实输入峰值 497.06 MiB；生产补跑 277.62 秒、峰值 580.21 MiB，cgroup oom/oom_kill 均为 0。相关服务已加载新代码，四个内部服务健康。
- 定时 A 股配置保持 enabled=true、03:00、with_qlib=true；daily_sync 和 Qlib 构建锁均释放。一次性恢复任务的 Redis 进度日期序列化已修正，并按已完成验收回填 completed，不重跑数据。
- 结果与完整证据：`docs/quantdb-pg-memory-recovery-20260926.md` / 同名 JSON。云端 `/root/code/QuantMind/data/maintenance/quantdb-pg-memory-20260926/` 保留 PG/Qlib 备份、执行回执、验收和 schedule-after.json。
- Tushare 已自动推进到 data-0b0146f7，实际日线 5557 行、9/24、upstream_calls=0；源端继续发布，source_lagged 仍为 true。
- 独立缺口未掩盖：北/南向私有模块未部署，整体日更仍可能显示 partial；128 个标的缺除权事件表仍走既有回退口径。同步完成不等于这些历史数据已获研究/交易准入。没有替换既有研究固定输入，没有开启交易。
