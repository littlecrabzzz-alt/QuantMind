# Mac Tushare 接线范围与 blocked 实时审计

- 节点：Mac 完整归档唯一写入者。审计全部只读，范围审计输出 `/tmp/tushare-scope-audit-20260918-v2.json` SHA-256 为 `c406349c03260af61a5702c5d67061cd6cee0d702d5b8d0b4941ed3d66546812`。数据库查询分别走 `attempts_discovery_api` 与 `jobs_pending(state=?)` 索引，没有全表扫描。
- 命名范围是 263 个基线页、25 个发现页和 2 个命名相邻义务，得到 250 个命名 API 义务。当前 247 个运行时可读，`registered_without_reader=[]`。未注册的 4 项为：`ggt_monthly`、永久排除自动化的写操作 `p_save`/`p_delete`、SDK 派生包装 `pro_bar`。
- `ggt_monthly` 仍是唯一公开只读合同缺口：当前官方 `https://tushare.pro/document/2?doc_id=197` 返回 `404, 文档不存在！`，已保留的真实 API 名请求返回 40101。在没有新权威端点、字段和合法分区证据前，不从 `ggt_daily` 自行聚合伪造供应商月度数据。
- 港/美股财务 8 接口的官方当前页面明确要求单独权限。2026-09-18 真实复查的 `hk_income`/`hk_balancesheet`/`hk_cashflow`/`hk_fina_indicator` 和对应 4 个美股接口全部为 `permission_denied`；因此 `enable_foreign_financial=false` 是证据驱动的停用，不是漏开。权限低频复查仍保留。
- 因子族保持启用：`factor_value` 有 `available/empty_unverified` 真实能力证据并以 `code_only` 模式运行；`factor_list` 最新复查为 `permission_denied`。历史/实时分钟线没有购买证据，`hk_mins`/`idx_mins`/`opt_mins` 及实时 ETF 分钟代表请求仍是真实权限拒绝，不启用全量回填。

## 871 个 blocked 任务

- 分类为 `possibly_truncated=858`、`api_error=11`、`rate_limited=2`。主要 API 为 `dc_member=621`、`moneyflow_dc=142`、`index_weight=91`；其余每项 1–2 个。
- `dc_member` 和 `moneyflow_dc` 父任务已从真实返回值生成数千个 identifier 子任务，但供应商没有独立全集证据，所以保留 `universe_complete=false` 的父级缺口。`index_weight` 91 个是单指数/单日仍饱和、且官方没有更细过滤或分页参数的任务；已有专用后代链，不重放饱和父任务。
- `npr` 两个是机构+精确秒级仍满500行；`share_float` 一个是单股+单公告日仍满6000行；均无合法更细轴。11 个 API 错误分布于已停用开户数据、影视/基金销售/TMT 独立权限接口；2 个分钟线限频记录是保留的权限探针证据。
- 因此当前 blocked 没有可以通过删状态、伪造分页或循环重试来合法闭合的项目。原始对象、尝试、子任务和缺口证据全部保留；若后续权限或官方合同变化，由低频复查/合同重评估路径恢复，不需要重建归档。

本审计证明当前可实施的接线与缺口分类已闭合，不证明历史数据已全部下载。结构化 pending、文档注册/下载/解析和正常发布仍在 Mac 持续运行。
