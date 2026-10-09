# 远端存储恢复与优化实施计划

用户已在代码审查后确认执行。沿用 Mac 唯一采集、云端接收与业务数据权威，不创建第二套数据服务。

## 设计与实施顺序

- [x] 紧急恢复：停完整快照 timer，在独占快照锁内移除已确认的未发布失败副本，保留最新完整快照；验证数据库恢复。
- [x] 快照：使用同一范围策略完成复制、清单、增量与校验；排除 `data/local-market-source/incoming`、`backups` 等可再取得的运输载荷，但保留回执和研究输入。历史已发布清单按旧规则仍可验证；新快照标记规则版本。保留副本内部硬链接，绝不把新副本硬链接到活跃源。按估算额外复制量、DB/卷导出和运行预留检查容量，复制时监测；废弃旧暂存规则不静默复用。
- [x] 接收：上传清单后、上传载荷前进行云端容量预检，估算新/变更文件及临时写入的保守上限；共享磁盘上的快照和接收使用现有锁进行准入协调。上传阶段保留余量；已应用、失败、正在使用版本分别处理。受管回执保护当前版本与中断恢复，成功后只轮转有显式完成标记的传输包，保留两版，未知/旧版保留。
- [x] 日志与消费：Redis 系统故障立即结束批次，逐步延长重试并合并重复错误；文件系统 ENOSPC 不连续输出 logging 堆栈；云端容器日志限制单文件大小及轮转数。
- [x] 就绪：保留原存活检查，另提供磁盘/PG/Redis 持久化就绪状态；健康探针应检查 JSON degraded 状态，避免假健康与重启风暴。
- [ ] 发布：明确路径提交，主工作树快进合并、Syncthing 内容核对、Git 元数据对齐；备份启动配置/修改文件，检查活动任务后仅更新相关服务及 Mac 已安装上传客户端；远端实测容量拒绝、数据库、日志、接口、HAPI，并恢复修正后的备份 timer。

## 回归与验收

使用临时目录和假服务，不以生产数据跑测试：三硬链接不膨胀；被排除的传输文件不会在增量重新进入；旧快照可校验；容量不足拒绝且 latest 不变；中断阶段不清理；上传前预检失败时不传载荷；当前版本/待恢复版本/未知目录不删；Redis 一次故障仅一次失败读取；退避和恢复；ENOSPC 记录不形成堆栈风暴；HTTP 200 + degraded 不被识别为业务就绪。

