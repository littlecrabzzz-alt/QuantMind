# Tushare：四路文档解析生产验收

- 时间、节点、任务：2026-09-18T09:46:33Z，Mac，document-parse4
- 状态：已验收并保留 `document_parse_workers=4`；全量历史同步仍在进行
- 代码：`master` / `cccae33b24974edbd3686be1dd7cf44a5fb42689`
- 存储边界：Mac 继续保存全量归档，云端只保存研究子集/缓存

## 代码与边界

解析 worker 配置上限从 3 扩到 4，默认仍为 1；多路解析仍要求下载/解析重叠开启且下载 worker 大于 1。每个解析子进程原有的 1 GiB 常驻内存、15 秒 CPU、5000 页和输出上限均未变化；SQLite claim、attempt 和完成事务继续只由主线程写入。

新增隔离并发测试让 4 个下载任务和 4 个解析任务同时到达屏障，峰值严格为 4/4，8 个阶段全部完成，claim 清零且完成事务数等于处理阶段数。定向 56 项、完整相关回归 82 项均通过；Ruff、`py_compile` 和 `git diff --check` 通过。测试仍会输出已有的未关闭测试 SQLite 连接 `ResourceWarning`，不影响结果。

## 部署

部署前原子移出 `ENABLED`，等待在途周期提交完成并由 worker 明确写出 `disabled`；随后卸载旧 LaunchAgent、安装 `master` 运行时、原子更新私有配置并恢复原 marker。全量数据库与文档目录未移动或重建。

- 配置 SHA-256：`ba1d4ca5df959f3bfab5f0a345e6477e24aaa48c007324056ffcfee886e67341` → `bae4b800925a5812702fd479bb1308ce32046a7c77693de1ea623ca1bae39aa2`，权限保持 `0600`。
- `ENABLED` SHA-256 保持 `6b45163b577df25f4e6842501fc95128649c5b129daddf3958224864008eda40`。
- `archive.env` 权限仍为 `0600`；记录中未写入 Token 或订单信息。
- 仓库与运行时的 `tushare_documents.py` SHA-256 均为 `86070fc86234cfd1f1e9978fc08d33cbc08ab3adbaeb498797dce92b5b411df9`；`tushare_archive_worker.py` 均为 `e7bc93b2931e73a65cfaab0443e5b65261b2b8f6e4feb81707ea8414f9a52bc4`。
- 1800 阶段、100 秒、6 路下载、独立文档进程、Tushare 分层限频和日配额均未改变。

## 真实生产吞吐

| 周期开始 | 文档阶段 | 下载 / 解析 | Tushare 请求 | 解析槽任务时间 / 容量 | 峰值进程树 RSS | 失败 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 09:40:22Z | 1,800 | 893 / 907 | 626 | 358.497 / 384.461s | 1,098.3 MiB | 无 |
| 09:42:16Z | 1,800 | 784 / 1,016 | 0（`planning_only`） | 371.066 / 375.991s | 1,317.9 MiB | 无 |
| 09:44:02Z | 1,800 | 697 / 1,103 | 714 | 328.711 / 343.493s | 1,197.9 MiB | 无 |

三轮均达到 1800 阶段上限，平均 1800；三个解析器发布后最近四个普通轮次为 1579、1800、1299、1787，平均 1616.25，因此本次观测完成量提高约 11.4%。第二轮的 `planning_only` 只表示规划间隔未到，1800 个文档下载/解析阶段仍真实执行并提交。

最高进程树 RSS 为 1.32 GiB，明显低于四个解析子进程的最坏 4 GiB 预算；验收后 `Pages throttled=0`，数据卷可用约 2.2 TiB。LaunchAgent 保持 `running`、`runs=1`、无退出；错误日志在部署与三轮验收期间没有新增内容。

## 当前队列

最新原子状态中的结构化队列为 `done=349187`、`pending=2875952`、`empty=300074`、`blocked=871`、`permission_blocked=4784`、`split_pending=9853`。文档队列为 `pending=2093905`、`parse_pending=101167`、`parsed=82209`，另有已审计的终态和少量 retry；本轮文档登记继续从旧 attempt 发现新 URL，因此显式待办可在处理过程中增长。

结论：四路解析在真实生产中稳定提高吞吐且资源余量充足，保留 `document_parse_workers=4`。Mac 后台继续进行全量历史同步；队列仍为百万级，本次验收不代表全量已经完成。
