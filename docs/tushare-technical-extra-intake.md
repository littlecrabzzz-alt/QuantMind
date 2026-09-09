# 技术指标、筹码与备用行情接入候选

基线 `8c2e938`，2026-09-09 官方复核。五个不同 API 均属于现有 263 基线，未注册；`stk_factor_pro` 不是 `stk_factor` 或 `pro_bar` 的别名。已在隔离候选注册纯合同、规划与固定版本存储，未修改完整目录义务、生产数据或配置，权限全部 `unprobed`；尚未 probe、启用或部署。

| 官方接口 | 全输出列 | 公开单次上限 | 公开权限/频率 | 历史范围 |
|---|---:|---:|---|---|
| [stk_factor 296](https://tushare.pro/document/2?doc_id=296) | 35 | 10000 | 5000 分 100 次/分，8000 分以上 500 次/分 | 声称全历史，无具体下界 |
| [stk_factor_pro 328](https://tushare.pro/document/2?doc_id=328) | 261 | 10000 | 5000 分 30 次/分，8000 分以上 500 次/分 | 声称全历史，无具体下界 |
| [cyq_perf 293](https://tushare.pro/document/2?doc_id=293) | 11 | 6000 | 5000/10000 分为每日 2万/20万次，15000 分不限日总量；每分钟未写明 | 2018 年起，首个观察日未知 |
| [cyq_chips 294](https://tushare.pro/document/2?doc_id=294) | 4 | 6000 | 同上日配额；文档写 200 次/分 | 同上 |
| [bak_daily 255](https://tushare.pro/document/2?doc_id=255) | 31 | 7000 | 正式权限 5000 分，接口频率未写明 | 约 2017 年中，明确部分早期日缺失 |

10100 分不等于已实测授权；独立权限是否另需开通未知。纯合同统一采用保守本地 30 rpm，后续仍必须服从共享账户/API gates 与实际返回限频。筹码两接口每日约 18–19 点更新，时区/可用性时间及订正历史未验证。

全部 **342** 列在模块 `_OUTPUT_TABLES` / `FIELD_METADATA` 中逐字段保存名称、类型、默认可见性、原始参数与语义，`field_gaps` 对每列保留实际返回/版本/可用时间待验证项。复核全部默认 Y，隐藏列表为空；每个 job 仍显式请求全列，不能用 `fields=''` 或部分列成功作为全字段验收，也不能拒收以后新增字段。完整表格和 HTML SHA 保存在模块；Mac 原始证据位于 `/tmp/tushare-technical-docs/{255,293,294,296,328}.{html,json,txt}`。

## 规划与后续接线

导出 `TECHNICAL_EXTRA_CONTRACTS`、`iter_technical_extra_jobs(config,today,identifiers=None)`、`technical_extra_prerequisites(...)`。group/开关为 `technical_extra` / `enable_technical_extra`；配置 `technical_extra_apis` 与 `technical_extra_history_start`（字符串或 API 映射，回退 `history_start`）。运行 registry 适配逻辑 `stocks` 至独立 `technical_stocks`，不会改变其他 family 的标识集合。

五接口输入均为字符串 `ts_code/trade_date/start_date/end_date`；仅 `bak_daily` 另公开字符串 `offset/limit`。筹码两接口 **必须 `ts_code`**；专业版必须 `ts_code/trade_date` 至少一项，其余两接口没有已公开的必选项。不能把筹码请求变成无代码全市场请求，也不能以专业版裸日期范围替代合法请求。

近期 7 个日历日按真实 `trade_date` 生成，筹码逐股，其余全市场；API 间逐条轮转，近期结束后才历史。筹码历史按月、每只股票生成合法范围，首尾截断，日期轴仍为交易日；其余 API 历史按精确日。筹码采用 20180101 年份包络，不能宣称该日有数据；另外三接口无默认历史下界，缺显式范围只生成近期并保留 gap。全量历史股票、退市/T 代码及来源观察发现仍需补齐；不按当前股票列表或上市日裁掉旧身份。没有 stocks 时筹码阻塞但其他三 API 继续规划。

复用日范围二分与 `stocks`/`ts_code` 饱和维度。自然键是 `ts_code,trade_date`，筹码分布再加 `price`；保留不同源行及原始代码，不能按股票日期压成一个筹码档位。任何单股单日满上限仍须阻塞。其他四接口没有公开 offset，不能因为文档泛称分页便伪造；备用行情确有 offset/limit，但排序、默认值和跨页稳定性未实测，本候选仅存 `documented_pagination`，不提前开启运行分页。月窗实际过滤/返回量和拆分须后续有限 probe；模拟请求数不等于真实加速。

## 研究口径与未闭合事项

- 普通技术指标使用前复权，文档描述历史快照与最新日锚点，并指出与 `pro_bar` 的 end_date 动态复权可能不同。专业版没有继承该快照保证；bfq/qfq/hfq 各列都保留，不以本地算法覆盖源因子。
- 专业版 `bbi_bfq/hfq/qfq` 的 M4 原文分别 20/21/22；`kdj_bfq/hfq/qfq` 未明确标 J；`pre_close` 可能对不上前日 `close_qfq`。这些字段单列 gap，不能统一参数或据邻日修值。其余指标的种子、预热、缺失日、舍入和完整公式未获证明。
- 技术接口成交量为手、金额千元；专业版股本万股、市值万元；备用行情内外盘为手、总/流通股本为亿股，而其 `vol/amount/float_mv/total_mv` 单位未明确。保留原单位和空值，尤其亏损 PE，不沿用主行情倍率。
- 筹码来自社区模型估计，不是持仓账户事实。衰减、初始化、复权、历史高低价窗口、`winner_rate` 比例尺度仍有缺口；分布 `percent` 为百分比，但不能未验证就硬校验总和等于 100。
- 数据日与观察时刻分开。估值/行业归属/动态因子未证明当时可知，七日重刷不能证明旧修订或删除已覆盖。筹码/备用价格复权、币种等不明处逐列保留源值，不能直接当作 RRG 或完整 PIT 研究准入。

离线验证：`python3 -B scripts/test_tushare_technical_extra_contracts.py`，8 项通过；完整官方字段与保存目录一致、合法参数/所有列、闰月首尾无重叠遗漏、历史 T 代码、缺失依赖隔离、懒序列公平性；提取现有纯 `assess_response/date_children` 验证上限状态和筹码月窗 29 日叶分片。Ruff 通过。未调用 Tushare 数据 API、未执行生产或完整回测。


运行候选在 `07a7fde` 纯提交之后接入 registry、pipeline 发现/规划验证、store 与 mirror 安装名单。`technical_stocks` 合并已存 stock_basic、历史挂牌/退市/BSE旧新代码、龙虎榜/涨跌停/ST 股票，以及 daily/daily_basic/adj_factor 和本组 API 来源观察（含 saturated attempts）；不加入 ETF/fund 或概念指数目录，也不按当前上市状态裁剪。真正全历史主数据完整性仍是 gap，坏代码只阻塞本组。

读取默认日期均为 `trade_date`；`read_dataset`、`dataset_schema`、`export_jsonl` 使用实际返回全字段和现有自然键/`_row_identity`。原始负值、PE 空值、新增未知列、T 与复用普通代码、筹码同日多个价格档位/不同源行均保留；units/adjustment/formula/PIT/逐字段 gap 随读取元数据返回。此增量不改 SQLite/Parquet/manifest schema 或既有 release 含义，不迁移或重写旧文件；旧固定版没有本组分区时继续明确 unavailable，不能回源。`pipeline.__init__`、`next_job`、publish/interval 与其他 planner 均保持原实现。

运行验证：`UV_OFFLINE=1 uv run --no-project --with httpx --with pyarrow --with duckdb --with fastapi --with pyyaml --with reportlab --with pypdf python -B -m unittest discover -s scripts -p 'test_tushare*.py'`，**456 项通过，21.199 秒**，包含新增 6 项采集→normalize→publish→固定版读取测试，完整 342 列/未知列、历史身份与隔离、日期过滤/JSONL、旧版缺口、分片/满 cap 终端 blocked，以及全部 store 164 数据集夹具。日志仅 Mac `/tmp/tushare-technical-runtime-tests.log`；Ruff/diff 与 Pipeline 方法 AST 范围检查通过。未实测权限、月窗上游过滤或全历史完整性。


## 2026-09-09 生产与固定版样本验收

上述未probe状态为开发阶段记录，当前a68c6d9已部署并启用五接口。8次真实请求17338来源行、去重17202行，342显式字段全部返回；筹码单日与9月1—4日窗口、专业因子单股与全市场日请求三组全列比较通过。

固定cc8ed219…db55的全部相关来源/Parquet/实际reader行通过云端与Mac禁网验证。云端HTTP超过2000行的factor/pro/bak明确取SH600000单股范围，筹码全样本可覆盖；不宣称HTTP覆盖17202行全数据。Mac报告/tmp/technical5-mac-verified.json，原probe SHA8837a1ebabb9d36e3af49b7df9addc1f780637c7790066674234dda80a003b35。完整release与部署见tushare-progress 10:36记录。报告gap0仅指本次字段/过滤核验无差异，不取消上文单位、公式、来源全集、修订和PIT限制。history首批500项均跳过近期任务、新增历史0，长近期前缀仍待优化。
