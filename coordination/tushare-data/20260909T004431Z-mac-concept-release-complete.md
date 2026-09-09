# concept4本轮生产闭环与下一轮接续

- Runtime100e4df已主线/云端核对并发布，文档/台账096fee8+5615f56；404全Tushare测试12.380秒、Ruff通过，目录/合同另9测试。全部本轮暂停已恢复：acquire1f84450c-2506-4d74-90bb-b9768b49878d、documents768c6e8e-d036-415a-9a75-a164eaa33ddd及各queue实测；US88fe98db保持。最新00:33:56Z批265请求/120.401秒、failed_stage=null。
- 已启用ths_index/ths_daily/ths_member/dc_index；8请求6.139秒、5803行、40字段全返回，三DC类别过滤正确，原值/Parquet/hash通过。fixed data-e1386fc1f304f2ef6ef34d3c59ec99b4f3d1ec34fd49c9841ddd7591a74e1bce 全5803行云端30HTTP+Mac禁网对账通过；Mac159836文件verified、24样本证据SHA。报告和精确字段缺口见docs/tushare-concept-extra-intake.md、docs/tushare-progress.md 08:36。
- 成员weight/in/out全null、目录A/BB样本实为.HK成员（count306/返回309），未将目录exchange当成员市场；四自动member响应5099—5549超过未知cap本地guard，完整来源保留、possibly_truncated继续记gap。history规划仍在跳过成员近期段，并非历史已完成。总152采集+6查询别名，原263+13范围不变。
- 下一DC两项准确pick顺序523d32b→94d66a1（均已push codex/tushare-dc-extra和codex/tushare-dc-runtime），基于100e4df，417tests，通过但未生产probe/enable。原文记录003657Z。父下一轮独立集成检查、备probe/API/Mac验收后再短发布，不立即暂停当前采集。
- structured正在独立codex/tushare-publish-interval准备tick发布最小间隔候选（基于100e4df，仅tick、新test/docs）；默认0兼容，后续可选900秒但未启用。原始响应/observations/API attempts/文档attempts持久化继续，降低的是全量状态清单发布次数，需验证后续全证据收录及新鲜度状态。不要将44.72GiB/日静态manifest估计当实测增长；旧164副本最多3.628GiB去重潜力尚未执行或完整hash审计。
- 源码单写边界保持云端权威；不重启Mac旧主栈。旧互联互通过滤probe未执行、全目录剩余/历史/修订/PDF/RRG PIT仍未完成，goal active。本轮为实质进展而非完成全目标。
