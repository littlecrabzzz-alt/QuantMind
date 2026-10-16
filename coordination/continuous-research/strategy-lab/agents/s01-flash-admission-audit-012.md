# S01 ETF 准入审计012

- agent：`qr-flash-0b55` / `w1:p5`
- 实际模型：`glm-5.3-flash`
- session_decision：`reuse`，Herdr `default/w1`
- 本地归档：`/Users/lizeyu/.local/share/quantmind/strategy-lab/wave-001-20260911T160311Z/evidence/s01-admission-audit-012.json` 和 `.md`

## Verdict

S01 继续 `blocked_executor_and_admission`，`no_return_numbers_gate=true`。固定 release 的近端覆盖和 U2 相对单位换算已证；U1、U3-U7 尚待查，U8 PIT 被明确外部数据阻塞。不得产生 ETF 收益数字。

## 已证

固定 release 本地只读读取无上游调用；五只 ETF 的前缀代码、键唯一性、57 日研究窗和 121 日预热覆盖已核对。冻结 Qlib provider 不含 ETF。股票 CnExchange 对所有卖出收印花税且默认 close 成交，与 ETF 二级市场和 S01 open 成交要求不匹配。`etf_worker.py` 仍为含 `NotImplementedError` 的 skeleton。

U2 仅能确认相对换算：`vol×100`、`amount×0.1`；绝对单位标签没有外部锚。U1 复权基准、U3 过户费、U4 佣金、U5 申报单位、U6 表达式、U7 ETF 涨跌停仍待查。

## 外部阻塞

固定 release 没有历史发布时间元数据，观察/抓取时间不能证明 PIT。需要用户或外部权威来源提供 release、数据集和历史发布时间证据；在此之前停止外部数据派发和 ETF 收益回测。

未下载数据、未改源码/合同/冻结输入、未启动容器/回测/虚拟盘/实盘。
