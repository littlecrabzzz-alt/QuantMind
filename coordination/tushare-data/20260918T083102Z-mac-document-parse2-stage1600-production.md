# Tushare：双路解析与 1600 阶段生产验收
- 时间、节点、任务标识：2026-09-18，Mac，document-parse2-stage1600
- 状态：完成并继续生产运行
- 代码：`6a8d7b98 perf(tushare): bound parallel document parsing`、`f8d76cf2 perf(tushare): raise bounded document stage cap`，均已合入并推送 `master`
- 接续：`20260918T080503Z-mac-document-parse2-start.md`、`20260918T082052Z-mac-document-stage1600-start.md`

## 逻辑与测试

- `document_parse_workers` 默认 1、上限 2；双路只在下载/解析重叠已启用且下载 worker 大于 1 时合法。每个 PDF 子进程原有 1 GiB 常驻内存、15 秒 CPU、5000 页和输出限制不变；SQLite claim、attempt、finish 仍仅由主线程执行。
- `document_worker_max_documents` 配置上限从 1000 有界扩到 2000，生产只采用 1600；100 秒总截止、6 路下载、磁盘保护和单文件限制不变。
- 80 项文档/归档/规划相关回归与后续 54 项阶段上限定向回归通过；Ruff、`py_compile`、`git diff --check` 通过。隔离测试实际达到下载峰值 2、解析峰值 2，并验证 claim 清空、attempt/finish 与完成阶段一一对应；2000 接受，2001、非整数与缺少重叠前提的双路配置均拒绝。

## 部署与真实吞吐

- 两次部署均在自然周期边界排空后更新。最终仓库/运行时 `tushare_documents.py` SHA-256 同为 `049380325ec02168fd25df64f3665e67eac34695336fdf131b8cbbfd7abd856a`，归档 worker 同为 `0db74e01a2c24d17bf814b9bd07b3faedc3d8d95ab8f468373bd5af770d6bf18`；`ENABLED` 保持原 SHA-256 `6b45163b577df25f4e6842501fc95128649c5b129daddf3958224864008eda40`。
- 新代码单解析器基线：625 阶段（下载 324/解析 301），解析活跃 96.28 秒、作业 96.24 秒、槽位空闲 0.03 秒，真实请求 625，失败阶段为空，证明单解析器饱和。
- 私有配置先从 SHA-256 `446e480a51acd57920725c40e937a5b2be71853edf0402c182ccb29c3cdbc458` 原子切到双路 `6e740f8558d4b02dea61a9fc18b682048bae1e9b7ce789e6a0e26dde818d9874`，权限保持 `0600`。双路在 1000 阶段档位连续三轮均提前命中上限，下载/解析为 511/489、503/497、477/523；真实请求 615/613/641，失败阶段为空。
- 阶段档位随后从 1000 原子切到 1600，最终配置 SHA-256 `3e96ee9ece5ebed01b18c5a7b7f599f140e52f582572bd144d3887c431e4b209`、权限 `0600`。三个连续周期处理 1403、1414、1068 个阶段，下载/解析分别为 671/732、697/717、545/523，claim/finish 一致。第一、三轮真实请求 659/626；第二轮恰逢固定 `interval_due` 规划、请求 0，但同轮真实处理 1414 个文档。失败阶段均为空。
- 1600 档位平均 1295 阶段，约为单解析器基线 625 的 2.07 倍；没有放松文件完整性、事务或资源限制。主进程观察约 395 MiB RSS，系统 `Pages throttled=0`，磁盘约 39% 已用。

## 当前边界

- 最新结构化队列 pending `2,884,788`、done `339,882`、blocked `871`；文档注册游标 `176307`，每轮继续处理 10,000 条。文档 pending `1,932,865`、parse_pending `91,296`、parsed `56,835`；注册追赶仍会新增历史文档，因此 pending 暂时上升不表示倒退。
- 可用空间 `2,440,044,613,632` bytes，NAS 提醒 false。全量历史同步尚未完成，Mac 继续是唯一全量写入节点，云端只保留研究子集/缓存。
