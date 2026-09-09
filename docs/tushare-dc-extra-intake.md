# DC 历史成分与行情两接口接入

本组接入目录 363/382 的 `dc_member`、`dc_daily`，生产已注册并启用。两项无待解释的 API 别名；仍保留固定263项目录与13项额外发现的完整义务，具体权限、样本和离线验收见下方记录。

| 接口与官方依据 | 合同要点 |
|---|---|
| [dc_member / 363](https://tushare.pro/document/2?doc_id=363) | 历史每日成分从 2024-12-20 起，单次 5000。完整输入 `ts_code,con_code,trade_date,start_date,end_date`；完整输出 `trade_date,ts_code,con_code,name`。 |
| [dc_daily / 382](https://tushare.pro/document/2?doc_id=382) | 板块行情从 2020 年起，单次 2000。完整输入 `ts_code,trade_date,start_date,end_date,idx_type`；完整输出 `ts_code,trade_date,close,open,high,low,change,pct_change,vol,amount,swing,turnover_rate,category`。 |

两页所有输出均默认 Y，无默认隐藏列；仍显式请求并校验全部 17 列，保留合法空值和以后返回的新列。两页列出 6000 分门槛，未说明独立权益或各接口每分钟/日调用数；合同初始权限为 `unprobed`，实际账户两接口已观察到可用；50 rpm 仅本地运行上限，不代替真实限额观测。

导出 `DC_EXTRA_CONTRACTS`、`iter_dc_extra_jobs(config,today,identifiers=None)`、`dc_extra_prerequisites(...)`；运行组 `dc_extra`，配置 `dc_extra_apis`、`dc_extra_history_start`（字符串或每 API 字典，回退 `history_start`）。默认采用各自文档起点；20200101 只是“2020 年”的规划边界，不宣称实际第一条日期。配置较晚起点继续记录早期未请求范围。

最近 7 个自然日逐日请求，历史按 API 轮转惰性生成；不以当前上市/板块集合过滤。行情显式覆盖“概念板块/行业板块/地域板块”三类，成分每天一次无代码过滤。`idx_type` 在官方输入表是可选，本组为覆盖策略而要求显式传入；返回字段名是 `category`，本次三类样本字面映射已经验证，历史及未来变化仍需观察。保持三类请求身份，不能用响应相同推断类别等价。未选择月窗：每日全部成员很容易触及上限，窗口变大可能增加二分探测开销，需真实样本后另评估。

自然键为成员 `(trade_date,ts_code,con_code)`，行情 `(ts_code,trade_date,category)`；都保留不同源行，行情再保留请求 `idx_type`。日期轴都是 `trade_date`。DC 板块 `ts_code` 保持来源原值和独立 `dc_indices`，不能套 THS 或股票标识；成员 `con_code` 示例包括 SH/SZ/BJ，仍保留源字段，未知跨市场形式不猜转换。行情成交量单位是股、成交额是元，不能沿用 THS 手数或其他 DC 万元字段。

运行中继续显式保留以下缺口：

- 合法日期范围可二分，单日可按 `ts_code` 分片；两页均没有 offset/limit 输入。发现集合应并入 DC 分类、行情、成员的历史原始观测，不能凭当前目录证明退市板块齐全。
- 成员单日单板块饱和后还可合法按 `con_code` 查询，但需要完整历史成员发现；现有单维代码拆分不支持证明这一层完整，必须继续 blocked。
- 每日历史成分确实比当前快照提供更多历史信息，但缺少当时公布时刻、成员生效区间与权重；不能造 `in_date/out_date` 或据此解除 RRG 的 `blocked_data`。7 日重叠也不证明旧修订、删除完整。

离线复验：`python3 -S -B scripts/test_tushare_dc_extra_contracts.py`，7 项测试覆盖官方列/参数、权限未知、类别请求身份、各自起点、跨年闰日覆盖、惰性轮转、配置校验；不导入 Pipeline、不联网、不访问生产。


## 2026-09-09 生产与固定版验收

- runtime e87dc2b 已合入 master/GitHub/cloud；425 项隔离 Tushare tests（12.886 秒）、Ruff/diff 通过。共154个采集API（147扩展+7基础）与6个查询别名，KEYS160；本次无schema迁移。
- 7个真实请求耗时6.447秒，显式17字段全部返回；dc_member总表8000行、三个实际板块10/12/16行，dc_daily行业/概念/地域496/504/31行，共9069原始行。source/observation SHA、Parquet全列、源代码/请求identity和日期过滤核对通过。
- 总表明确返回 has_more=true，且8000超过文档5000上限；它不是全量成员证明。BK1230.DC/BK0805.DC的22个成员不在总表样本，BK0162.DC的16行与总表重叠，读取正确保留22个新成员并折叠16个重复行。查询得到dc_member8022+dc_daily1031=9053行，未丢失不同原始记录。
- 实际三类日线的 category 分别与请求 idx_type 的行业板块/概念板块/地域板块相同，字段名称仍独立保留；此结论限本次样本，不能替代历史分类修订证据。
- 两接口已启用，近期28新任务，首次历史规划500项中472新、28跳过近期；原12个未完成其他history签名/offset保持。09:14运行观察：daily done15/empty9，member done21/empty1/split_pending6/quality1；总表饱和进入现有按日/板块拆分路径，单板块仍饱和时继续保留缺口。
- 固定版本 data-0a801f56529c55444386be12892cdaaa1d864c2aa64e4a5bef86ce0131897ad1：12次云端HTTP查询全列与独立raw/Parquet读取共9053行一致，匿名401、上游调用0。Mac新增9439、共180862文件校验；禁网/禁凭据同版全9053行、21证据文件SHA通过。两端精确probe报告SHA一致为39fe1e79049a0e5baab1e84c283673d684f5ad88eff3fdbf55fec42e8eccdd22。
- 云端证据：validation/dc-extra-probe.json、dc-acceptance.json、dc2-api-acceptance.json、dc-runtime.json；Mac /tmp/dc2-mac-offline-verified-20260909.json。固定probe版本为data-4f389ce821b5553fb80be36d47f307d2ed198943e41b1f08000b23637d9e0a43。
- 仅自有两个队列自然排空后发布，09:07恢复quantmind和两个专属worker；实际采集307246c7-ab6f-43f4-8128-4e96f5efc1d8/文档ed901c94-d40a-4551-a988-a40af379c1c7已确认，原普通US任务88fe98db保持。随后自动任务继续推进，不等待全历史才做固定验收。全历史、下线板块发现、修订及成员PIT仍未完成。
