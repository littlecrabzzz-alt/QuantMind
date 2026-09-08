# 结构化子任务：26 契约与完整目录台账待集成

- 节点/任务：Mac / structured_contracts；状态：子任务实现完成，待主任务集成与生产实测。
- 分支/worktree：codex/tushare-structured / quantmind-tushare-structured；提交 `c10850873e16e2ca0e6be7790855122cac3365bb`。
- 接续：20260908T164603Z-mac-full-goal-start-a35bc190.md；方案 docs/tushare-integration-plan.md。
- 文件归属仍仅 backend/shared/tushare_structured_contracts.py、scripts/test_tushare_structured_contracts.py、docs/tushare-structured-intake.md、config/tushare-coverage-ledger.json。

新增 26 端点纯函数请求计划；股票 5 状态 × 3 交易所、全 7 指数市场、三大表 12 报表类型、宏观/利率数字字段补齐。263 个目录项都有状态与下一步，2 个账户写操作明确排除，权限均不凭积分推断。
验证：4 项离线测试通过，Ruff 检查通过；未读凭据、未调用账号 API、未写生产数据或部署。
待集成：主采集器处理 VIP catalog_api 字段别名、饱和后完整股票枚举扇出，再日期细分；fina_indicator 的日期是报告期，其他财务是公告期。stk_limit 标的包含 A/B 股与基金，不能只用 A 股做完整性声明。未知 cap、SW 行情、旧财务迟到修订作为非阻塞缺口保留。
下一步：主任务 cherry-pick 该分支提交，云端真实验证、持续采集与 Mac 全文件校验，运行证据更新台账。
