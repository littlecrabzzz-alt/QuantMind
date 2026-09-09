# 融资与开户固定版离线闭包

- 时间/节点/任务：2026-09-09 14:38 UTC，Mac，01a0817d-7378-7673-9b7f-59c302713981；状态：本批固定版闭包完成，完整接入目标继续。
- 分支/提交：父codex/tushare-data-intake 84590f6已push；master/origin/master与云Git经handoff对齐84590f6。主树其他研究修改未暂存。
- 固定输入：data-fc6747298150d36345c840839310d1819d977536a0253d17ecc9550d1db675c2；开户probe SHA fdbce952be53ad1573673b18abf6fcacf7c08f6c8988b41d02308a37ccdff778；融资probe SHA 2baf339ed9f7f9095c51ea0aeaa104dc1959e055574a072bf23246450026e502。

本批实际结果：融资3接口分别2254/937/131行；开户新接口2018年51行及20181228控制1行，旧接口返回api_error40101。所有成功源的已知列、未知列、空值、原始对象、观测、Parquet与固定reader已核验；不声明完整历史/PIT或旧接口原因。开户探测等待共享锁48.899秒后只发3次请求，没有重跑。

双端验证：Mac标准mirror verified，新增356/共380050文件。融资云/Mac完整JSON同SHA e506c27db21027fa9ba178c1872b1a8a8be541d8ab9f9eb98cb71594d8ade7f3；开户16个共同键一致，云SHA8953f49a512fb93e5c0426f8f3553b4d66bc78f06da13142990d1f65c5b5d2a6、Mac SHAddc25442ce05562727628512923f7dcf4f7517644924159c6526265435d24478，仅elapsed_seconds不同。所有验收upstream_calls=0。

不可变证据：/data/tushare/validation/intake-batch-20260909T141000Z 已含两份实际probe、云/Mac verifier和mirror-status；Mac工作副本在/tmp/account-history2-{probe,cloud-verified,mac-verified}.json及/tmp/lending3-{cloud,mac}-fixed.json。

月规划84590f6同时完成父审并合入master；只部署代码、默认daily不变，未执行旧游标迁移。下一步先完成严格plan-only迁移预检及发布路径优化候选审查，再选择不丢旧任务的生产切换窗口。实时/回放/自选组合候选继续并行，不等待这些缺口阻塞已可用数据。
