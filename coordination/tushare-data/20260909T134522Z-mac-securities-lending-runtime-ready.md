# 融资历史3接口运行时完成

text_contracts / Mac / codex/tushare-securities-lending-history / commit006b293。仅本批registry/pipeline/store/mirror接线47行、新pipeline专项、新运行说明及父授权store_extended计数212→215；配置模板/生产未改。未混开户2。父pick此增量即可。

family securities_lending_history默认关闭；真实股票发现仅用于饱和，未进入此family冻结policy。20列明确请求/未知与null保留，tenor+fee_rate+内容版本不合并，T源代码保留并前缀规范。缺列仍schema_gap；5000单股单日仍blocked且原文/Parquet保留，不编分页；4000不误判。stocks新增不重置未完成历史signature/offset；共用账户与30rpm API gate、权限状态原语义。固定release reader/JSONL/as_of、旧release不可读新数据及所有gap metadata通过。

验证：/tmp/quantmind-calendar-factor-test310/bin/python -m unittest discover -s scripts -p 'test_tushare_*.py' →638tests/36.307s/OK；7专项；Ruff/diffcheck通过。完整日志 /tmp/tushare-securities-lending-runtime-full.log SHA d590414555818f84b7ba9064967c7c5c00749a6552147e22d35bf425c7d6d795. 初次精简uv环境缺依赖与旧计数失败已用完整缓存Python环境及授权计数修正消除。

边界：账号权限/实际历史可得性/完整universe/停更端点/PIT待真实有限probe和云Mac固定版验收。本候选无source HTTP、0生产配置/DB/云写。主树新AGENTS42–112已重读，父占统一发布窗口。
