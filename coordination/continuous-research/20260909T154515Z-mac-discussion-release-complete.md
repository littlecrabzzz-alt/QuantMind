# 研究讨论与计划确认改版完成
- 代码 bba6453（含 fba592f/8c9e281/78a303a/8586b8f），已合入并push master；本条与验收文档是最后的记录更新，不再修改运行逻辑。
- 两端研究表已备份，新增v2 drafts表；API和专用research-worker已重启，云端web-publish通过。handoff已核对bba6453/数据快照一致，末尾文档提交后补最终核对。Tushare及通用worker未重启。
- 隔离HTTP/DB并发/事务回滚/归属/暂停/新版本/重试不倒退检查通过；原Docker取消/恢复通过，17项合同单测与前端typecheck通过。
- 真实API与浏览器：本地黄金ETF准备方案不可启动，问答不改计划；固定模板计划修改形成v2，旧版仅可看，未勾选不能确认、返回讨论不执行。云端仅问答成功且无计划/执行。模型格式失败和语义修正均记录，实际步骤来自工具定义。
- 最终活动研究0；窗口数量保持本地12/云端3，旧取消/暂停/结果保留。本轮不执行新训练、模拟或实盘。
- 证据：.local-dev/project/data/research/validation/discussion-20260909/summary.json；详细范围、真实失败与限制见 docs/research-workbench-validation-20260909.md，后续迭代见持续研究Plan。
