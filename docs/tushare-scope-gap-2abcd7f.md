# Tushare 具名范围与运行时差集（父候选 2abcd7f）

离线复核，不查询 Tushare、云端服务、凭据或权威数据库。候选在独立 worktree 合入父 `2abcd7f`，本地 merge `0151450`；注册表/reader 与该父候选一致，独立因子迁移候选未改变接口注册。使用 ponytail 最小方案：复用冻结目录和已有合同，不为凑覆盖数新造接口。

## 分母与实现情况

| 范围 | 数量 | 含义 |
|---|---:|---|
| 冻结官方目录 | 263 页 | 原 index SHA `182240e4826c7e65a6b63ef83efdc4e14b7b3589a6249ed54cd36ac66c937dce`，不改基线 |
| 追加独立发现 | 13 页 | 总 276 页；42 页无可确认 acquisition API 名，分类/失效页义务保留 |
| 基线 acquisition 名 | 227 | 保留已有财报 VIP acquisition 映射，不重复计算 reader 别名 |
| 基线与发现页具名并集 | 234 | 原分母不消失 |
| 已确认独立邻接 API | 2 | doc420 `rt_idx_min_daily`、doc340 `rt_fut_min_daily`；不是同页实时接口的别名 |
| 全部已确认具名并集 | **236** | 不是未来范围上限 |
| 已注册且有本地 reader | **227** | 220 extended + 7 legacy；全部有 KEYS；只说明代码能力 |
| 仍未注册 | **9** | 下表分类，不把写操作/SDK/私有 API 算作公共行情缺失 |

KEYS 共 233，额外六项 `income/balancesheet/cashflow/forecast/express/fina_indicator` 是 reader 别名，不增加源 API 分母。不存在 registered-but-reader-missing 或未归入已确认范围的 registered API。

| 未注册项 | 类别 | 剩余事项 |
|---|---|---|
| moneyflow_hsgt / ggt_daily / ggt_top10 / ggt_monthly | 公共只读、完整合同阻塞（4） | 已保存官方正文均失效；默认响应不能证明隐藏字段、输入/续页、历史与权限 |
| p_list / p_get | 纯合同已有、私有组合只读（2） | `tushare_portfolio_read_contracts.py`；账户私有组合，不是公共市场数据，权限/运行接线未验证 |
| p_save / p_delete | 排除自动采集的写操作（2） | 不生成采集任务，不解除 mutation 边界 |
| pro_bar | SDK 聚合入口（1） | 不能伪造同名 HTTP 请求；底层来源、复权与历史对账义务保留 |

另保留原三条 unresolved mention：doc93 `index_member` 只有概览名；doc177“在岸人民币”无具体 API；doc18“私募基金”为未来范围。它们不被擅自加入可执行端点分母。原 `hk_hold`、`dc_concept_cons` discovery seeds 作为原证据保存，已具名/已注册，不再重复加数。

## 不因注册而清零的缺口

逐 API JSON 分开记录 implementation、历史 permission evidence、live enablement 未检查、合同 history/PIT/note/attachment/verified 元数据、已知缺列；完整原 ledger 的所有 status、next_action、capability/runtime/contract/正文证据原样嵌入，避免覆盖较早记录。旧 `implementing/unverified` 标签不能替代当前注册差集，也不能因代码已实现反推当下账户权益。

- 权限：独立分钟/新闻/文档等授权不从积分推断；本轮无当前配置/账户检查。
- 数据与字段：`research_report.file_name` 仍有两份真实缺列证据（1000 行范围和 85 行精确日期）；required 键齐不等于所有供应商字段已齐。unknown/null 源行义务不变。
- 历史与 PIT：请求 1990 不等于来源存在；当前成员/最新修订不能替代当时成员或 known_at；as_of 仍是系统观察时间。RRG 已通过切片不会在这里被冒充全历史。
- 原文与附件：注册 URL 字段不等于 PDF/HTML 成功下载或可解析；既有 challenge、timeout、权限和原文缺口保留，未重验全部附件。
- 实时邻接：已注册不等于已启用、已取数或可任意回看；独立权限、时点与夜盘边界按原合同保留。

## 下一批最小选择及明确阻塞

优先 `moneyflow_hsgt`、`ggt_daily` 两项：已有真实返回且对跨境资金背景研究有用，是 RRG 的可选辅助输入，不是其价格/成员/PIT门槛的替代。第三候选 `ggt_top10` 先解决合法输入。`ggt_monthly` 继续单列义务，不能用日线聚合冒充其供应商月口径。

本轮**不新增纯合同**。已有 bounded primary review 的 8 个官方 URL 结果为文档不存在/404，官方仓库树没有完整 schema；不是“没搜索所以没做”。本次只读取这些归档报告，并保存其 SHA 与报告内容。

| API | 归档真实结果（不是本轮新请求） | 最小所需证据 |
|---|---|---|
| moneyflow_hsgt | 20260904，1 行，7 默认字段 | 完整输入/隐藏输出、现行披露定义、历史/单位/cap/rpm |
| ggt_daily | 1000 行、has_more=true，20220526–20260907，5 默认字段 | 合法日期/续页机制；不能猜 offset 或把 1000 当已证上限 |
| ggt_top10 | 空参数 source 50101 | 合法必填参数与全部输出；不是权限拒绝证据 |
| ggt_monthly | 空参数 source 40101 | 官方当前有效名称及月度口径；不能断言永久停更 |

待官方恢复完整合同或提供可审计说明，才做纯规划及有限真实探测；不重复失效网页、不从第三方/SDK猜完整字段。本轮没有足够依据制作 1–3 个真正尚缺且公共只读的新合同。

## 复跑与证据

- [完整冻结审计](tushare-scope-gap-2abcd7f.evidence.json)：236 项、完整原 ledger、归档 Connect4 报告及所有合同输入源码 SHA。此文件是历史审计，不被之后运行状态覆盖。
- `python scripts/audit_tushare_scope_gaps.py --output /tmp/tushare-scope-current.json`：对调用时 checkout 重算，不访问网络或数据库。结果随后续代码变化，不自动覆盖冻结报告/共享 ledger。
- `PYTHONPATH=scripts:. python -m unittest test_tushare_scope_gaps test_tushare_catalog_review test_tushare_catalog_schema`：13 项通过，Python 3.10；含真实 CLI、分母去重、别名/邻接、未决提及、unknown 分类、缺 reader、不丢缺列与源 ledger、无网络调用测试。Ruff 通过。

较早 `5d442d3` 快照为 212 注册/234 具名；新增融资3+开户2+实时原8+邻接2 后为 227/236。分母新增与实现推进分别记录，不能只报百分比。
