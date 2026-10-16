# R01P0-H3P1 修复与冻结记录（2026-09-25T13:3xZ, mac）

- 最终 HEAD=`74d0b3e0`（H2R 五项修复+证据脚本修正链：33186a93→73efbeea→74d0b3e0；
  此后零代码提交）。H 轮组合证据：artifacts/p04/h1/final/（README 汇总）。
- 修复对照：①g2 手工 days=历史演示移出验收入口（grep 仅存历史脚本）；②ledgerAdapter
  evidence 严格校验（null/形状不符→AdapterFormatError 显式拒绝，pytest+node 双覆盖）；
  ③classifyRunKinds 四类分立（工程回放/历史研究/持续虚拟运行/真实交易，未知显式未知）；
  ④fixtureConsistency 两层核对（不一致警示不静默取其一；最终账本 group=A 两层一致）；
  ⑤H1.3 run-a/b 绑定真实 v2 包身份，manifest+README 注册可打开，constraints-links 为实际绑定。
- 回归四件在冻结 HEAD：单测 70p、E2E 53/53、typecheck 0、dashboard:build 0。
- 沙盒恢复：r01 临时容器删、原 sidecar 健康、builtin-regress 清理。

> H4P2 终修（2026-09-25T14:0xZ）：legacy 样例两层 fixture 一致（fixture=true+fixture- 策略）、
> h13 输入产物 seq 修正（0 stale_event+断言）与文件 GET 逐字节证据。**新冻结 HEAD=`d215c7fb`**
> （此后零代码提交）；组合证据 artifacts/p04/h1/final-h4/（commit=d215c7fb，回归四件 70p/53-53/0/0），
> 旧 h1/final（74d0b3e0）保留历史轮。
