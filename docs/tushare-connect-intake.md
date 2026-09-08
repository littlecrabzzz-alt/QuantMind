# 互联互通与板块资金流：纯合同候选

基线 `fef5233`，审查日期 2026-09-09。本轮只新增纯合同、说明和离线测试；未注册 runtime、未探测账户、未修改覆盖台账。`moneyflow` 已在 structured 注册，`moneyflow_dc/ths/mkt_dc` 已在 supplement 注册，均跳过。

| 候选 API | 当前官方正文 | 行数/权限依据 | 请求分区 |
|---|---|---|---|
| stock_hsgt | [398](https://tushare.pro/document/2?doc_id=398) | 2000 行；3000 分；声明自 20250812 开始 | 每个日期 × HK_SZ/SZ_HK/HK_SH/SH_HK |
| hsgt_top10 | [48](https://tushare.pro/document/2?doc_id=48) | 页面未列积分或数值行限；1000 仅本地饱和警报 | 每个日期 × market_type 1/3 |
| moneyflow_cnt_ths | [371](https://tushare.pro/document/2?doc_id=371) | 5000 行；6000 分 | 最近逐日；历史按月起止日期 |
| moneyflow_ind_ths | [343](https://tushare.pro/document/2?doc_id=343) | 5000 行；6000 分 | 最近逐日；历史按月起止日期 |
| moneyflow_ind_dc | [344](https://tushare.pro/document/2?doc_id=344) | 5000 行；6000 分 | 每个窗口 × 行业/概念/地域 |

五页均未列数值每分钟额度，合同 50/min 是保守运行上限，必须叠加账户及实测接口门限。积分门槛不等于已授权；`hsgt_top10` 的门槛保留 unknown。五页没有停更日期，不能据此承诺今日数据仍然更新。港通名单页面写明约 09:20 更新，十大成交页写明 18–20 点更新。

全部官方输出字段保存在 `FIELDS/extra_fields`，输入参数另存 `INPUT_FIELDS`。398 的类型枚举表是参数值表，不是四个额外参数：已排除旧 catalog 解析误纳的 `HK_SZ/SZ_HK/HK_SH/SH_HK`。其示例在指定一个 type 时展示多个 type，应验实际响应的日期/type 一致性，不能用示例证明过滤有效。

THS 行业和概念金额单位为亿元；DC 金额为元，比例为百分比。十大成交 `change` 是涨跌额，金额为元。保留源小数、负净额、空值与股票名称；不根据展示样例的加减关系改写原值。自然键包含 source `type/market_type/content_type`，不会把渠道或板块类型并为一条。`.HK`、`.TI` 与 DC 板块原始代码不是同一个股票/行业分类体系，未证明可交易身份或 RRG 分类适用性。

## 纯接口与后续集成边界

```python
CONNECT_CONTRACTS
iter_connect_jobs(config, today, identifiers=None)
connect_prerequisites(identifiers=None, enabled_apis=None, config=None)
```

配置使用 `connect_apis`（默认本轮 5 个）、`connect_history_start`（YYYYMMDD 或逐 API 字典，回退 `history_start`）。所有最近 7 个自然日与全部明确类型先输出，priority 20，epoch 为当天或 `planning_epoch`；随后按 API 轮流输出历史，priority 40，epoch `history`。历史按月的三个资金流接口仍声明合法 start_date/end_date 日级二分，饱和月应递归细分。十大成交页要求代码或日期，规划始终用 exact trade_date，避免仅范围或空请求。没有交易日历捷径、抽样上限或推断历史起点。

港通名单使用官网声明的 20250812 下界，不能重建此前 PIT 成员关系。其他四项未声明最早日期；没有用户日期范围时只规划近期并留下 unknown-history gap。配置一个早期范围也不证明该范围之前无历史。七日重叠不保证捕获所有旧日修订，采集时间也不是历史可得时间。

未来 runtime 需注册 family `connect`，安装本模块，并将这五个接口各自已存原文发现的代码送入 `connect_<api_name>` 标识族；不复用纯 A 股 master 来枚举香港代码或板块代码。当前 planner 不依赖发现就能发全市场/明确类型窗口；`saturation_fallback` 仅供饱和时在父观测代码基础上分片，始终继承原有日期/类型过滤。新增 identifiers、normalization/API 读取及镜像字段身份仍需父任务集成验证。

成功子集合不证明证券/板块全集。缺少文档分页时不创造 offset；单代码/日期/类型仍饱和则保留 gap。所有这些限制由 `connect_prerequisites` 输出，港通成员 PIT、未知历史、旧修订、未知行限和样例过滤问题分别记录。

## 未进入合同的优先候选

2026-09-09 直取以下官网页面均为 **HTTP 200，但正文只有“404, 文档不存在！”**：

- [moneyflow_hsgt，47](https://tushare.pro/document/2?doc_id=47)
- [ggt_top10，49](https://tushare.pro/document/2?doc_id=49)
- [ggt_daily，196](https://tushare.pro/document/2?doc_id=196)
- [ggt_monthly，197](https://tushare.pro/document/2?doc_id=197)

官方 [waditu/tushare-data 索引](https://github.com/waditu/tushare-data/blob/b68d5517e0cbe84d61774de26ad366d900c7eb92/tushare/references/%E6%95%B0%E6%8D%AE%E6%8E%A5%E5%8F%A3.md)仍列这些名字，196/197 的 `/wctapi/documents/<id>.md` 链接也返回 404；搜索引擎仍有 47 的旧缓存。保留 `source_missing/review_required`，不能把缺正文解释为确定停更、无权限或删除历史义务。本轮不依据第三方转载/缓存造当前字段与权限合同，也不为凑数选第六项。

## 源证据与离线验证

公开正文保存于 Mac `/tmp/quantmind-connect-docs/<doc_id>.html`；以下 SHA-256 是本轮直接响应原字节，未使用账户或 Tushare API token。

| doc_id | SHA-256 |
|---|---|
| 398 | b2c42ccbf8d9fec459cdbcf0d812db217773a7496a8e3b34e0a1c64d77ad80a4 |
| 48 | 99ffc50728378e821a4fd34285acf1e6a3b66848a100ec738a2c1c0513cef468 |
| 371 | 9e4f486746c7145cf68941cf4242fef7117d77a0dfd57d60182a43b3372d3947 |
| 343 | 43e72c86c54dede3c17dc077d25c5991c0cfb925187af56fd9bebc12a8d94d4a |
| 344 | b6add81884b34d4ba9ff344b680fea46b362f26a0422c40374c5f55c051f888e |
| 47/49/196/197 | bbf4318386ca0ea4c5072fc5e67fe0302f473ccbeba7238c45607226236dfadf |

运行 `uv run --no-project --with httpx python scripts/test_tushare_connect_contracts.py`。检查当前未注册、字段与 catalog 一致、398 枚举修正、全方向/类型日期无遗漏重叠、闰月边界、未知历史不猜起点、负数/空值原样通过、长历史惰性、输入校验。实际权限、源过滤、归一化、离线查询和生产完整性尚未验证。