运行 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts python3 -m unittest scripts.test_dual_node_safety scripts.test_storage_recovery` 及本次新增针对性用例；集成时按依赖环境运行本地数据源回归。Linux 上用小型临时数据完整走复制/清单/校验流程；实际生产完整备份属于较长 I/O 操作，报告真实状态而不以 timer active 冒充成功。

## 保留边界

保留真实业务库、研究结果、冻结输入、唯一恢复快照、迁移前旧 QuantDB 快照与其他应用的文件。系统盘及数据盘独立监测；不关闭 Redis 持久化保护来掩盖故障。

## 实施验证（2026-10-09）

- 数据盘失败 `.building` 已在独占锁内移除；保留当时最新完整快照。可用空间从 0 恢复到约 142 GiB，PG 健康、Redis RDB/AOF 均为 ok。
- 新快照 `snapshot-v2`，统一排除传输 incoming/backups；旧清单仍按 legacy 校验。rsync 保留副本内部硬链接，仅复用前一份不可变快照。
- 容量采用 rsync dry-run 实际差异 + DB/卷导出预算 + 100 GiB 预留。bulk subprocess 每秒检查，在预留之上另保留 2 GiB 写入缓冲；信号中断先回收子进程再释放锁。接收派生也进入受监控进程，保留原收据续跑。
- 只轮转新代码成功标记 `MANAGED-v2` 的运输/回滚副本，保留两版与当前版；未标记历史目录不清理。
- 快照保护 `qm-research-*` 实验；自主研究协调器先检查真实活动状态，关闭 API 入口后再次检查，空闲才暂停并在 finally 恢复。
- 独立审查已复核信号遗留进程、活动研究和接收派生三项修复。Linux 临时目录 19 项回归通过；复制/清单/完成标记走真实 rsync，未操作生产数据库。
- 线上只读容量预检：预计复制 7,414,806,283 字节，卷逻辑大小 5,179,086,414 字节，总额外预算 19,920,462,759 字节；当时可用 151,644,983,296 字节，符合 100 GiB 预留。该预检不是完整备份完成证明。

## 发布与恢复证据

- 候选代码 `0f8c179d` 已合入两端 `master`，handoff 验证通过；原有四个未提交文件保持原样。70 项相关回归通过，1 项 opt-in Docker 测试跳过。
- Mac 已安装客户端通过 `.source.lock` 更新；保留安装副本原有的 L1 OHLCV 近 10 天采集差异，未重新安装定时任务或启动采集。旧客户端备份在 `~/Library/Application Support/QuantMind/client-backups/storage-recovery-20261009-1339/`。
- 云端 12 个当时运行的 QuantMind 容器均已实测 `json-file / 20m / 3`。沿用原镜像 ID、环境变量及数据挂载；配置有历史差异，故此次通过 `cloud-compose -f /root/backups/quantmind-storage-recovery-20261009-1322/keep-running-config.yml` 保留真实运行参数。该文件含现有环境凭据，仅存服务器私有目录，不入 Git。以后发布前需重新核对运行参数，不能假定默认 Compose 与现场完全一致。
- 远端真实 rsync 验证：超额预算在载荷上传前拒绝；允许的小文件完成传输并校验；临时测试数据已移除。
- 本次重启暴露旧 AOF 中段损坏：磁盘恢复后 `INFO persistence` 状态为 ok 不能证明整个旧文件可回放。未使用会截断后半段的 `--fix`；依据 [Redis 持久化说明](https://redis.io/docs/latest/management/persistence/) 在隔离、无网络容器中，从本次正常退出生成的 `2026-10-09 13:47:42 +08:00` RDB 重建 AOF。RDB checksum OK；重建前后全库 DEBUG DIGEST 一致；新 AOF 全文件检查通过，随后生产启动成功。旧文件与原始 SHA256 全保留。校验工具需可写打开文件，因此检查在副本中执行，额外核对校验前后文件哈希未变；从未在原件上执行修复截断。
- Redis 证据在 VPS `/root/backups/quantmind-storage-recovery-20261009-1322/redis-repair/`；原目录中的旧 AOF 另保留为 `.appendonly-before-repair-20261009`。修复使用刚退出的内存快照，不切换到历史业务备份；自然到期键按 Redis TTL 正常过期。
- 已验证 PG 临时表事务写入并回滚、Redis 独立 TTL 测试键写入后删除、四子服务健康及独立存储 readiness。HAPI `https://lzy.me.uk/health` 返回 ok；系统盘约 35 GiB 可用，数据盘约 142 GiB 可用。完整快照验收从 13:55:28 开始，最终结果另记。原 `quantmind-snapshot.timer` 已恢复 active/enabled，原有每日北京时间 07:00 规则未改变；手动作业运行期间定时器不显示下次触发时间。

## 追加性能验证

- `97804e00` 已在两端 master 对齐，7494 个源文件内容指纹一致。暂存文件仅在本轮内复用 stat/hash 缓存，最终校验仍独立读取全部文件；修改文件重新计算，篡改则拒绝 COMPLETE/latest。真实 rsync fixture 同时在 macOS 与 Linux 通过。
- 最新相关回归 71 项通过，1 项 opt-in Docker 测试跳过。Mac 已安装快照模块同步更新，旧模块保存在 `~/Library/Application Support/QuantMind/client-backups/storage-recovery-20261009-1416/`。
- 13:55 启动的完整生产备份仍按启动时逻辑运行，不为追加缓存优化中断本轮验证。12 个容器约 15 分钟累计日志仅增长 397207 字节，约 26 KiB/分钟，证据为 VPS 恢复目录中的 `log-growth-report.json`。14:17 独立 readiness 通过，根盘可用约 34.6 GiB、数据盘约 132.5 GiB；备份暂存的额外写入已计入。
