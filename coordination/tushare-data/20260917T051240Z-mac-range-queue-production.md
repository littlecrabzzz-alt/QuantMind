# Tushare 高扇出逐日队列改为股票范围任务

- 时间、节点、任务标识：2026-09-17 05:12 UTC，Mac，range-queue-production
- 状态：生产完成；本地全量归档继续补采
- 分支、提交：`master` / `8ea9761183b5ce6b41c6e1b114a36b59ad2a9bf8`
- 分工：本次只修改 `moneyflow_dc`、`dc_member` 规划及其正式队列；云端仍只读研究子集，不恢复全量采集。

本次完成：以停止时刻重新发现的 5,914 个股票标识，把两个接口 1,530,766 个开放逐日任务原子替换为 65,054 个股票范围任务。旧任务和分区证据保留为 `superseded`/`blocked`，352,355 条 attempts 与 349,023 个含结果任务在迁移事务中校验保持不变。生产收据为本地归档根目录下 `range-queue-migration-v1.fe70dc00416b40b00e0082e3f93f7f65b6df0d4a14632113182469b5c893dab7.json`，文件名哈希已核对，`upstream_calls=0`。

验证：74 项相关测试通过，Ruff 和 staged diff check 通过；12.7GB 生产提交后一致克隆的 `PRAGMA quick_check` 为 `ok`。恢复后真实采集轮 90.691 秒完成 342 个请求，实际账户上限 500 RPM，文档并行处理 240 条成功。其后独立查询确认 `moneyflow_dc` 范围任务 5 个完成、11,823 个待处理；`dc_member` 4 个完成、3 个空结果、53,219 个待处理；两个接口的旧开放逐日任务均为 0。

双端：handoff 通过，Mac/云端 HEAD 和 6,697 个源码文件摘要一致；云端读取模式为 `research-cache`、缓存 timer active、旧归档 `ARCHIVE_RELOCATED` 存在、legacy Tushare worker 为 none。没有重启无关云端应用服务。

下一步：Mac worker 按新范围队列继续全量补采；完整历史、历史股票全集和板块全集仍按合同保留未验证边界。数据库全量校验副本是临时文件，生产验收记录完成后可删除。
