# SQLite v4 父子分区闭环可集成

- Mac / text_contracts，独立codex/tushare-text，先合入master39fff3d。delta提交1a7be56245a12e9d33fcacbfceeefb6c04e1bbe3，只有backend/shared/tushare_pipeline.py和scripts/test_tushare_partition_closure.py。接续182945 partition-closure-start记录；pipeline已释放给父。
- v4新增partition_splits/partition_children与查询索引。日期二分覆盖证据+精确父子关系持久化，重复请求幂等，嵌套由子向父闭合；reconcile每轮1000父预算与持久游标，失败后可重试/重启续算。
- 只有子done+sample_ok+持久Parquet或已resolved子，且父覆盖范围已证实，才resolved。empty_unverified、quality、权限、missing artifact/child、universe未知保持gap；子证据失效向祖先撤回resolved。原始满页attempts不删除。
- v3仅能根据日期参数、完整请求合同、epoch唯一匹配两子时恢复；不猜fanout名单，其他legacy_relationship_unverified。迁移创建与恢复在事务内；v1/v2迁移保留旧jobs/attempts/gates。
- manifest新增partition_closure证据/关系，resolved父不再列open gap；history_complete仍false；普通分页语义未改。本批未碰registry/store/mirror/API/配置/原其他tests，未生产调用/部署。
- 验证新10、原pipeline12、global7通过；extended原8中的迁移测试固定schema3，与v4不匹配（v1/v2两个子断言失败）；仅内存改该1行期望4后8全过，无磁盘修改。Ruff、diff check通过。
- 父cherry-pick delta后需将scripts/test_tushare_extended_pipeline.py:506的user_version期望3改4，再统一回归和生产迁移；生产旧474个split_pending能恢复多少尚未实测，不承诺全部resolved。
