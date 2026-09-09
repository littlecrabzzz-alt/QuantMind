# Technical 历史前缀规划分析（只读）

父授权；不改任何代码/生产。575e3e1候选保留原样。既有验收/tmp/risk-technical-enable-20260909T022106Z-5c6cd8af.json（SHA6afdcf4c7d2ad2af4993996d9c244f5980dc8a247f81fa57a9022e2d0928cc08）提供真实冻结快照：technical_stocks6194、anchor20260909、5API。无需新采上游。

1. 现有 iter_technical_extra_jobs 先完整近期、后历史，两阶段各API轮转。近期=7×6194×2个CYQ+7×3个日线API=86,737。history planning_state.offset 是**整个生成器**的绝对已遍历项数，包含有意跳过的近期项。每批range(500)把这些skip也扣预算，初始500只是正确地走过500前缀，非权限/丢数据。
2. 第174个history planning pass才首次遇到历史；从验收offset500还需173次调用（含首次产出历史的那次）。不是174个下载请求，也不是全历史完成时间。实际调用还会受publish-only轮次/忙锁/失败影响，不按两分钟硬报ETA。
3. 本轮云业务入口只读PK+group索引查询（3秒保护，实际pending count0.003秒）：两个cursor均已4000，signature仍分别398150f7.../1212eb1d...不变，pending3948。最新acquire_only报告166请求、全family planning22.05秒；technical history仍500 skip/0 new，discovery_refresh_pending=true但冻结6194不重置。说明近期确实在入队、历史仍未过前缀，不是planning被pending阈值阻断。代码plan_extended无pending数量门槛，仅固定每mode预算；不能将22秒归因pending增长，尚无匹配规模/耗时对照。此前95万jobs的宽表publish热点是另一个阶段。

最小候选：保留原生成器、snapshot/signature/anchor/epoch、原islice的绝对offset。history循环的500预算只计真正history候选（含INSERT OR IGNORE已有任务），但count与offset仍累加全部实际next过的项；额外显式扫描项数/耗时上限，到界按已遍历count持久化，下一轮续。近期mode仍原500预算。本快照跳前缀+取500history在Mac纯规划约0.08–0.10秒，无数据库/网络；保守扫描上限如100,000项可本次跨前缀，但仍需worker隔离预算验证，不把Mac耗时当生产保证。

禁止把generator改成history-only后直接套旧offset，也不能filter(history)后再islice旧offset：offset4000目前全是近期，后一做法会静默漏前4000条真正历史。更不能直接重置cursor、将history_start从1990缩到近期、裁掉6194里历史/特殊代码，或删除pending。应对已跳过前缀计数照原含义前移，而非重新定义offset。

证明/后续测试要求：本轮纯fixture已在offset0/500/4000/86736/86737/86774边界验证新计预算算法选中500history与原stream过滤结果逐项相同，首批SHA a912785057e34ea6ad9a7cfecc0b3bf0b1187d11f5bc5611ccb2f7e8793dad6d，最终绝对offset=max(old,86737)+500。实现时另加扫描/耗时到界中断恢复、enqueue后commit前失败重跑、已有done/empty不改、近期cursor不动、发现新增只保留refresh_pending、其他family/预算不变测试；无需schema迁移或新调度表。

边界：该候选减少“空转批次”，未消除每次islice从头重放的O(offset) CPU，也不保证priority55历史在technical组priority20近期积压下及时消费（structured的3:1公平不适用于technical）。这两项分开监测，先不要扩展成新调度框架。

证据：
- /tmp/tushare-technical-prefix-analysis-20260909.json SHA256 b6f1aaa112309fa61e3cd34bc4dc491d9fc7e7fb3e6f9933ec401a470fd31bc9
- /tmp/tushare-technical-plan-state-readonly-20260909.json SHA256 15829f9c0589687bc389b531fc6828ffa702f6dcfbd16290383954ee6f2593f0
