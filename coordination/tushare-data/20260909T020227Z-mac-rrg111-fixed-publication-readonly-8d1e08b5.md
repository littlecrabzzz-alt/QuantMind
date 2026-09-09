# RRG111自然固定版只读核查：CURRENT尚未推进
- Mac remaining_markets；仅只读云端quantmind python3 -S（dual-node.sh cloud-compose入口，sqlite mode=ro）与Mac已发布清单；无worker/mirror/publish/上游请求。
- 云02:00:28Z CURRENT仍data-ea8b819290385b2d630d940e2e3bd041f0c51ae59fe62c1256ba7ea4c9ff5af3。02:01:18Z一次SQLite快照：111目标全部新尝试，81done/30empty，445887源行，所有目标observation与先前完整验收报告一致，无新增/变更；CURRENT对应manifest重算SHA通过。按父要求不忙等、不重复同版昂贵全量reader。
- Mac锁定同一ea8清单，111对应303唯一文件：133文件清单SHA/bytes匹配且本地逐文件重算通过，覆盖49目标/194099行；余62目标不在该固定release（170文件未纳入），不能声称剩余已发布或镜像闭环。
- 原完整111 raw/obs/Parquet及所有manifest parts独立dedup证据仍为/tmp/tushare-rrg-priority-readonly-report.json；此轮以相同云manifest hash+111 live observation一致性链接复用，不冒充新固定版重跑。没有新的自然release可验，研究仍blocked_data。
- 新报告/tmp/rrg-fixed-membership-20260909T020028Z.json，云一次快照/tmp/rrg-current-live-20260909T020028Z.json，未覆盖前报告；后续CURRENT推进再锁定新固定版复验62。
- 新汇总报告SHA256：43490217aa818bc601739ce54f2e3ff9b7cde7f5708732c3cb77fb6a65eae8df
