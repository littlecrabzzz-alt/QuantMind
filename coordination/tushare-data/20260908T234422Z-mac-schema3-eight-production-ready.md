# schema3和八接口生产闭环完成

- 运行f2cd52e，父验收台账/文档89db2e5；主线已快进。完整364 tests/Ruff、目录15定向checks通过。
- 双端handoff通过后只重启quantmind和两Tushare worker；meta1→3迁移备份420331520B，352512文档/412528引用/3465尝试全部摘要前后一致，便携全行亦一致。旧新API各9页通过。
- 新8API 6928行/91列raw-Parquet-API-Mac全部对账。固定data-1a593ee58c333ebb02b025b1529f342c914a82cf389ac7878eeb34c73f45d668，Mac130814files（补4141）verified，禁网禁凭据通过。schema3固定1d8dfc1b全行在Mac与云端DB一致，旧schema2仍可读。
- 已恢复全部专属消费者：acquire7b68c095-ba31-48d5-80b8-88d31446b6ac/documentsf85881ce-c050-44b2-9009-d6910b2d2dd1；US88fe98db-f897-42a9-932c-cc1a84860e10未动。正常325请求/115.710秒，publish12.562，failed_stage=null。
- 原12family历史进度保留；new_share无筛选2000饱和blocked不冒充完整；daily_info新SH_FUND_REITs保留；research_report真实file_name缺列已台账记录，官方示例仍支持故不删字段。详细证据docs/tushare-progress.md及/tmp/tushare-{eight-*,schema3-*}.json。
- 下一步：独立limit_extra cd1da8a+91fc460（43 tests）和challenge5246705（43 tests）审查/集成/真实验收；旧互联互通日期筛选/tmp/tushare-connect-legacy-filter-probe.py仍未执行；全目录263+13、全部历史/修订/文档及PIT/RRG准入不缩减。无剩余暂停队列，无本轮未结束远端迁移/镜像进程。goal持续active。
