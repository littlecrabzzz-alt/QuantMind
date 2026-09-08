# Global family 管线集成已提交，释放文件

- Mac / text_contracts，独立codex/tushare-text，提交0b4761368c57101d6da23e92a685bc9da065803c。父可仅cherry-pick该delta，先决契约1d87b23；merge651da24只用于本隔离worktree合入master，无需pick。
- 接续20260908T180200Z-mac-global-pipeline-start-1b195b11.md。仅registry、pipeline及新test_tushare_global_pipeline.py；未改verify_data/publish、mirror、生产配置或共享master。
- 注册global17类；发现hk_stocks/us_stocks合并jobs+attempts，保留旧名单/退市原始代码；归一化HK00700、USAAPL、USBRK.B及指数前缀，保留source和原始rowhash。分页优先于大规模标的fanout；非分页满日按完整发现范围拆分并持续标universe_complete=False。
- global_history_start/global_apis进入持久规划签名；显式1990范围仍写unknown_history_bound到既有capability，发布可携带；非空标的列表不证实发现完整。
- 父追加需求已做：enable_documents始终register_documents，document_execution=worker跳过inline run_documents，其他值保留原inline默认。
- 验证35项通过：global pipeline7、global contracts9、extended pipeline8、pipeline11，Ruff和diff check通过。仅临时目录+mock网络，无生产请求/凭据/部署。
- registry/pipeline/新测试文件已释放给父做后续集成优化。store KEYS尚未注册global（不属于本轮文件），父后续接本地查询。父接手运行配置、权限探测、mirror runtime复制与部署。
