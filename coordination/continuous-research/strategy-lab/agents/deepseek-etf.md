# DeepSeek Flash：S01 ETF准入调查

本文件由本波只读调查结果整理，完整证据位于本地产物 `evidence/etf-tushare-probe.json` 和 `evidence/etf-executor-gap.json`。

## 结论

- 数据面：五只预设ETF在固定镜像 2024-10-08 至 2026-09-10 的472个交易日均有行情，研究窗57日和121日预热无缺口；复权因子为正。
- 数据限制：2015年以来有28—30个缺口；ETF涨跌停表覆盖不完整且pre_close为空；没有历史known_at/公告时间、交易单位和完整申报单位。
- 执行限制：冻结Qlib只有股票，没有ETF；现有CnExchange默认收盘成交，且卖出对所有标的收印花税，不能直接用于ETF次日开盘轮动。
- 区分：ETF二级市场趋势轮动只需要ETF行情和复权，不需要RRG成分或PCF；RRG/PCF缺口不应被误报为ETF行情缺口。

状态：数据在限定近端窗口 `ready`，历史PIT和规则 `blocked_data`，现有执行器 `blocked_executor`，整体不能直接进入收益回测或虚拟盘。未执行回测、采集或交易。
