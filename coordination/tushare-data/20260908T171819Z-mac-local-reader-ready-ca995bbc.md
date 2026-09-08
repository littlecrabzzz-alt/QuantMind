# 固定 release 本地读取扩展完成：待集成

- Mac / text_contracts 第三子任务；codex/tushare-text @6d0671515e6135afa002b6dbda56ec532943b5f2；worktree /Users/lizeyu/.codex/worktrees/quantmind-tushare-text。接续 20260908T170907Z-mac-local-reader-start-28a303a8.md。
- 本提交只改 backend/shared/tushare_store.py、scripts/test_tushare_store_extended.py。已 cherry-pick 结构化 c108508/市场 e148006 获取契约，不编辑契约。主执行者只需 cherry-pick 本提交，前两契约已在其分支。
- 支持原 7 + 文本 9 + 结构化 26 + 市场 23，共 65 接口及 6 财务别名的固定本地 release；schema、字段选择、日期、内部标的、关键词、观察时间 as_of、limit 与流式原子 JSONL 导出。查询校验各选中 Parquet SHA256/大小，拒绝符号链接/未登记路径，禁上游回退和自动扩展加载；spill 在独立临时目录。
- 公共函数：dataset_schema(root,release_id,api_name)；read_dataset(root,release_id,api_name,**filters) -> Arrow；export_jsonl(root,release_id,api_name,destination,**filters) -> stats。filters 支持 fields/date_field/start_date/end_date/codes/code_field/keyword/keyword_fields/as_of/limit；as_of 必须带时区并在去重前筛选，业务条件在去重后筛选。默认保存所有 raw/source 字段，正文差异和原始行 identity 不误合并。
- 元数据：Arrow schema.metadata[b'tushare']、schema 和 export stats 都携带 release、coverage、history_complete、historical_versions_complete、upstream_calls=0 与观察时间不是 PIT 的说明。历史完整版本依赖 publisher；旧清单默认 False。月/季度日期筛选锚定该期首日，导出目标须在不可变存储根之外。
- 验证：6 项新测试（内含全部 65 接口+财务别名）在 DuckDB 最新版与最低 1.4.4 均通过；原 pipeline 8 tests 通过；Ruff、diff --check 通过。所有数据由临时 Parquet 生成，测试期间禁 socket/DNS，无生产读写。
- 下一步：主执行者集成本提交、保留 publisher 的所有历史观察分区，结合云端真实固定 release 验证 schema/筛选/导出及本地副本。主机尚未安装新全局依赖，测试仅用 uv 临时环境。
