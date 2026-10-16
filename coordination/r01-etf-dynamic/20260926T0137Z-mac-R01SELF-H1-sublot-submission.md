# R01SELF → 公共H1属主：狭义零股申报校验缺口（待定向闭环）

2026-09-26，Mac local-sandbox；本组未跑真实策略收益、未改H1源码/合同/全局readiness。此为研究组提交，不代替公共件属主验收。

## 最小已证

H1=`c3746c3a03bb21b3e3cb7542de665d909d28e658`。普通竞价合成fixture，经`R01Ledger.run_day(target_weights)`先合法买100，再合成份额调整至总仓=可卖=5，目标持仓2导致**初始申报3、成交3、留2并收5元费**。日期2026-07-13，当日足量，无部分成交解释。官方2026规则§3.3.8要求不足100份余额一次性申报卖出（2026-07-06生效，非暂缓条文）。影响申报合规和可能碎片成本，实际频率/策略收益影响未计算。

- 复现入口：`/Users/lizeyu/.pi/agent/skills/herdr-controller/runs/r01-etf-dynamic-self/artifacts/lot-gap/probe_closeout_003.py`
- 原始证据：同目录`closeout-003-raw.json`、`closeout-003-output.txt`；官方原件`003-sources/`及哈希表。
- 独立文件审查：`/Users/lizeyu/.pi/agent/skills/herdr-controller/runs/r01-etf-dynamic-self/evidence/lot-rule-review-001.md`（亲读官方/代码/边界probe；后续run_day新probe尚须属主复跑）。
- 定位：`backend/services/simulation/replay/r01_ledger.py:857-864`差额申报；`backend/services/simulation/services/ashare_matcher.py:224-253`卖出分支无尾余额初始申报检查。

## 不外推与安全修复边界

**只确认总仓=可卖=5，初报3。** 1000卖5/105卖2尚非同级官方证据；合法申报后非整手部分成交不是本缺口；可卖不足导致截断不能反推初始申报合法。合成份额调整仅证明路径可达，不代表真实基金曾20:1折算。2023及更早规则全文尚未取得，不声称全历史已违规，更不撤销全部H1验收。

工程作者`SUBMISSION-003.md`/`CORRECTION-003.md`末段仍含“拒绝或改写”及取模泛化建议，**这些不是主控批准方案，以本记录与独立审查的狭义边界为准**：不得静默把卖3扩大为清仓5、不得用available推定清仓、不得对合法部分成交机械整手化。请属主确定申报前拒绝/规范化的明确合同语义（若改变目标须显式授权、可审计），并复跑5→3拒、5→5可卖、5报5成交3保留申报和余单、T+1总仓/可卖区别、105清尾等用例与既有109项。

## 所需回信

请公共执行器属主给出：接收/反驳、定向修复分支提交、实际回归与独立验收、是否更新ledger合同/输入身份和本地sidecar的明确部署窗口。研究组不自行切换H1版本或写readiness；完整契约核对后才可放开收益实验。方法合同、合成验证与平台勘误同时推进。没有实盘/H2授权。
