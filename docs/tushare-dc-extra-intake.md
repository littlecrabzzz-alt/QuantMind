# DC 历史成分与行情两接口纯候选

对照固定 263 项目录基线、13 项额外发现与 148 个生产 API，加 concept4 候选，本批只补目录 363/382 的 `dc_member`、`dc_daily`。两项无待解释的 API 别名，不替代其他目录义务。只新增纯合同、专属测试和本文；未注册、未 probe、未启用或采集。

| 接口与官方依据 | 合同要点 |
|---|---|
| [dc_member / 363](https://tushare.pro/document/2?doc_id=363) | 历史每日成分从 2024-12-20 起，单次 5000。完整输入 `ts_code,con_code,trade_date,start_date,end_date`；完整输出 `trade_date,ts_code,con_code,name`。 |
| [dc_daily / 382](https://tushare.pro/document/2?doc_id=382) | 板块行情从 2020 年起，单次 2000。完整输入 `ts_code,trade_date,start_date,end_date,idx_type`；完整输出 `ts_code,trade_date,close,open,high,low,change,pct_change,vol,amount,swing,turnover_rate,category`。 |

两页所有输出均默认 Y，无默认隐藏列；仍显式请求并校验全部 17 列，保留合法空值和以后返回的新列。两页列出 6000 分门槛，未说明独立权益或各接口每分钟/日调用数；账户真实权限保持 `unprobed`，50 rpm 仅本地运行上限。

导出 `DC_EXTRA_CONTRACTS`、`iter_dc_extra_jobs(config,today,identifiers=None)`、`dc_extra_prerequisites(...)`；建议未来组 `dc_extra`，配置 `dc_extra_apis`、`dc_extra_history_start`（字符串或每 API 字典，回退 `history_start`）。默认采用各自文档起点；20200101 只是“2020 年”的规划边界，不宣称实际第一条日期。配置较晚起点继续记录早期未请求范围。

最近 7 个自然日逐日请求，历史按 API 轮转惰性生成；不以当前上市/板块集合过滤。行情显式覆盖“概念板块/行业板块/地域板块”三类，成分每天一次无代码过滤。`idx_type` 在官方输入表是可选，本候选为覆盖策略而要求显式传入；返回字段名是 `category`，对应字面值未获真实响应证明。保持三类请求身份，不能用响应相同推断类别等价。未选择月窗：每日全部成员很容易触及上限，窗口变大可能增加二分探测开销，需真实样本后另评估。

自然键候选为成员 `(trade_date,ts_code,con_code)`，行情 `(ts_code,trade_date,category)`；都保留不同源行，行情再保留请求 `idx_type`。日期轴都是 `trade_date`。DC 板块 `ts_code` 保持来源原值和独立 `dc_indices`，不能套 THS 或股票标识；成员 `con_code` 示例包括 SH/SZ/BJ，仍保留源字段，未知跨市场形式不猜转换。行情成交量单位是股、成交额是元，不能沿用 THS 手数或其他 DC 万元字段。

未来接入须继续显式留缺口：

- 合法日期范围可二分，单日可按 `ts_code` 分片；两页均没有 offset/limit 输入。发现集合应并入 DC 分类、行情、成员的历史原始观测，不能凭当前目录证明退市板块齐全。
- 成员单日单板块饱和后还可合法按 `con_code` 查询，但需要完整历史成员发现；现有单维代码拆分不支持证明这一层完整，必须继续 blocked。
- 每日历史成分确实比当前快照提供更多历史信息，但缺少当时公布时刻、成员生效区间与权重；不能造 `in_date/out_date` 或据此解除 RRG 的 `blocked_data`。7 日重叠也不证明旧修订、删除完整。

离线复验：`python3 -S -B scripts/test_tushare_dc_extra_contracts.py`，7 项测试覆盖官方列/参数、权限未知、类别请求身份、各自起点、跨年闰日覆盖、惰性轮转、配置校验；不导入 Pipeline、不联网、不访问生产。
