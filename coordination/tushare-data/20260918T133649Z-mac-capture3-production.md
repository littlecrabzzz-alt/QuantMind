# Mac Tushare 三路隔离采集生产验收

- 时间、节点、任务：2026-09-18T13:36:49Z，Mac，capture3
- 状态：生产保留 `acquisition_pipeline_depth=3` 和 `acquisition_capture_workers=3`；Mac 仍为全量归档唯一写入者。
- 代码：`ee88238a5e5c9b83828c8e5da25c2ea75a1ae423` 已合入并推送 `master`；候选分支为 `codex/tushare-capture3` / `3ae6f2c7b8ded2a991fb98305b81e2c009612b1c`。

## 逻辑与回归

候选将 pipeline depth 和 capture worker 的硬上限从 2 提高到 3。多路捕获仍必须使用 process 隔离，worker 不得超过 depth；主进程仍在每个 HTTP 请求前串行持久化共享账户/API gate 和每日配额，并串行提交结果。500 次/分钟账户上限、接口特殊上限、`batch_requests=800`、`batch_seconds=100` 及 `cyq_*` 每日配额均未改变。

67 项 pipeline、rate-policy、archive-worker 和 installer 回归通过。本地 HTTP 夹具分别实际达到 2 路和 3 路峰值，对应 observation 全部持久化；超界值、thread+3、worker 超过 depth 和 process+depth1 均被拒绝。Ruff lint、Python 编译与 `git diff --check` 通过。现有大文件的旧格式不符合当前 `ruff format` 全文件输出，本次未做无关的全文件重排。

## 部署与真实吞吐

部署前原子移出 `ENABLED`，等待在途周期完整提交并写出 `disabled`，再卸载旧 LaunchAgent、原子替换配置、恢复原 marker 并重新安装运行时。配置指纹变化后只执行了一轮预期的 `planning_only`：Tushare 请求为 0，文档仍完成 2500 阶段，随后立即进入真实采集。

- 私有配置 SHA-256：`aaea7c4c1963265fdc976e1d22b1ebab78a6c8eb9d1d939f7933a94e1308ba48` → `e5b3b3e723d9d4ba8bb44c1ba081701325521dae10e4b0244311eafa1e654317`，权限保持 `0600`。
- `ENABLED` SHA-256 保持 `6b45163b577df25f4e6842501fc95128649c5b129daddf3958224864008eda40`，权限保持 `0600`。
- 运行时和仓库 `tushare_pipeline.py` SHA-256 均为 `3a2236363f486a85117ba71034a2328c8c1bffa1bf81ecfcbe077764f5d46cda`。

| 真实周期 | Tushare 请求 | gate 预留 | depth / HTTP worker / 高水位 | 文档阶段 | 失败阶段 |
| --- | ---: | ---: | ---: | ---: | --- |
| 1 | 521 | 521 | 3 / 3 / 3 | 2360 | 无 |
| 2 | 485 | 485 | 3 / 3 / 3 | 2478 | 无 |
| 3 | 531 | 531 | 3 / 3 / 3 | 2500 | 无 |

相邻五轮双路基线为 470/451/396/439/478，中位数 451；三路为 521/485/531，中位数 521，提高约 15.5%。精确 attempt 范围为 rowid 712081–713617，共 1537 条：`sample_ok=774`、`empty_unverified=760`、`possibly_truncated=3`，全部 HTTP 200；`rate_limited`、`transport_error`、`api_error`、`invalid_response` 和 `permission_denied` 均为 0。

验收时系统内存压力余量 86%，进程树采样 RSS 约 387 MiB，数据盘约 2.1 TiB 可用。私有无凭据收据为 `validation/capture-workers-gray-v2.ee0861ac00b49146f69a323f719e1e68f7b831f34248fd1b8bf35e16080a2143.json`，权限 `0600`；回滚临时配置已在验收后删除。

Mac 继续本地全量历史同步；云端仍只保留受限研究子集/缓存，不恢复全量 writer。
