# 六成员分区probe：review两项修正就绪

接044427Z候选；structured只改/tmp probe/test/wrapper/handoff，不改runtime/fixed verifier，也未生产执行。

- 开始时刻移到实际flock成功之后；原90秒执行预算与root bounded native lock wrapper等待时间分开。
- 同epoch已存terminal result先于本轮denied集合和cached capability denial判断，原observation不被后来权限缓存遮蔽。未尝试任务仍probe_prepared、无自动采集或enable。
- fixture在flock模拟等待200秒后仍取得6请求；随后两API都有later capability denial，同epoch重跑禁止token getter，0HTTP且6原observation/status相同。完整10项Python3.10隔离测试1.082秒通过，仍包含superset/字段/饱和/fanout/reader测试。
- probe `/tmp/tushare-member-partitions6-probe.py` 新SHA `010e7dad769396b8c0405ff28c6d46b3f16cf292ce6cf446c8b6136456a925ed`；wrapper `/tmp/tushare-member-partitions6-cloud-run.py` 新SHA `c4fcfc3d340fae2b8efae974d29253a5d3eb097a242280c62ade1b2c4501ec10`。旧SHA不再作为待执行候选。
- test SHA7801a143e77fc427a539518e7573e48c693ec9ec83567a63a12039a18cc5bc37；log SHA63939fb56876c49cfc9094ae3f4b2eea5466c837fe62d5de2920f02488e9dad2。fixed verifier仍原SHA0e68fe303a9ec8ad7a1cd753300a74b9aeca7dcc31f8894838f26a05dcb37cba。
- handoff `/tmp/member-partitions6-handoff.md`已更新。六scope、保留父饱和/全集/第二维/PIT/migration_needed含义均不变；root审核执行，归属释放。
