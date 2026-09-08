# 其他资产与国际利率接入增量

2026-09-09，基于 [总体方案](tushare-integration-plan.md)。这里只增加 15 个只读接口的纯契约/规划器，尚未注册、实测账号、部署或宣称历史完整。父任务继续负责全目录接入；本批不替代其余接口、历史版本、附件、Mac 镜像和消费验收。

所有字段在 `tushare_other_contracts.FIELDS/extra_fields` 显式列出，顶层 `fields` 参数必须发送其并集；新增未知原始字段照常保存。自然键用于同一逻辑记录的版本读取，不删除原始观察。不限制数值为正：零、负利率、空期限与未成交合约均可能合理。运行频控 50 次/分钟是保守配置，不是实际账号权限或官方频次证明。

| 接口 / 官方明细 | 主键 | 单次阈值 | 明细积分 | 规划与完整性边界 |
|---|---|---:|---:|---|
| [opt_basic](https://tushare.pro/document/2?doc_id=158) | ts_code | 未说明，报警 6000 | 5000 | 无过滤 + 六个已文档化交易所 + 逐 `list_date`；保留已到期、退市合约。没有合法 `list_status`、日期范围或 offset 参数。 |
| [opt_daily](https://tushare.pro/document/2?doc_id=159) | ts_code, trade_date | 15000 | 2000 | 全市场逐日，饱和后按完整 options 发现集分代码；代码或日期至少一项。 |
| [sge_basic](https://tushare.pro/document/2?doc_id=284) | ts_code | 100 | 5000 | 无过滤一次取当前目录；退市目录完整性未说明，不能据当前不足 20 个推断所有历史。 |
| [sge_daily](https://tushare.pro/document/2?doc_id=285) | ts_code, trade_date | 2000 | 2000 | 全市场逐日，按 spot_metals 兜底；文中提分页但参数表无游标，不虚构 offset。 |
| [fx_obasic](https://tushare.pro/document/2?doc_id=178) | ts_code | 未说明，报警 1000 | 2000 | 无过滤获取全部类别；不只 FX，也包含 INDEX、COMMODITY、METAL、BUND、CRYPTO、FX_BASKET。当前只明确 FXCM，退市范围未说明。 |
| [fx_daily](https://tushare.pro/document/2?doc_id=179) | ts_code, trade_date | 1000 | 2000 | 全市场逐日，按 fx_instruments 兜底；原日期为 GMT，不能直接解释成 A 股交易日。 |
| [libor](https://tushare.pro/document/2?doc_id=152) | date, curr_type | 4000 | 120 | 显式 USD/EUR/JPY/GBP/CHF 五币种，各自年度区间；省略币种只会取 USD。 |
| [hibor](https://tushare.pro/document/2?doc_id=153) | date | 4000 | 120 | 年度区间，无股票代码或交易所参数。 |
| [wz_index](https://tushare.pro/document/2?doc_id=173) | date | 官方不限，报警 10000 | 2000 | 无过滤全历史发现 + 已配置范围的年度区间。2012-12-07 是发布日，不能据此断言第一条历史观测。 |
| [gz_index](https://tushare.pro/document/2?doc_id=174) | date | 官方不限，报警 10000 | 2000 | 无过滤全历史发现 + 已配置范围的年度区间，非每日更新不能由空日推断缺损。 |
| [us_tycr](https://tushare.pro/document/2?doc_id=219) | date | 2000 | 120 | 年度区间；`m4` 自 20221019 起，其此前空值正常。 |
| [us_trycr](https://tushare.pro/document/2?doc_id=220) | date | 2000 | 120 | 年度区间；实际利率允许负数。 |
| [us_tbr](https://tushare.pro/document/2?doc_id=221) | date | 2000 | 120 | 年度区间；`w17_bd`、`w17_ce` 自 20221019 起。 |
| [us_tltr](https://tushare.pro/document/2?doc_id=222) | date | 2000 | 120 | 年度区间；`e_factor` 允许为空。 |
| [us_trltr](https://tushare.pro/document/2?doc_id=223) | date | 2000 | 120 | 实际长期平均利率，年度区间，允许负数。 |

期权交易所按 [官方映射](https://tushare.pro/document/2?doc_id=157) 使用 SSE/SZSE/CFFEX/DCE/SHFE/CZCE；仍保留无过滤请求以发现新增场所。来源的代码后缀和期权标点只在供应商边界使用；内部标准化由父任务按资产类型处理。黄金 `Au(T+D)`、`Au99.95` 等不能套用股票后缀转换。

[权限总表](https://tushare.pro/document/1?doc_id=108) 与期权明细的积分阈值不一致，契约采用对应明细，并全部保留 `permission_status=unprobed`，实际结果由云端能力记录决定。总表说明 LIBOR 历史始于 1986 年、HIBOR 始于 2002 年，因此默认查询下界分别为 19860101 和 20020101；这只是整年边界，不能证明各币种/期限的首行日期或未停发。其他历史首日没有可靠说明，不从示例、指数发布日期或当前最早样本推断完整性。

## 易漏字段与量纲

- 原 catalog 对数字开头字段有遗漏，显式补全 LIBOR `1w,1m,2m,3m,6m,12m`，HIBOR 另有 `2w`。不是这些列不存在。
- FX 日线的默认隐藏字段 `exchange` 必须请求；基础信息的 `traget_spread` 是供应商拼写，不能自行改成 `target_spread` 后再请求。
- 期权保留全部 20 个基础字段，其中 `exercise_price/opt_multiplier` 是经过调整的值；观察版本与原始 PIT 值不能混同。`delist_date/last_edate/last_ddate` 不用于过滤历史发现。
- 上海黄金成交量按千克、成交额按元，属于双向计量，包含前一夜盘；不能使用股票手数或单边成交假设。完整基础元数据与 `settle_vol/settle_dire` 一并保存。
- 美国利率全部期限显式请求，包括新增 `m4/w17_bd/w17_ce`；实际/名义利率分 API 保存，不合并成一个序列。

## 调度约定

`iter_other_jobs(config, today, identifiers=None)` 输出既有形状 `{api_name, params, epoch, priority}`，不自行联网、写库或取 token。配置 `other_apis` 只接受显式已审阅 API；`other_history_start` 接受 YYYYMMDD 或 API 映射，其后才回退 `history_start` 与已文档化下界。未知下界时仍发最近七天与无过滤目录/温州广州历史发现，历史前缀保持 gap。

最近七天优先级 20、epoch 使用 planning_epoch，历史优先级 40、epoch 为 history。行情和期权上市发现按日；宏观按不超过一年的日期范围，每币种最多 366 个自然日，远低于文档行数限额，因此不需要逐日打数万次请求。每轮各 API 一个历史分区，惰性产出；无过滤与有范围发现是不同请求，消费层按键及观察时间读取。

`other_prerequisites(identifiers=None, enabled_apis=None, config=None)` 报告饱和依赖、未知历史前缀，以及配置晚于已知历史的裁剪风险。显式配置起点只是工作范围；即使选 19000101，也不自动证明更早没有数据。非空 identifiers 仅解除“尚未发现”的提醒，不证明全集齐备。

父任务接入时必须：

1. 注册 `OTHER_CONTRACTS`、`iter_other_jobs` 到 group `other`；提取 `opt_basic -> options`、`sge_basic -> spot_metals`、`fx_obasic -> fx_instruments` 的历次并集，包含退市合约和每日数据中新增代码。现有 identifier 验证/规范化需接受该资产格式。
2. 新 family 纳入权重、配置签名、镜像运行时模块及 schema/read-only store。先作有界真实样本、全部字段与持久频控验证，再启用历史计划；只读纯契约测试不等于已部署。
3. 目录/日数据达到阈值必须进入饱和状态。opt_basic 逐上市日可减少截断，但一日仍饱和时须验证 exchange/opt_code/call_put 分区；当前模块不虚构通用日期 split 或分页。opt_code 是 `OP+期货合约代码` 的输入语义，不能直接拿输出值假定可用。
4. 只有完整目录证明后才能把按代码扇出的结果算作完整；新的场所、退休品种、未知历史界限和无法分页均记录缺口。上游缺失、空响应、未权限通过不可解释为供应商历史为空。
5. 保留历史修订；近七日刷新不是全部存量修订检查。年分区饱和时复用日期二分，单日饱和与异常重复键仍需质量处理。

## 验证

`python3 scripts/test_tushare_other_contracts.py`：6 项离线测试通过，覆盖 15 接口的 catalog/隐藏字段、五币种、全目录请求、逐日与年度闰日精确覆盖/无区间重叠、未知首日/范围裁剪提示、特殊代码与错误输入、惰性历史规划。LIBOR/HIBOR 从默认文档年到 20260909 合计少于 300 次规划请求。Ruff 格式与检查通过。没有生产请求、部署或权限实测。
