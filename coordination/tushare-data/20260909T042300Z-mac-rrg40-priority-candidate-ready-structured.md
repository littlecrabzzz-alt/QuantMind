# RRG40有限优先级提升候选（未执行）

structured / Mac，接续041731Z最小数据审查。仅/tmp helper/test/handoff与本条；未改仓库runtime或生产设置、数据/优先级，未采集/发布/镜像。

- root授权准备的40个已存在history任务，严格完整job digest/id/logical/params/fields/epoch/group核对后，仅pending/tries0/resultnull/无attempt/retry_after0/priority45→24。已消费/优先级或gate变化保留跳过；缺job或身份不符整批回滚。无新增job、无state/reset/cursor/config改变。
- 复用RRG111 authority + pipeline.lock + BEGIN + prepared/committed证据模式；直接现有mode=rw SQLite，要求schema6、不构造Pipeline。SQL authorizer仅允许jobs.priority变更；config及planning/scheduler前后全量快照SHA相同才提交。secret/network禁用，40主键查与attempt索引，不全扫描。Python3.10 authorizer清理用显式allow回调，避开None清理兼容问题。
- 候选 `/tmp/tushare-rrg40-priority-candidate.py` SHA `4dbe25d19a1d0700618f9479e4990cd7556e5aa7cc37ef8386f4c3c8eb75fdc0`；stdin-safe wrapper `/tmp/tushare-rrg40-priority-cloud-run.py` SHA `fc567de7feab81af02d2a56b239de4d9f044fd69faae08bf6fecb3fd1a754944`。
- 10项隔离测试Python3.10通过0.066秒：正常40与幂等、已消费/重试/已高优先保留、旧attempt保留、身份错/缺job、写准备失败/配置竞态回滚、schema旧版拒绝、越权trigger拒绝、busy lock不变。测试/tmp/test_tushare_rrg40_priority_candidate.py，日志同名.log；全部临时DB无生产。
- 详细命令和SHA在 `/tmp/tushare-rrg40-priority-handoff.md`；默认仅plan，不访问authority。root审核后自行经既有cloud-compose业务入口执行，忙立即exit3，无自动等待/暂停队列。prepared并非commit证据；postcommit收据写失败必须按40主键确认，不能谎称回滚。
- 单点20260831扩散底数，不改研究文件/准入，不证明PIT；完整240交易日索引、成员历史known_at仍缺。交接就绪，执行权交root，归属释放。
