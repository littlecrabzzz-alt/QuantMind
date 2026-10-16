# S03 四组信号机制消融完成
- 收到数据会话正式准入，使用deps-v2 manifest aee884ff…与限定面板；不再等待或补数据。
- 冻结L/LT/MT/LT-cash，周频、100万/95%原场景、4/7～6/30开发窗，先选股落盘再读标签。13信号，末次越窗共同剔除，12配对。
- 下一交易日前瞻标签配对差：趋势LT-L −16.52bp（3正9负）；低波LT-MT +14.11bp（6正4负2同）；现金LT-cash-LT −1.71bp。不是净收益/周持仓/独立OOS。
- 产物沿前记录目录：signal-ablation.json、frozen-signal-selections.csv、paired-forward-label-scores.csv、SIGNAL-ADDENDUM.md、RESULT.md；执行退出0，硬件检测警告留日志。
- 四组撮合收益尚未执行，仅原Qlib环境受Docker权限/宿主缺包阻碍；不重写成交引擎。需要父会话安排可用原引擎环境，禁止绕过。未改平台代码/服务或旧结果。
