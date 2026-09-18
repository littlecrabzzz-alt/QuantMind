# Mac Tushare 附件四路下载生产验收

- 时间、节点、任务：2026-09-18T04:28:00Z，Mac 全量归档所有者，document-four-downloads。
- 代码：`95f64c8b` 允许 1 至 4 路公开附件下载，并让原生 worker 严格校验 1..1000 阶段、0..100 秒和 1..4 下载；保留的 Celery 入口同步接受当前 600/100 边界。四路 durable claim、并行原始下载、解析不与下载重叠及全局截止均有测试覆盖。
- 验证：文档下载/解析、租约、挑战、worker、原生循环共 64 项测试通过；Ruff 与 `git diff --check` 通过。

生产部署：

- 旧 PID 29460 在 2026-09-18T04:19:37Z 完整结束 739 次真实请求、231 下载 + 229 解析、`failed_stage=null` 后安全卸载。
- 私有配置仅把 `document_download_workers` 从 3 调到 4；600 阶段、100 秒、登记 100/5000/5、单下载 20 秒、失败退避和 Tushare API 限速不变。配置 SHA-256 为 `87312dec4e74621fa173357702432ef30d72298840a5dfecd30dbd09f2d58c99`，权限保持 0600。
- 新 LaunchAgent PID 33382 已加载安装副本；`tushare_documents.py` SHA-256 为 `b8054f125b806af1259107e41ad062f5ba0b9657abd79675b42306b3e02307cf`，archive worker SHA-256 为 `3ea4d6690b5a35c24e2b7b93938360ec474fed5adefb54c85f0dc06902c04708`。

真实生产验收：

- 部署前最近四轮三路分别为 762/240、765/192、757/156、739/231（API 请求/下载），API 平均 755.75，下载平均 204.75。
- 部署后首轮配置指纹 planning-only 只验证四路代码加载，不计入对比。随后三轮真实 acquisition 分别为 763/232、745/228、759/244，API 平均 755.67，下载平均 234.67；解析分别为 229、225、241。
- 四路使真实下载平均提高约 14.6%，API 平均基本不变；三轮 `dispatch_rejections=0`、`failed_stage=null`，登记器每轮继续处理 5000 条 records。
- `source_challenge` 保持 5275。验收时 download_timeout 83、retry 47；相对四路部署前已有的 timeout 76 增量属于已保留的有限重试，不伴随挑战增长或周期失败，继续观察但不绕过来源保护。

验收边界结构化 pending 2879709、done 300081、empty 261262；附件 pending 1507362、parse_pending 74956。pending 因登记器每轮补入 5000 条历史记录而上升，四路已提高消费速度但完整登记尚未结束。Mac 继续作为唯一全量 writer。
