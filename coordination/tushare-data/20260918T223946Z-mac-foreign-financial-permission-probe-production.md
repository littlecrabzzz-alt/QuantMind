# Tushare 港美股财报权限验证生产完成

- 时间、节点、状态：2026-09-18T22:39:46Z，Mac 全量归档唯一写入者；有界权限验证完成，正式全量同步已恢复。
- 代码：候选 `269358ce`，master `f6a96ad1e684f4e0809866a65658ac2764eed3d3`。新 helper 默认 dry-run，执行需同时钉住 helper 和合同 SHA，校验 Mac 归档权威、SQLite v6、标的发现记录和两层唯一写锁。
- 真实权限：`hk_income`、`hk_balancesheet`、`hk_cashflow`、`hk_fina_indicator`、`us_income`、`us_balancesheet`、`us_cashflow`、`us_fina_indicator` 各请求 1 次，8/8 为 `permission_denied`。当前账户没有港股财报/美股财报独立权限。
- 决策：继续保持 `enable_foreign_financial=false`、`foreign_financial_apis=[]`；没有生成约 27.4 万个无权限历史根任务，没有修改其他速率或队列配置。
- 脱敏：本地收据 SHA-256 为 `62810ad4e045d196d1ea93ecd0456103305b64b1e88a0d49f5381e7d00aec0dc`；收据、8 个 raw object 和 8 个 observation 共 17 个产物均确认不含 Token。
- 验证：专项 44 项通过；完整 Tushare 离线套件 1389 项通过、5 项跳过；Ruff、编译和 diff check 通过。证据见 `docs/tushare-foreign-financial-permission-production-20260919.json`。
- 恢复验收：LaunchAgent 新 PID 383，首个正式续传周期完成 395 次 Tushare 请求和 2500 个文档阶段，`failed_stage=null`，本地仍约 1.92 TiB 可用。

下一步：继续当前本地全量历史补采；仅在购买并重新实测港股/美股财报权限后才启用这一组历史计划。云端仍只保留研究子集，不恢复全量写入。
