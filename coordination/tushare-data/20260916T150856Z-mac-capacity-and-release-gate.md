# Tushare 容量与发布门槛（Mac，2026-09-16 23:08 CST）

- 本次仅做只读容量/状态审计；云端正式数据、QuantDB 和服务均未停改。Git 观察时为 `f08615a6`，Tushare 镜像修复已在 `6dc8a972`。
- 云盘 `/dev/vdb`：总 `845309321216`、已用 `690918297600`、可用 `114624643072` 字节；100 GiB 保留线为 `107374182400`，余量仅约 7.25 GB。`du -x` 实测 `/root/data/disk/quantmind/snapshots` 为 `407248216064` 字节，项目为 `267067154432` 字节，其中 Tushare 为 `187498450944` 字节；另有 QuantDB 快照 `8805523456` 字节。空间下降不能全部归因于 Tushare。
- 云端 `CURRENT.json` 为 `data-58ed3e4f6459c50642224d0db2f2b01bbb89c412a5e294bb54a01b3536b3fede`，清单含 `1192964` 文件、`157030` 数据集；coverage 为 done `147199`、empty `125971`、pending `7331919`，不代表历史完成。
- 文档状态文件截至 9 月 14 日：已下载约 `42752`、pending `1338025`。按当前 documents+attachments 约 69.6 GB 与已下载规模粗推，剩余正文及附件约 2–3 TB；实际文件大小、失败率、增量和快照留存会改变结果。这是规划区间，不是全量承诺。
- 建议云盘总容量扩至 5 TiB；希望减少再次扩容则 6 TiB。扩容由用户在云平台操作；设备扩大后在线核对并 `resize2fs /dev/vdb`，不停止 QuantDB。保留至少 100 GiB 恢复余量。
- 2026-09-16 22:58 CST 发布任务在 `publish.serialize_manifest` 被 Celery 600 秒 soft limit 中断，`CURRENT` 保持上述已发布版；生产五个核心服务 healthy、restart 0。须修复发布预算并真实验收。
- Mac `CURRENT.json` 仍是 beb5，私有 `.mirror-target.json` 锁定 d5；长连接多次在对象 rsync 超时。`169be2f5` 实现清单断点续传，`6dc8a972` 锁定重试版本并已部署；尚未完成本地切换、精确引用及断网读取验收，不能称本地追平。

下一步：扩容后核对设备/文件系统与服务；修复发布 600 秒上限并验收新固定版；调查 Mac 镜像长连接/陈旧 LaunchAgent 状态，完成 d5 或更新版本的本地固定读取闭环。原 `fund_nav10` 与 `index_daily23` 的 2100 个引用已在云端 ef0 和后继 2fc 版本逐项校验通过，仍需 Mac 验收。
