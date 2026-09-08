# ETF 申赎篮子纯合同

核对日期：2026-09-09。仅静态合同、惰性请求规划和离线测试，尚未注册或调用生产 API。

## 官方证据与字段

官方 [沪市 ETF 申赎清单成分](https://tushare.pro/document/2?doc_id=471) 与 [深市 ETF 申赎清单成分](https://tushare.pro/document/2?doc_id=472) 均说明每日开盘前公布、单次最多 3000 行、8000 积分。页面未说明额外独立权限要求或具体每分钟频率；账户实际权限未探测，不能由积分余额推断已经验收。合同中的 50 次/分钟是保守运行配置，不是供应商承诺。

两个 API 的输入均为可选 `ts_code / trade_date / con_code / start_date / end_date`，日期格式 `YYYYMMDD`；没有已记录的 `offset/limit`。输入表把 `ts_code` 写为“板块代码”，输出及示例明确对应 ETF。全部输出默认可见，没有已记录隐藏字段：

| API | 全部输出字段 |
| --- | --- |
| `etf_sh_cons` | `trade_date ts_code con_code con_name qty sub_flag cpr rdr sca exchange` |
| `etf_sz_cons` | `trade_date ts_code con_code con_name qty sub_flag cpr rdr sub_cc red_cc exchange` |

`qty` 单位为股；SH 的 `cpr/rdr` 分别是申购溢价率/赎回折价率，SZ 则分别是申购/赎回现金替代保证金率，单位都是百分比但业务语义不同。SH 的 `sca`、SZ 的 `sub_cc/red_cc` 金额单位为人民币元。保留原始 `sub_flag`，不封闭枚举。`exchange` 为成分市场 HK/SH/SZ/OTH，不能用它判断 ETF 上市地。

SH 官方示例 `517030.SH / 20260615` 含 `00001.HK`、零数量和声明为 float 的列中的 `-`。SZ 示例 `159051.SZ / 20260625` 包含 `159900.SZ / 申赎现金`、零数量、申购替代金额 512407.5 与赎回替代金额 141173.9。这些现金及境外行必须保留，不强制转换原始数值、不要求正数、不筛成 A 股，也不能从成分行建立股票或 ETF 标的库。

## 最小集成点

- 导出 `ETF_BASKET_CONTRACTS`、`iter_etf_basket_jobs(config, today, identifiers=None)` 和 `etf_basket_prerequisites(identifiers=None, enabled_apis=None, config=None)`。
- `identifiers['etfs']` 接受已存的供应商代码或含 `ts_code` 的记录；保留退市及特殊前缀，不按活跃状态或数字前缀过滤。按源代码 `.SH/.SZ` 路由两接口；其他市场记录为未覆盖缺口，不自行映射代码。
- 可配置 `etf_basket_apis` 与 `etf_basket_history_start`（单个日期或按 API 映射；兼容通用 `history_start`）。未配置历史下界时，每 ETF 发一个无日期发现任务，不能把返回的最早记录当成供应商最早历史证明。
- 所有 ETF 的最近 7 个自然日范围优先，priority 20、epoch 为当前日期或显式 `planning_epoch`；随后历史 priority 40、epoch `history`。不依赖未经验证的股票交易日历删日期。
- 已配置历史范围覆盖到最近窗口前一天，按已结束年份、当年已结束月份、当月逐日尾部分区惰性生成；不随每日变化重发整个旧年份。月/年边界会合并此前尾部，原有成功任务与观察必须保留。历史起点是用户请求范围，仍不证明更早数据不存在。
- 满 3000 行必须由父执行器按日期继续拆分。单 ETF、单日期仍满页时不得标完整；只有独立证明覆盖全部成分的集合才可用文档参数 `con_code` 再拆，不能用 A 股列表猜集合。无日期发现任务满页且下界未知时保留明确未解决状态。
- 自然键为 ETF、篮子日期、成分代码、成分市场；`preserve_distinct_rows=True` 配合原始行摘要与不可变观察保留同键内容修订。不得覆盖原观察或把不同现金替代数据静默合并。

## 尚不能宣称的完整性

官方页面未给历史最早日期、精确发布时刻/时区、公告时间戳、日内修订记录或最终封版时刻。`trade_date` 仅表示篮子适用日；`_fetched_at` 仅表示本系统观察时刻，都不能编造历史 `known_at`。最近 7 日刷新也不能证明更早数据不会修订，旧历史修订扫描需另行安排。

这两个接口没有提供完整 PCF 表头、最小申赎单位或总持仓/净资产分母。申赎篮子数量不能直接解释成持仓权重，更不能与季度 `fund_portfolio` 互相替代。ETF 全量及退市发现覆盖、实际账户权限、实际返回上限、历史范围仍待独立验收。

离线验证：`python3 scripts/test_tushare_etf_basket_contracts.py`，6 项测试包含官方目录字段一致性、日期无遗漏/重复、闰日、稳定旧分区、历史未知、特殊和退市 ETF、延迟生成及非法输入；测试禁用 socket 连接与 DNS，无生产请求。
