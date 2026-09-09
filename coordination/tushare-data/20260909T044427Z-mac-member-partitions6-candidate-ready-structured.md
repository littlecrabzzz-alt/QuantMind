# TDX/KP饱和成员：6个真实板块分区候选就绪

structured/Mac，独立/tmp准备与测试完毕；未改runtime/配置/ledger/progress/研究文件，未上游请求/enable/生产写。

- 基于固定41d91a26636bde7c6c83020e36671e012aa845af1c2ea8e07f6772aae9f80435的7份源观察+原文逐SHA选码：tdx_member 880206.TDX/880208.TDX/880207.TDX（源10/85/486行，与同日index/daily交叉）；kpl_concept_cons 000366.KP/000173.KP/000226.KP（源7/50/347行）。统一20260904，只板块code维，无con_code。源证据 `/tmp/member-partition-source-selection.json` SHA a6372294ae75b80186547494543789ddae9388d0e46d527965380a3ee3682888。
- 发现TDX index613/daily616/member父19板块，KP父47板块，均不等于全集；没有已注册独立kpl_concept，使用实际kpl_concept_cons父观察而不猜API别名。
- 复用sentiment7 probe/fixed verifier缩为6请求/new epoch/90秒，保留原authority/lock/gates/quota/terminalcached/probe_prepared/raw/attempt，token延迟到真正需要请求；不切分/发布/启用。固定reader全部源列/unknown/null、TDX/KP与member源码、rowidentity，比较父已见subset⊆子，允许子新增；共同源行缺失或变化留gap。原父饱和证据不改。
- 10项Python3.10隔离测试1.333秒过（含多模式子测试与复用runtime6项）：MockTransport真实存储/reader、6上限、denied/rate/cached0重试、子超集/变化/缺字段/饱和、三板块fanout幂等且coverage0、单板块饱和不猜con_code第二维。
- Probe `/tmp/tushare-member-partitions6-probe.py` SHA97d0b5c8aee21cacc038e44d31887e2511c5a62b60b01388ac0e3f199413217f；stdin wrapper `/tmp/tushare-member-partitions6-cloud-run.py` SHAa515152fc3d170dcf77ecef636a7726d70527022a2dca50dd654fea329136b6a；fixed `/tmp/member-partitions6-fixed-verify.py` SHA0e68fe303a9ec8ad7a1cd753300a74b9aeca7dcc31f8894838f26a05dcb37cba。详细参数、测试SHA、执行边界在 `/tmp/member-partitions6-handoff.md`。全部仍仅准备。
- root明确启用另有migration_needed：旧5API未完历史流加2会变interleaved policy，保留旧游标/状态，禁止为放行重置。verifier持续报该gap以及supplier_board_universe_unverified/member_second_axis_coverage_unverified/historical_pit_unverified，即使6子样本通过仍verified_with_gaps；单独partition_samples_verified不能当enable授权。父继续真实probe/固定保存与追加scope迁移审查，归属释放。
