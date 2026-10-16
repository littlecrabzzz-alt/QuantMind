# Mac 离线记录契约 v3 修订完成

- 范围：父会话独立复核要求的失败原因持久化最小修订；候选仅在 `.local-dev/project/data/research/diagnostics/forward-startup-package-v3-20261010T190443Z/`，不改共享后端/运行配置，不提交/发布。
- 复用：v2 合成 Records/校验器，扩大失败状态显式允许列表，新增记录保存 status=reason_code；合法计划身份与被拒绝尝试哈希分开。原 v2 第一次29项及最终30项通过记录、v1 原件均逐文件校验未变；29项后问题是覆盖缺口。
- 验证：35项合成测试全部通过，包括 late_input、late_validation、late_seal、ambiguous_versions、hash_conflict 的实际校验拒绝→失败写入→临时文件→新实例重读→幂等重试。原因、字节和原时间钉保持；拒绝泛化改写及失败补救。临时合成文件已自动清理。
- 新配置 SHA-256：`8afabb82de4a23ddc8f94835ab8f959583445b7e0c4d4c88878924c08d7d8022`；源码 `ea2fbfe45916ef09b95a6866b66c8087c5cc6cee7fcd00cca87fb18845f398eb`；报告 `1839a79e6d5de161c634fb407b82e03d4577db0906c80e37a20dfe4b2a3062b8`。目录 SHA256.json 与 final-verification.json 保存完整证据。
- 关闭状态：enabled=false；激活绑定仍为空且不存在 activation.json；无参数实际输出 DISABLED。冻结公式/参数/日历不变。无真实行情/预测/收益计算、研究任务、网络调用、部署、服务重启、交易或权限扩展。
- 限制与收口：证明离线合成契约，未证明生产持久化、实际采集到达或独立可信时间。实际启动须单独确定执行范围与真实记录/证据条件。本修订已完成，不另开后续任务。
