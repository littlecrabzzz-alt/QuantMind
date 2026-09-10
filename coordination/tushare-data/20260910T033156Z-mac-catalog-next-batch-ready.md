# Tushare：7 个旧 RRG 接口统一合同候选完成
- 时间、节点、任务标识：2026-09-10，mac，catalog_next_batch
- 状态：待交接
- 分支、worktree、提交：`codex/tushare-catalog-next-batch`，`/Users/lizeyu/.codex/worktrees/QuantMind-tushare-catalog-next`，候选代码 `de5106f0`
- 分工：本记录覆盖 `trade_cal`、`ci_daily`、`ci_index_member`、`etf_basic`、`fund_daily`、`fund_adj`、`fund_portfolio` 的合同、registry、旧 RRG planner 接线、store/query、Mac mirror 安装和离线测试。未改主工作树、配置、覆盖台账、凭据、上游或生产。
- 接续：`20260910T031803Z-mac-catalog-next-batch-start.md`

完成：7 个原来仅在 pipeline/store 硬编码的接口进入统一 registry；固定目录 7 份输入字段、62 个输出字段及 HTML SHA 逐项测试相等，所有目录输出列均显式请求。保留原有 RRG 自动规划和启用状态，没有新增 API 或扩大生产调用。`ci_index_member` 在合法 `ts_code` 维度、`fund_daily/fund_adj` 在合法基金代码维度补齐饱和拆分；旧行数上限仍标为未验证。固定版查询暴露默认日期轴、字段/历史/PIT/饱和缺口，并继续声明 `upstream_calls=0`。

启用与证据：这些 7 个接口已有 `ingested_partial` 仓库证据，因此没有把既有范围改为默认关闭；账户权限条款仍是 `unverified`，历史完整性、字段类型/修订语义、PIT 与供应商最大行数均未提升。账户组合 `p_list/p_get` 价值和复用范围较低且权限/分区未证实，本批未占用第 8 个名额；`p_save/p_delete` 继续排除写操作。

验证：临时 Python 3.10.19 venv，仅安装测试依赖；`python -m unittest discover -s scripts -p 'test_tushare*.py'` 为 885 项通过、跳过 5 项、43.848 秒。相关 43 项通过。`uvx ruff check` 对 7 个改动 Python 路径通过，`git diff --check` 通过。所有 HTTP 是 MockTransport；未读取 Token、未访问 Tushare、未接触生产。

真实验收要求：合并后先在不改变启用配置的固定小预算窗口核对 7 个 API 的返回字段全集、空值、行数上限/has_more 与现有分区恢复；尤其核对 ETF 三类 list_status、30 个中信一级成员/日线、基金日线/复权同日一致性、基金持仓 ann_date/end_date。只有真实证据才能更新 permission、字段类型、历史或 PIT 状态。

并行 follow-up：任务期间收到生产只读证据 `/data/tushare/validation/realtime-probe-20260910/probe.json`，SHA256 `62ee99ff5b802b29d05a019ad8e8f40bca106f18071c21b40f02caad2f1a93a9`。它仅证明 `stk_auction`、`rt_etf_sz_iopv`、`rt_idx_k`、`rt_idx_min`、`rt_sw_k`、`rt_fut_min`、`rt_k`、`rt_etf_k`、`rt_idx_min_daily`、`rt_fut_min_daily` 各自 `permission_denied`；集成人应逐项把这 10 个 API 的 ledger permission/status 与该证据关联，不能外推同族接口。本分支未改 ledger，避免混入未经本任务读取核验的生产状态。

下一步：推送候选分支，由集成人复核并合入 master；生产探测和部署另占共享服务窗口。
