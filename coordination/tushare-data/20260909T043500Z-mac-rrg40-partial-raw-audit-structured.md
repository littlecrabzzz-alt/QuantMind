# RRG40有限落盘核查：2完成 / 38待响应

structured/Mac，只读结束；复用RRG111 verifier到/tmp新文件，既有cloud-compose quantmind python3 -S业务入口，socket/DNS禁止，SQLite mode=ro/query_only与限时精确主键查询，不调Tushare/发布/改DB配置/重新提权，也不等待40完成。

- 准备文件SHA `71bcb2332d83eff05b8841d74274d7766ac47913e2f43f8c52d19d230f759a7c` 与committed收据仍一致。04:34:08.776652Z读事务：40job精确full job/logical/epoch/group身份相同，2done +38pending。最初短状态读取1done；随后独立原始证据事务已进至2done，这是正常采集推进，不将不同读时刻混为单快照。
- 两次新响应均sample_ok、0空/0失败：daily20250930为5423行、13源列；adj_factor20250930为5437行、3源列，总10860源行。全部6raw/obs/Parquet SHA正确；观测params/fields一致，实际日期偏差0/空代码0；全部源列/null、规范码/source_ts_code、完整源行_row_identity、fetched_at/observation逐行对账差异0。SSE固定日历该日开市。其余38无attempt，不算已下载。
- 云端固定版 `data-8f9d1c65c7ae3199fd25923ace44c4c9e841226ff3c5cc689fc9c1c284eee304` 尚不包含这2观察的6文件。依任务要求，完整40固定reader对账为deferred_until_all40_responses_and_fixed_publication，未把未发布原文算入固定版。
- Mac现成固定版 `data-41d91a26636bde7c6c83020e36671e012aa845af1c2ea8e07f6772aae9f80435` 独立只读manifest校验亦不含全部6文件；未触发mirror或修改CURRENT，不能称新增2响应已到Mac。
- 云报告 `/tmp/tushare-rrg40-current-evidence.json` SHA `f91fa69e73a363542cbfdd7628df2ff133c12755e1f85ad2c4976a830c252ac9`，含完整40状态、2次原文路径/SHA、字段/空值/行身份对账及源文件指纹；helper `/tmp/verify_tushare_rrg40_current.py` SHA `b9de1eda8e9bc6b4e4e109b9f610202dcd278ba8e2aab9298ca7b460b5c2499a`。云验证3.116秒。
- Mac闭包报告 `/tmp/tushare-rrg40-mac-current-closure.json` SHA `3ef335d3aaf594316e0eff42f9d1b852921e36c5e42441db2bca58e78ed06d3f`；仅6文件清单查询，不重做全量验收。
- 下一步由正常采集/自动发布继续；后续固定reader预期必须使用全部对应API分区中的旧probe/修订，不能只按40目标原文假定无其他版本。本次不改变研究文件/gates；20260831单点底数、完整240交易日日历骨架/成员PIT仍是边界，非全部RRG历史。归属释放。
