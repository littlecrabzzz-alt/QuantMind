# 港股遗留读取兼容交接
- Mac remaining_markets，codex/tushare-other-markets；32b26c8a2bbcfe4eb728b2988d6e4ee420b1c470，worktree clean；接续20260908T190055Z-mac-hk-reader-compat-start-fb677396.md。
- 仅store.py九行视图projection和既有本人新fixture：只hk_*且ts_code精确五位!?\.HK转换为HK前缀，保留!，位于自然键去重与筛选前；source字段/原始Parquet/manifest/as_of观察语义不改，无生产请求。
- 8项other pipeline验收和ruff通过。旧后缀退市+新前缀退市+同号当前证券只返回两标的；codes和as_of得到正确新旧版本；旧固定release可前缀读，旧文件校验哈希不变。
- 额外既有test_tushare_store_extended.py为5通过1失败：唯一失败硬编码fixtures数量82，新增15接口后97。未越界改既有test，已通知父同步断言或改集合覆盖；这不作为全suite通过证据。
- 父下一步pick独立delta、更新固定数量断言，一并验收部署；pipeline.publish未触碰。
