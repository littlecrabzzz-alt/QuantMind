# 已启用数据组的近期与历史消费机会

2026-09-09 部署历史规划预算修复后的只读观察：technical_extra 冻结 signature 不变，history offset 从 7500 推进至 87737；五个 API 各入队 200 条历史，共 1000 条，均 pending、tries=0，attempts 关联查询为 0。同时有 8384 条 priority20 近期任务；历史 priority55 在其后。原因是旧 next_job 仅为 structured 使用 API 轮转，其余组仍优先级排序。修复规划并不等于历史已被采集。

本候选复用 schema6 的 jobs_ready_api_history 索引和现有选择器，为 PLANNERS 中配置 enable=True 的组增加同样的 API 轮转与每 API 3 次近期、1 次历史机会。epoch 精确等于 history 才入历史桶；桶内仍按 priority、rowid，空或冷却桶可借用另一桶。遇到 API 限流跳过该 API。请求失败也已消耗预留机会，避免反复重试占据同一机会。四次是可用 API 的选择机会，不是保证四次全账户请求或固定秒数。

外层 group_weights、account/API gates、最小请求间隔和配额观测保持原逻辑。跨组 fallback 根据实际被选组使用公平路径；rrg 保持原优先级路径。未知或未启用的新组维持原行为，不删除已有 pending。structured 旧版允许未启用时通过 fallback/无 rpm 入口公平消费，本候选保留此兼容行为与 _next_structured_job wrapper。

structured_api_turn:*、structured_phase:* 键完全不变。新组使用 family:<UTF-8组名hex>:api_turn:* / phase:*，hex 和冒号确保边界明确且 GLOB 无元字符；不同组即使有同名 API 也不共享阶段。新检查点与原 gate/family_turn 在同一事务提交，失败回滚。没有 schema 迁移、没有改 job 内容、state、tries、result 或 planning_state；原冻结历史游标继续使用。

验证包括 2 万条临时任务、五 API 各两轮 3:1、重开数据库、空 RRG slot 的 fallback、API 冷却和借桶、独立命名空间、失败消耗机会、提交失败回滚、组权重与 RRG 优先级、未知/禁用/无 rpm 兼容。两条选择 SQL 均 SEARCH 现有索引且无临时排序；40 次选择约 32 毫秒是 Mac 隔离夹具结果，不代表生产吞吐。原 structured 40 万行迁移与查询测试仍保留。Python3.10 测试故障注入后的 authorizer 清理由 None 改为显式 SQLITE_OK，保留故障与回滚断言。

本候选不增加账户额度，不证明任何接口权限、时间范围完整性或实际历史采集成功。上线后仍需独立观察 history 对应真实 attempt/raw/Parquet，不以入队计数替代成功采集。

```sh
PYTHONPATH=scripts UV_OFFLINE=1 uv run --python 3.10 --no-project --with httpx --with pyarrow --with duckdb python -m unittest scripts.test_tushare_family_fairness scripts.test_tushare_structured_fairness scripts.test_tushare_queue_indexes scripts.test_tushare_extended_pipeline scripts.test_tushare_technical_extra_pipeline scripts.test_tushare_history_budget
```
