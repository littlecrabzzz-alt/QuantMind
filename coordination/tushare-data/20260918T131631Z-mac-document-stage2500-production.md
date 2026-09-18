# Tushare：文档阶段 2500 生产验收

- 时间、节点、任务：2026-09-18T13:16:31Z，Mac，document-stage2500
- 状态：已验收并保留；全量历史同步继续运行。
- 代码：`2404fb25ba1d7678f4ec52d1dbc9dd0b844b1550` 已合入并推送 `master`；候选分支为 `codex/tushare-doc2500` / `ccaeb1d3184d65dc200e36c62c5b24daf545ea32`。

## 逻辑与验证

`document_worker_max_documents` 的硬上限从 2000 有界提高到 2500。生产仍使用 100 秒文档截止、8 路下载、4 路解析、256 MiB 单文件上限；Tushare 分层限频、日配额和 Mac 全量/云端研究缓存边界均未改变。

相关回归共 89 项通过：系统 Python 执行 64 项文档、归档、限频与安装测试，含 DuckDB 的已部署运行时执行 25 项流水线测试；Ruff、`py_compile` 和 `git diff --check` 通过。2500 被接受，2501 及非整数继续拒绝。

## 部署与真实吞吐

部署前原子移出 `ENABLED`，等待已进入的一轮完整提交并明确写出 `disabled`；随后卸载旧 LaunchAgent、原子替换配置、原样恢复 marker 并重新安装运行时。新 LaunchAgent PID 为 31673，`runs=1`、`last exit code=(never exited)`。

- 私有配置 SHA-256：`b7d27d2aae6596d77fca7794be7bdf86f54b0bfbde9638dfb0c1e2a22dbf9c83` → `aaea7c4c1963265fdc976e1d22b1ebab78a6c8eb9d1d939f7933a94e1308ba48`，权限保持 `0600`。
- `ENABLED` SHA-256 保持 `6b45163b577df25f4e6842501fc95128649c5b129daddf3958224864008eda40`，权限保持 `0600`。
- 运行时和仓库 `tushare_archive_worker.py` SHA-256 均为 `f4b8e05e7c6cd7d5794e798e002e6f5d4bc87125367ec1b04d40fdbe1149bba0`。

| 周期开始 | 真实 Tushare 请求 | 文档阶段 | 下载 / 解析 | 文档耗时 | claim / finish | 失败阶段 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 13:09:18Z | 489 | 2238 | 1133 / 1105 | 100.488s | 2238 / 2238 | 无 |
| 13:11:26Z | 479 | 2500 | 1264 / 1236 | 100.846s | 2500 / 2500 | 无 |
| 13:13:27Z | 494 | 2364 | 1196 / 1168 | 100.258s | 2364 / 2364 | 无 |

三轮平均 2367.3 个文档阶段，比原先固定命中的 2000 上限提高约 18.4%。每轮 `processed == claim_db_calls == finish_db_calls`，且下载与解析之和与总数一致。验收时的 11 个 claim 均属于已开始的下一生产轮活动 owner（7 下载、4 解析），不是上述已完成周期的遗留。

系统内存压力查询显示 86% 可用余量，采样进程树 RSS 约 347 MiB；数据盘约 2.1 TiB 可用，未触发 300 GiB 停写或 500 GiB NAS 迁移告警。私有验收收据为 `validation/document-stage2500-gray-v1.66b06ae15ce5735ea981f0626a220260d8cdab046a49c4e67c3370521aaf514f.json`，权限 `0600`；灰度回滚临时配置已在验收后删除。

Mac 继续作为唯一全量归档写入者，云端仍只保留研究子集/缓存。结构化任务和文档任务仍是百万级，本次验收不代表全量历史已完成。
