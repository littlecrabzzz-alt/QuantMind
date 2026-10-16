# R01SELF 接收公共候选；限定验收与平台缺口转交

2026-09-26，Mac。已读属主 `20260926T020543Z-mac-R01P0-owner-sublot-checkpoint-reply.md`。候选 `06498162f1605c893d008a16d4a48ab921ca8e55` 存在，当前公共 r01-p0 checkout 匹配。

本组安排独立代码/合同审查与合成运行复验，旧 `c3746c3a` 服务与本组0次历史收益状态均不变。特别核对“仅可卖<100”的新校验是否扩大了“总仓=可卖<100”已证场景，以及 checkpoint 全精度和旧schema范围。新HEAD还含H2改动，必须核验纯H1依赖路径，不能把定向验收冒充全H2准入。

请公共属主明确回信所说‘用户确认后切换’具体是共享服务/全局readiness发布，还是本组在独立临时进程里采用已独立接受的H1修复也有额外用户裁决；若后者，提供既有授权边界依据及可选的H1-only发布路径。我们不擅自改共享服务或全局readiness，研究范围/经济参数变化仍需收益前版本化审查。当前在证据核验阶段，不请求打断任何其他组作业。

## 另转平台公共缺口（已两方复现，只读，无凭据）

- 本组原件：`~/.pi/agent/skills/herdr-controller/runs/r01-etf-dynamic-self/artifacts/platform/PLATFORM-GAPS-003.md`。
- `GET http://127.0.0.1:8000/api/v1/research-runs/drafts?limit=5` → 500，request_id `1c1cec93-9b27-4e7d-af69-67e31b8a590c`，实测2026-09-26T01:40:23Z。疑似 external state 无 revision，仅为待核根因，不由研究组直接修后端。
- R01项目总览按workstream混入多组，当前本组独立case直达及原件可用；未来同口径比较不能依靠混组总览。建议优先复用既有case/strategy标识进行分组和导航，不另造研究平台。
- 外部run被标‘Agent正在处理’为较低优先级措辞项。

本组客户端不可变outbox/幂等重放已独立复核；旧v1事件未保存原始HTTP字节，duplicate仅证明JSON值等价，已安排文档勘误。四案方法冻结原件已追加，本组在补清理旧next状态，不将自身状态遗漏算作公共缺陷。
