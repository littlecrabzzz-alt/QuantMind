# 云端旧归档与数据库副本已精确释放

- 源码 master 79a699d3 记录本次运维验收；无业务代码修改，无服务重启。
- 原始负载清理 unit quantmind-tushare-prune-apply-20260917 于 2026-09-16T20:27:22Z 成功完成，1,209,626 文件，219,773,995,368 逻辑字节，缺失 0。
- 数据库验证 unit quantmind-tushare-database-verify-20260917 于 20:30:36Z 成功，11 个旧库只读 backup 输出 SHA 全部匹配 Mac 冻结件。22 文件删除预检完成后，quantmind-tushare-database-retire-20260917 于 20:34:29Z 成功，34,884,812,800 逻辑字节。
- 旧云端归档剩余 648 MiB 运维证据/停写标记等；研究缓存 1.5 GiB；文件系统可用 352 GiB。完整备份 306 GiB 仍保留，等待正常成功轮转，未修改 COMPLETE 内容。
- 清理后云端实际应用路由 daily/adj_factor/ci_daily 各返回 2 行，upstream_calls=0。云端应用 StartedAt 18:55:46Z、QuantDB worker 15:31:26Z 均未变且 healthy；cache timer active。此处不是外部认证 HTTP/UI 验收。
- 私有完整证明在 Mac Library/Application Support/QuantMind/tushare-cloud-retirement-verified-20260917.json 和云端旧归档 .migration/checkpoint-2026-09-16T16-34-47.667824+00-00。
- 本地原生历史采集继续，未完成全量历史或权限/字段缺口验收。待办：继续实际历史补采与缺口治理、观察正常完整备份轮转后空间、最终全范围完整性验收。
