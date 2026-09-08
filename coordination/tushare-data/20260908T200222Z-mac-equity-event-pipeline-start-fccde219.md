# 7事件运行集成（离线）
- Mac remaining_markets，codex/tushare-other-markets；父31d2cd0已pick为2864d98，前序事件合同171398a。
- 独占registry/store/mirror、新test_tushare_equity_event_pipeline.py、既有store fixture数量修正；pipeline只import/record_equity_event_planning_gaps/家族校验注册/config签名，不碰publish/manifest_at或父代码。
- store依preserve_distinct_rows将源_row_identity加入去重键，显式标识不同原始行模式；缺失/空身份拒绝粗键去重，正常normalize总有身份。按history/cap/revision/discovery分别保存gap。
- 仅临时fixture验证capture→normalize→publish→read，禁止生产访问。
