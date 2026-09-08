# family 规划进度修复候选交接
- Mac remaining_markets；独立分支 codex/tushare-planner-progress，基线50ee715，单独增量提交 `17e23320eb70afb17745d7c3c692b40e53e148f9`；待父review/集成，未部署。
- 接续 `20260908T220403Z-mac-planner-progress-start-c3b60f62.md`；只改 tushare_pipeline.py 的规划helpers/plan_extended，新增 scripts/test_tushare_planning_progress.py。未碰publish、数据、配置、运行任务或密钥。

实现：按 family 的 selected contracts 与实际相关 config 子集计算policy哈希。发现依赖取纯planner实际使用的 contracts.dependencies，补 legacy structured 的 namechange→stocks、index_daily→indexes；saturation-only全集不影响纯生成序列，由既有date_children继续使用实时发现。PCF新增/变更、HK/期权新代码不会重置无关家族。没有丢掉 market 的 funds/indexes/bonds/sw_l3 等直接依赖。

现有 planning_state.signature TEXT 改为 version=1 JSON：仅保存policy哈希、必要发现集合、refresh、epoch；不存完整合同/config/无关标的，不新增表/迁移schema。不改变job键或旧成功状态。legacy标量signature首次安全重扫一次。其它运行代码对signature无hex/长度假定；publish仅透传，因此每次manifest仍会携带必要近/史发现快照，会增加一些元数据体积，本候选已按依赖裁剪但未声称零增量。

未完成近/史扫描都固定发现、日期anchor与epoch；仅集合增长或跨日/周/月不会打断。完成后发现变化启动下一轮同family历史补扫，用稳定job键跳过已存在任务；近期扫描独立先完成并按最新发现补扫，不等待历史扫完。近期及时性边界是“当前有限recent扫描结束后的下一轮”，不是发现当tick立即全覆盖；配置/合同持续被人为修改或validation_blocked仍可阻止进展，不能承诺固定墙钟时限。落后超过6天时recent按重叠6日窗口追赶，避免直接跳today而漏中间日期。global周/月历史在一轮完成后按新的闭合周期补扫，沿用合法日期轴。

新增统计 new_jobs / existing_jobs / skipped_recent / reset_reason / discovery_refresh_pending，旧planned字段仍表示枚举消耗量，不能再误当新增任务数。islice(offset)重走前缀的CPU开销仍存在，此候选解决的是无关失效/增长饥饿，不宣称已消除所有规划成本。

验证（全部隔离临时SQLite，无网络/密钥/生产数据）：
- `UV_OFFLINE=1 uv run --no-project --with httpx --with pyarrow --with duckdb python -B scripts/test_tushare_planning_progress.py`：10通过，覆盖无关PCF/发现/config变化、选中/未选合同变化、持续增长下旧尾部和新代码历史/近期最终覆盖、重启恢复、跨年anchor、长扫日期无洞、真配置变更幂等、旧签名安全接续、真实依赖映射。
- 同一运行环境 `python -B -m unittest scripts.test_tushare_extended_pipeline scripts.test_tushare_global_pipeline scripts.test_tushare_other_pipeline scripts.test_tushare_credit_pipeline scripts.test_tushare_extra_pipeline scripts.test_tushare_equity_event_pipeline scripts.test_tushare_etf_basket_pipeline scripts.test_tushare_tick_timing`：52通过。
- 从 `git show 50ee715:backend/shared/tushare_pipeline.py` 提取原plan_extended，仅临时替换该方法重跑3个专属回归；3/3实际复现失败（跨family重置、增长饿死尾部、跨年anchor重置）。候选对应3项通过。
- Ruff和diff检查通过；worktree只提交上述2文件。

后续：父下一轮review后按正常专属worker自然排空/一致版本发布，避免新旧planner同时轮流覆盖signature。无schema迁移，但旧程序恢复会把JSON当不匹配而安全重扫，进度会再损失；jobs成果仍保留。未知历史、权限、split closure、附件等完整性门槛不因本吞吐修复解除。
