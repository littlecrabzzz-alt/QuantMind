# 研究工作台运行说明

实现范围与设计见 [持续研究方案第 10 节](continuous-research-and-strategy-plan.md#10-产品化一个入口两种研究模板本地与远端一致)。当前版本为冻结八因子模板上的受控研究：策略更改特征子集或模型参数；方法研究计算受限因果公式并与原模型作增量比较。任意论文算法、外部数据下载和模拟交易不在本版本自动执行范围内。

## 准备与启动

先遵守仓库 `AGENTS.md` 的节点检查。研究复用现有 PostgreSQL、Redis 和计算镜像；独立 `research-worker` 只消费研究队列，不复制业务定时任务。输入复制到节点自己的 `data/research/inputs`，结果与合同位于 `data/research/cases`，生命周期保存在 `research_cases/research_windows`。

模型配置为私有 JSON，权限 `0600`，包含 `api_key`、HTTPS `base_url` 和 `requested_models`。Mac 使用 `~/.config/quantmind/glm-research-api.json`，云端使用 SSD 下 `secrets/glm-research-api.json`。Compose 只读挂载该文件。密钥不写入请求合同、Git 或页面。执行器使用供应商真实提供的 Chat Completion 接口；提供商工具使用资格仍须遵守 [GLM 验收记录](glm-research-validation-20260908.md)，技术连通不代表套餐长期接入资格。

准备已有且核验过的冻结模板（不是从正式数据库现场提取）：

```bash
# Mac 主工作树：已初始化 .local-dev 后
python3 scripts/prepare_research_workbench.py --project-root "$PWD" --node local
bash scripts/local-dev.sh start research
python3 scripts/prepare_research_workbench.py --project-root "$PWD" --node local --apply-migration

# 云端权威宿主：使用实际权威路径
sudo -n python3 scripts/prepare_research_workbench.py --project-root /root/data/disk/quantmind/project --node cloud --apply-migration
sudo -n bash scripts/dual-node.sh cloud-compose up -d --no-deps quantmind research-worker
```

首次迁移前 worker 不会宣称就绪；迁移是可重复的新增表操作。没有新增依赖时无需重建镜像。云端部署须避开活动研究；不重启 Tushare 或其他业务 worker。前端沿用现有 Vite 入口，进入 Alpha Research 的“研究工作台”。能力接口就绪后可直接点击两张卡片发起。

## 生命周期与证据

- 每个窗口最长八小时，默认两小时、最多两个候选。候选累计计数随课题保留；单课题最多十二次实际计算尝试。每节点同时一个重型计算，多个课题公平排队。
- 创建请求使用幂等键；继续同样幂等，只允许从课题最新的暂停/到期/取消/失败窗口续开。已完成课题可另建研究，方法产物可直接创建关联策略课题。
- 暂停完成当前实验后不再启动下一阶段；取消与到期必须观察到所属容器停止。容器内按绝对截止时间执行 TERM/KILL，即使队列服务暂时离线也有计算期限。
- Worker 重启后按数据库租约和固定容器名核对原执行。容器提交意图已存在而容器消失时保留证据、要求检查；不静默重跑。Docker 暂时不可达会重试；模型 429/503 按 Retry-After 退避。调用结果不明单独保留未知用量，不能虚记成功或零费用。
- API 和页面均绑定认证用户及当前节点。切换节点重新查询能力与列表；不同节点不自动导入课题。关闭页面不停止研究；本机休眠/关机不保证本地持续计算。
- 公式由受限 AST 解释，只有历史窗口、横截面 rank 和算术，无任意代码执行。保存真实因子值、分期 IC/Rank IC/覆盖、分层与相关性诊断，逐日仅用当日以前数据重算并对照批量推理。
- 三组组合使用同一股票池、资金、执行与费用规则；逐笔资金/费用/持仓独立复核。候选必须通过固定增量与稳定性门槛才能入选；双倍费用压力实验不得改变模型或信号。报告与下载核验文件哈希。

当前冻结测试区间已经用于开发比较；所有结果标记 `needs_independent_validation`，不称为独立样本外发现或真实收益。Token 可据接口统计，接口没有返回的货币账单保持未知。

## 验证入口

```bash
PYTHONPATH=.:scripts python3 -m unittest scripts/test_research_workbench.py scripts/test_agent_research_tool.py scripts/test_glm_research_runner.py
npm run typecheck --workspace=electron
# 单独创建名为 research_test 的临时 PostgreSQL，应用新增表 SQL 后：
DATABASE_URL=postgresql://.../research_test PYTHONPATH=.:scripts python3 scripts/test_research_persistence.py
```

第三项包含真实数据库并发幂等/归属/租约/恢复和真实 Docker 取消，拒绝使用其他数据库名。它不调用模型或正式数据。产品页面与真实模型的双端验收结果需另外记录，以上检查不能替代端到端完成证据。
