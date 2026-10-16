# 主题：R01-P0.3 分红三段式账务（p03_execution F2E2）

- 时间、节点、任务标识：2026-09-25 · mac · R01P0-F2E2（wave F2 attempt 2）
- 状态：**done**（ledger-contract v3 §5/§6/§8 实现；验收三回归值精确对上）
- 提交：`herdr/r01-p0` @ `9d0c75f746fd75037ca2c2149f7cf38efdcfafde`（仅 owns 5 文件）
- 输入：v2 包 `node://mac/r01-etf-daily/v2-fcbabbb7`（manifest_sha256 a0d88429… 校验通过；只读未改）；证据 `<run>/artifacts/p03/fixes-f2/`

## 要点

1. 三段式：record EOD 定格（登记日买入享有/卖出不消灭；record→ex 份额调整口径乘数换算）→ ex 开盘前入 dividend_receivable（计 nav、不可交易）→ pay 开盘前转可用现金；旧 ex-EOD 发放路径删除；幂等键 (run, symbol, event_id, record_date) 三段共用。
2. nav=cash+应收+持仓，应收参与两风险线；unknown_blocked 三段全阻塞+停买；v1 事件缺日期加载即显式阻塞；schema v3 消费（share_adjustment 禁混字段）；checkpoint v4。
3. 独立复算按 record 持仓独立重算资格（只读包事件，不读引擎分红日志）。
4. 验证：三回归精确（150 应收保留/pay +150）；33/33 v2 分红事件回放对账残差 0；v2 十窗口 ALL_PASS 0.0%；回归 282 passed；沙盒 PG 11/11；v1↔v2 差异=ex 起恒 +150 应收、pay 转现金（v1 阻塞无账务，见 diff-v1-v2.json）。
5. interface-samples/AB-QUICKSTART 已同步 v3。
