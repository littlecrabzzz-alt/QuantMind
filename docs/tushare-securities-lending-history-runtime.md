# 融资历史三接口运行时

`slb_sec`、`slb_sec_detail`、`slb_len_mm` 注册于 `securities_lending_history`，复用现有队列、共享限速、历史游标、分区关系与固定 release reader。默认关闭，本次不改模板或生产配置，不等于已获账号权限。

启用时由权威节点明确设置 `enable_securities_lending_history=true`，可选 `securities_lending_history_apis` 和 `securities_lending_history_start`（日期或逐 API 映射）；后者缺省沿用 `history_start`，两者均未配置则请求范围从 `19900101` 开始。这只是请求边界：已保存官方目录标停更，最早日期、准确停止日期、当前历史可得性都未知，不能把1990或最近空响应写成完整性证明。

规划只依赖选定 API、请求范围及冻结日期。`stocks` 只用于饱和后的补分区，发现更多历史标的不重置该 family 的历史 signature/offset。来源为 `stock_basic` 及这三个接口已保存响应中的合法股票原码；不筛退市、不截掉 `T`，不拿基金或概念代码充当股票。异常代码仍保留原始响应并进入质量诊断，不能猜证券身份。

全部20个已知字段显式请求，非标识列允许 null，但“允许空值”不等于“允许漏列”。没有隐藏字段不代表未来供应商不会加列；capture保留未知字段。内部代码使用 `SH/SZ/BJ` 前缀并保留 `source_ts_code`。明细自然键包含 `tenor` 和 `fee_rate`，正文内容 `_row_identity` 进一步保留修订；重复观察相同内容在查询中去重，原始响应仍保留重复行。没有稳定供应商行ID，内容视图不能证明独立事件次数。

满5000行保守判为可能截断，实际cap尚未验证。范围请求先日期二分；单日全市场请求可由真实已发现/本次返回股票拆分，但 universe_complete 仍为 false。单日单股票满页没有已确认的 offset/limit/期限/费率请求参数，保留 raw、observation、Parquet 和 blocked 缺口，不伪造分页、不删除父证据。4000行本身不会按错误阈值触发截断。

`read_dataset` / `dataset_schema` / `export_jsonl` 可固定 release 按 `trade_date`、内部股票代码、字段和观察时间读取。股票源代码、未知字段、null及数值保留；schema metadata透传字段单位、停更、权限、PIT和饱和缺口。`as_of` 仅是本系统 `_fetched_at`，不是历史公开可得时间。数量单位万股、余额万元、费率百分数、期限为供应商字符串；不填零、不与融资汇总 `slb_len` 混用。

验证仅临时目录和 MockTransport：全列采集→规范化→固定发布→离线读/JSONL，多期限/费率/修订、历史T身份、旧release/as_of、游标稳定、日期二分/真实标的扇出、单股5000上限、权限错误/账户与API gates和缺列保护。离线测试不能取代后续有限历史真实probe与云端/Mac固定版验收；镜像安装清单已包含新纯模块。
