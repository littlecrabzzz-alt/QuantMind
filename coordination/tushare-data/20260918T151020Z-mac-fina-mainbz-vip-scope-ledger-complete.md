# Mac Tushare VIP 主营构成范围台账修复完成

- 结果：doc 81 的 `acquisition_api_names` 已补入 `fina_mainbz_vip`。候选提交 `a81eb6d5`，master 提交 `69237136`。
- 离线验收：scope/catalog/schema 共 13 项测试通过；重算审计 `registered_outside_named_scope=[]`、`registered_without_reader=[]`，249 个 catalog/discovered 命名 API 加 2 个相邻义务，总命名范围 251，247 个运行时可读。未注册的 4 项仍为 `ggt_monthly`、`p_save`、`p_delete`、`pro_bar`，分类不变。
- 审计产物：临时输出 `/tmp/tushare-scope-vip-ledger-20260918.json`，SHA-256 `af02d1a54ef6d9928f42ca7765bce4cb34b86369264af3bb73a53d69540e32a6`；不写入凭据或生产数据。
- 生产影响：覆盖台账不参与正在运行的采集进程，不需重启。LaunchAgent PID 71541 持续运行、从未退出。一个 `planning_only` 周期真实处理 2410 个文档任务；随后自动完成 780 次真实 Tushare 请求和 2500 个文档任务，耗时 105.827 秒，状态 `completed_cycle`、`completion_order=first_completed`。
- 语义：`planning_only` 是把全量范围持久化扩展为待采任务的周期，不是 dry-run 或演练；不证明历史、修订、PIT 或文档完整，后台全量补采继续。
