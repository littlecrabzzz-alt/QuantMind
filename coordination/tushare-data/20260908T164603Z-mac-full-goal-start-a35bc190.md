# Tushare 全目录持续接入：并行实施

- Mac / tushare-full-intake；目标活跃：按总计划接入账号可用数据、尽量全字段/历史/原文，云端采集并完整镜像到 Mac，非阻塞缺口记录后继续。用户明确授权并行推进，不能以七类 RRG 接口或样本验收代替全目标。
- 起点 master e4a5212；接续 20260908T162923Z-mac-complete-312d8bbf.md 与 docs/tushare-integration-plan.md、docs/tushare-integration-task.md。
- 主执行者 worktree quantmind-tushare-data-intake：backend/shared/tushare_pipeline.py、tushare_intake.py、tushare_store.py，现有三个 tushare 脚本/测试及 Celery Tushare 任务，config/tushare-pipeline.example.json、运行手册和统一进度清单。负责提速、统一频控、动态细分、落盘及发布；不编辑另一主题 dual_node_*、market_sync_scheduler.py。
- 文本子任务 worktree quantmind-tushare-text：仅新增 backend/shared/tushare_text_contracts.py、scripts/test_tushare_text_contracts.py、docs/tushare-text-intake.md。九个已购买接口官方参数/来源/历史/字段/频控与纯函数计划生成。
- 结构化子任务 worktree quantmind-tushare-structured：仅新增 backend/shared/tushare_structured_contracts.py、scripts/test_tushare_structured_contracts.py、docs/tushare-structured-intake.md、config/tushare-coverage-ledger.json。审计全目录并实现下一批主数据、行情、财务、宏观接口计划。
- 各子任务独立提交，不在共享主树写代码，不碰真实凭据/生产数据或服务。主执行者统一集成和实际云端探测/部署。子任务状态、文档、提交及缺口持续写入本主题唯一增量记录，跨压缩从 Git 与记录恢复。

下一步：预检、读取全部计划验收项，提速实测与新接口探测并行推进；权限不足、上游历史不可证实、源枚举不完整、PDF 失效、PIT 缺口分别登记，不阻塞其他接口。
