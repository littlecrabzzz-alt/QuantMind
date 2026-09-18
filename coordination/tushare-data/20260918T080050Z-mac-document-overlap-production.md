# Tushare：文档下载与解析重叠生产验收
- 时间、节点、任务标识：2026-09-18，Mac，document-overlap
- 状态：完成并继续生产运行
- 代码：`7e45175a perf(tushare): overlap document transfer and parsing`，已合入并推送 `master`
- 接续：`20260918T073937Z-mac-document-overlap-start.md`

## 行为与验证

- 新配置 `document_overlap_parse_download` 默认关闭。启用后下载继续受现有 1..8 worker 上限约束，PDF 解析始终最多一条；SQLite claim、attempt 和完成事务只在主线程执行。下载最多领先四批槽位，每轮阶段数、100 秒截止、单下载 20 秒与文件大小上限保持不变。
- 79 项文档队列、持久 claim、截止时间、终态恢复、归档 worker、规划指纹和独立 worker 测试通过；Ruff、`py_compile`、`git diff --check` 通过。新增测试真实制造线程重叠并验证下载峰值 2、解析峰值 1、claim 清空、attempt 数与完成阶段一致。测试输出中的 SQLite ResourceWarning 是既有夹具清理提示，没有测试失败。
- 运行副本与仓库 `tushare_documents.py` SHA-256 同为 `fa07d2bb358f1787387bf81d2b7d34b1a50c8f6be38ebe761ec71e88902baac3`，归档 worker 同为 `b6fc85ef572aa123aff444ff6f12ef7a7ad1ed6a9a360a5dfc610b433e2b456c`。部署只在自然周期边界排空后进行，`ENABLED` 恢复为原 SHA-256 `6b45163b577df25f4e6842501fc95128649c5b129daddf3958224864008eda40`。

## 真实生产灰度

- 新代码默认关闭的首轮基线：107.04 秒，真实 Tushare 请求 682 次，文档阶段 232 个，`overlap_parse_download=false`，周期成功。
- 私有配置以原子替换从 SHA-256 `97745aec837c75918bae536ba1e28f0614d08a2ef7283b482b2db25508095d33` 切到 `446e480a51acd57920725c40e937a5b2be71853edf0402c182ccb29c3cdbc458`，权限保持 `0600`；只新增布尔开关，不输出 Token。
- 三个连续正式周期分别处理 699、659、655 个文档阶段，下载/解析分别为 361/338、341/318、339/316；下载与解析真实重叠 82.49、72.55、59.76 秒。每轮真实 Tushare 请求 649、682、676 次，失败阶段均为空，规划原因均为 `interval_not_due`，规划指纹保持 `365ac7dea542d0226d352dbff7ce8c11e6a5d20ad84dac2f23a49da31136da4a`。
- 新档位平均每轮 671 个阶段，约为此前两个无规划旧周期均值 334.5 的 2.0 倍；下载与解析仍接近 1:1，没有用扩大未解析积压换取吞吐。第三轮 claim/finish 均为 655，数据库总耗时分别约 0.57/0.71 秒。
- 资源检查：主进程约 252 MiB RSS，两个工作进程约 54/46 MiB，系统 `Pages throttled=0`。验收末可用空间 `2,449,098,149,888` bytes，NAS 提醒为 false。

## 当前边界

- 归档继续真实运行；结构化队列 pending `2,888,665`、done `335,098`、blocked `871`，当前文档 pending `1,858,378`、parse_pending `88,780`、parsed `50,322`。注册追赶仍在发现历史附件，因此 pending 可暂时上升。
- 全量历史同步尚未完成。Mac 仍是完整归档唯一写入节点；云端只保留研究子集/缓存，不启用全量写入。
