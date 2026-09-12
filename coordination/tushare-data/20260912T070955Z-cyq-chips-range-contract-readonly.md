# cyq_chips 历史 range 请求合同只读审计

- 审计时间：2026-09-12T07:09:55Z
- 代码基线：`4911af05ffbe1d537709fed35a6def1fbb18f27d`
- 范围：官方 doc 294、本地 catalog/规划代码、已归档 post-deploy 审计、已保存 observation/object；未访问 Tushare、未打开或扫描生产 SQLite、未读取凭据、未修改服务或生产数据。

## 结论

`cyq_chips` 的 `ts_code + start_date + end_date` 是官方明确支持的请求形式，当前按自然月生成历史 range、仅在返回达到 6000 行上限时按日期二分的规划应保留。没有证据支持把历史规划改成逐日；逐日会把通常一个月一次的请求放大约 28–31 倍，却不能提高对“指定数据不存在”的语义置信度。

当前缺口位于 `backend/shared/tushare_intake.py` 的窄供应商空结果分类：它只接受精确的 `{ts_code, trade_date}`，因此同一已知业务码、消息和 `data=null` 出现在官方合法的 `{ts_code, start_date, end_date}` 请求时仍被标为 `api_error`。最小修复应扩展该 API 专属分类器，不改 planner。

上一轮保留的 range `api_error` 不能被解释为“无效请求”。它只是一个合法 range 请求的供应商业务响应没有命中当前过窄分类规则；既有 attempt/result/object/observation 应保持不可变。

## 官方合同证据

本地保存的官方页面 `/tmp/tushare-technical-docs/294.html`，SHA-256 `9012715db09bf099be50bbc6a6d31d3f322b3e039065fe304a4857ecc9d54863`。解析文本 `/tmp/tushare-technical-docs/294.txt`，SHA-256 `ea6d9e9d110ed6aeb08abc848384a85c5b091f92954e75c86d1e6f602f624641`。

页面的输入表明确列出：`ts_code` 必填，`trade_date`、`start_date`、`end_date` 可选；官方示例为 `pro.cyq_chips(ts_code='600000.SH', start_date='20220101', end_date='20220429')`，示例结果覆盖多个交易日。`config/tushare-catalog.json` 的 doc 294 条目也记录了相同四个输入字段及相同官方 HTML 哈希。

## 已保存生产证据

已保存成功 range 请求：

- observation：`observations/010cd6eb9d234eb7bae636424bbd74ce.json`，860 bytes，SHA-256 `bed371053cd48828214f48d9679e5316208add0c670e8b9a56fbefa08a4801ac`
- object：`objects/35ba773405d8c3042c7012f5eae2087b8af156a2f9c0394062f4ff7c76b5bb7e.json`，123425 bytes，SHA-256 与文件名一致
- 请求：`cyq_chips`, `ts_code=000001.SZ`, `start_date=20180101`, `end_date=20180131`
- 响应：HTTP 200、业务码 0、3586 行，`trade_date` 从 `20180102` 到 `20180131`，状态 `sample_ok`，明确请求字段完整，`supplier_has_more=false`

这一响应直接证明当前月度 range 几何能够返回多个交易日的真实数据。

已归档 post-deploy 审计：`validation/source-semantics-20260912/post-deploy-cyq-audit.json`，SHA-256 `495503b3c3fb46a7f2e029f786d91df42341b15b42264e1146eb7216d948d2c4`。其中 7 个首尝试包含 5 个 `sample_ok`、1 个精确日 `empty_unverified`、1 个未匹配的 range `api_error`。

未匹配 range 的精确证据：

- task/job：`8d98620659ec90a01a39c40c0ee1aa353cdd18bfaf2a7564a1379c7047ea5209`
- 参数：`ts_code=000522.SZ`, `start_date=20180101`, `end_date=20180131`
- HTTP 200，业务码 50101，消息精确为“指定数据不存在，请确认参数！”，`data=null`
- 状态 `pending`，`tries=1`，结果 `api_error`，`supplier_empty_hint=false`
- 原始 object：`objects/f046f7ef83c10b3500384f83e3ed94db2a9069970ec38756a109114908eed6dc.json`，SHA-256 与文件名一致

同一归档中，`000971.SZ + trade_date=20260903` 收到完全相同的 HTTP/业务码/消息/`data=null`，已被当前精确日规则分类为 `empty_unverified`、`supplier_empty_hint=true`，一次后终止。相邻的 `000968/000969/000970/000972/000973` 精确日请求均返回业务码 0 和 60–174 行真实数据。因此该窄语义应按请求合法形状扩展，不能通过全局消息正则泛化。

## 当前 planner 与最小修复

`backend/shared/tushare_technical_extra_contracts.py` 已把 doc 294 记录为：必需 `ts_code`、历史分区 `stock_calendar_month_v1`、range 轴 `start_date/end_date`；月度 planner 产出精确 `{ts_code,start_date,end_date}`。`backend/shared/tushare_pipeline.py` 在 range 响应可能达到 6000 行上限时使用日期二分，因此已有防截断路径。

最小修复限定在 `cyq_chips` 专属 supplier-empty 分类器：

1. 接受两种且仅两种精确合法形状：`{ts_code,trade_date}`，或 `{ts_code,start_date,end_date}`。
2. range 两端必须同时存在、日期规范且 `start_date <= end_date`；拒绝混合日期轴、单边 range、额外参数、无效代码或日期。
3. 继续同时要求 API 精确为 `cyq_chips`、HTTP 200、业务码严格整数 50101、消息精确匹配、显式 `data=null` 和合法证券代码。
4. 分类仍为 `empty_unverified`，保留业务码、raw object 和 observation，设置 `supplier_empty_hint=true`；`coverage_proven=false`、`history_complete=false`、`pit_verified=false`。不得把 payload 改写为业务码 0，也不得全局匹配该消息。
5. 不修改历史 planner，不将月度任务改为逐日，不修改既有 attempt/result。修复部署后，由有界正常重试观察同一合法 range：若仍返回同一精确空签名，则一次终止；若返回业务码 0 和真实 rows，则按真实数据保存。

## 合并前最低验证

- 正例：合法精确日与合法完整 range 的同一 50101 签名均命中；至少覆盖闰月/自然月日期。
- 负例：缺一个 range 边界、反向 range、`trade_date` 与 range 混合、额外参数、坏代码、坏日期、邻近消息、邻近业务码、另一 API、HTTP 429/500 均保持原分类。
- 数据正例：HTTP 200/业务码 0/真实 rows 不得被 supplier-empty 规则截获。
- pipeline：range hint 在修复后的下一次相同响应终止，不覆盖既有 attempt，不提升 capability 为 available，不再次重试。
- 回归：月度历史几何无间隙/无重叠，达到 row cap 的 range 仍二分到日叶；单股票单日仍达到 6000 行时继续保持覆盖阻塞。

## 语义边界

`empty_unverified` 只表示该证券和指定日期或区间收到供应商的明确无数据提示。它不证明该证券全历史完整、上市生命周期完整、PIT 完整或 RRG 可用。当前证据已经足以确认 range 合法，无需为证明合同再发探索性请求；部署验收只需观察有界正常重试和持久化不变量。
