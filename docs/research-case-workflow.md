# 研究案例登记与数据准入

用途：把来源、固定方案与可复查数据检查连接起来。流程为**登记来源 → 冻结方案 → 数据准入 → 实验 → 独立复核与状态回填**。当前 `scripts/research_case.py` 只实现前期登记/检查及完整性核验；没有 RRG 回测、平台模型注册或交易执行。

## 登记与检查入口

默认合同 `config/rrg_sector_rotation.json`，默认目录 `data/research_cases/rrg-sector-rotation`。来源方法与版本见[2026-09-05 RRG 笔记](2026-09-05-RRG行业轮动研究笔记.md)。脚本会复制合同指定的笔记，保留这个路径是运行需要，不是重复文档入口。

在有对应数据的实际运行根执行，不自动跨节点迁移：

```bash
python3 scripts/research_case.py register
python3 scripts/research_case.py check
python3 scripts/research_case.py status
python3 scripts/research_case.py verify
```

另建合同或修改规则必须使用新目录：

```bash
python3 scripts/research_case.py register \
  --config config/rrg_sector_rotation.json \
  --output data/research_cases/rrg-sector-rotation-next
```

后续 `check/status/verify` 使用相同 `--config`、`--output`；合同必须与登记时一致，不能用新配置覆盖旧案例。`check` 返回 `2` 表示检查已留档但数据未准入，不等于运行异常；自动化应同时读取报告状态。结构检查即使无缺口，也只进入 `awaiting_data_review`，当前实现不会自动判为可实验。

## 数据准入合同

| 层次 | 实验前必须证明 |
| --- | --- |
| 行业信号 | 分类版本与完整行业名单；指数/基准日历对齐，价格有效，代码/日期唯一，预热与比较区间足够 |
| 扩散度 | 每个历史时点的成分归属可知，个股价格可比且覆盖回看期；市值加权另需当期可得市值 |
| ETF 执行 | 历史产品池、上市退市/可交易状态；持仓公告可得日期；成交开盘价和估值收盘价的复权/权益口径一致 |

`220 / 60 / 20` 采用两层完整滚动时，首次有效 Momentum 需 319 个价格观测，即 318 个预热间隔；预热充分不等于比较期已覆盖。当前成分、ETF 名称和无日期持仓不能证明历史暴露；报告期不等于公告日，未披露部分不能放大成完整组合。

自动检查覆盖文件、字段及部分取值，不能证明全部历史分类、PIT、价格和执行语义；未知必须保留，不以字段齐全宣布准入。数据不足只登记缺口，不推测策略收益。既往检查的 `blocked_data` 是当时留档状态，不能替代当前输入复核。

## 记录、状态与回填

- `case.json`：来源与登记清单；`registration/`：冻结合同、来源/评审及笔记副本；`state.json`：阶段。
- 每次 `check` 创建独立 `checks/` 目录，保存输入、报告、代码、运行信息与哈希清单；补数据后重新检查，不覆盖旧缺口。异常保留失败目录，不提升为完成记录。
- `workflow_stage`：`registered` → 有缺口 `blocked_data`，无结构缺口 `awaiting_data_review`。
- `learning_status=candidate_experiment`；`evidence_level` 从 `source_review` 到 `local_data_audit`；三层 `readiness` 仅 `blocked/needs_review`。
- 单项 `passed` 只表示该结构项通过，缺口 `blocked`、语义未证 `unknown`；`latest_check/completed_checks` 指向完成记录及清单哈希。
- `local_reproduction` 与 `automatic_trading_authorized` 当前保持 `false`。

回填索引 `data/research_watch/research_case_state.json` 供采集报告关联最近案例状态。来源版本和阅读评审仍由 SQLite `entries/versions` 与 `digest_state.json` 保存；阅读过不等于复现过，采集报告也不会自动重验数据或提升案例等级。`verify` 证明已保存材料完整、一致，不证明数据准入或投资价值。

## 真正执行实验前

先补齐与 RRG 对应的信号及执行工具，再按[冻结研究合同](frozen-research-workflow.md)固定真实数据、代码、环境和未见验证范围。现有 `frozen_research_worker.py` 是个股 LightGBM / TopK、次日收盘执行，不能换配置就称为 ETF 月末信号、次日开盘适配完成。

在相同数据、资金、费用和执行下先比较等权、简单动量、纯 RRG，再逐项加入扩散度或 ETF 暴露优化。区分行业信号诊断与可交易组合收益，核对实际日期、信号可得时点、成交、持仓、现金、费用与净值后回填采用/暂缓结论；不因来源已评审或哈希通过自动推进。

修改案例工具后可运行 `scripts/test_research_case.py` 的临时目录用例；不借文档检查启动真实 `check` 或回写业务进度。
