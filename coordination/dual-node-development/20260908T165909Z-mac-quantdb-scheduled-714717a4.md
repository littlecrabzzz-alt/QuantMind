# QuantDB 自动更新与离线快照：已启用
- 状态：调度部署完成；首轮 QuantDB 追平运行中。接续 20260908T164303Z-mac-auto-data-b224bedf.md。
- 代码：9610182、d2dd8c6、3c78cf3；候选在 /private/tmp/quantmind-auto-data（codex/automatic-data-refresh）验证，已集成主分支/GitHub。末次两端 handoff passed，HEAD 3c78cf3，4256 个源码/共享配置哈希一致；并行 Tushare 提交与未提交研究文件保留。
- 范围：QuantDB 现有 A 股链路；Tushare 是独立开发需求，不能替代 QuantDB。部署规范复用 docs/development-data-contract.md 与 docs/dual-node-deployment.md。

已完成：
- 云端 Redis 市场 A 保存 enabled=true、03:00、with_qlib=true、datasets=[]。旧 A 定时入口跳过 PG 且忽略配置，现串起全量数据集增量下载、PG upsert 与 Qlib；共用同步锁和控制台进度，失败/部分失败保留状态。
- 云端 quantmind-snapshot.timer 已 enabled，下一次 2026-09-09 07:00 CST；复用完整一致性快照，含 QuantDB/PG/Qlib。活动研究任务跳过，不中断；Tushare 采集 worker 纳入完整快照停写/恢复。systemd 配置校验通过。本轮未人为运行新完整快照，正式停写耗时仍待首轮验证。
- Mac com.quantmind.snapshot-pull 已安装，每 3600 秒；初次真实后台完整验证成功、exit 0。351346 文件、68061617857 字节全部复用，数据主体传输 0 字节（协议/清单约 16.9MB）；再次 kickstart 成功跳过同版、exit 0。
- 下载目录原子移动到 ~/Library/Application Support/QuantMind/cloud-snapshots，原 logs/cloud-snapshots 为软链接；没有第二份拷贝。客户端也在 Application Support，复用原 Python/SSH；运行不依赖聊天任务。
- Mac/云端已验证版本均 snapshot-20260908T134413970428Z；.local-dev/SNAPSHOT_ID 保持同一旧版本。新下载只更新下载池，沙盒数据和卷不变，无本地回灌。

验证与当前进度：
- 9 项市场调度测试、18 项部署回归、22 项隔离/故障测试通过；可选真实 Docker smoke 本轮未重跑。编译/diff 检查通过；本机无 Ruff，未声称 Ruff 通过。
- 上游 QuantDB trading_calendar manifest 访问成功（1 对象）；开始前 PG 最新交易日 2026-09-04，不能据调度开启宣称已追平。
- 手动发起现有 Celery 完整任务 fb9644ab-cfb3-43dc-95c6-54760c5578ed，真实控制台作业 qdb-celery-20260909-005716。00:57 起运行，已进入 Parquet 数据集处理，with_pg/with_qlib 均 true；尚未完成 PG/Qlib 阶段验收。Worker 子进程已自然更替并执行新入口，本轮没有重启业务服务。

后续：通过现有控制台/Redis 作业和 Celery 结果检查首轮是否 partial/failed、PG 最新日及 Qlib 产物；07:00 快照服务日志与 Mac 下一轮记录验证新版本下发。调度会持续运行，不需要保持本任务打开。磁盘不足 100GiB 或忙时保留旧快照、记录失败并次日再试，不自动清理历史。实现文件归属已释放。
