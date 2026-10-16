数据到研究链路只读审计，2026-09-24，Mac。

范围：当前主树、Mac 归档/日志/只读 SQLite、双端容器与只读 PostgreSQL；只新增本记录、`docs/data-research-audit-20260924.md` 和同名 evidence.json。未修改采集/服务/数据库/研究状态，未调用供应商或启动研究。

审计中主树由 51c8f43c 更新到 77d57be6、af7df927；供数可用性修复属于并行的 research-cache-production-20260924 任务，本审计不接管该文件和发布窗口。23:13 云端仍因 64 MiB 清单限制失败；af7df927 随后提高到有界 512 MiB，真实新 CURRENT 切换仍需核验。

额外发现：云端 QuantDB 分区实际到 09-23，但系统解析的 Qlib 日历只到 09-18；Mac 两者到 09-22。Tushare daily/adj_factor/daily_basic 已完成样本仍到 09-18；recent:structured 游标 6000，而当前生成器第一个近期 daily 在位置 6243。两端 Agent 均仍用 frozen-controls-20260907-v3，未接入新 Tushare 研究输入；两端 PG 中 engine=deepagents 的课题均为 0。

完整证据、推断边界和分级建议见报告。不将旧 RRG blocked_data 或同步 completed 状态当成当前语义验收结果。
