# Tushare fund_share 精确批次生产结果

- 时间/节点/任务：2026-09-10T16:25Z，Mac 主集成人，fund-share-exact-root。
- 状态：代码、测试、master、云端部署、两批真实吞吐、固定版及 Mac 镜像验收完成；全量 Tushare 历史任务继续运行。
- 提交：`a7982586` 新增精确执行器；`54a517c4` 将新清单调整为近期优先并保持旧清单兼容。GitHub、Mac、云端均已对齐。
- 分工：本记录只涉及 `fund_share` 精确批次文件和证据；保留主树中 RRG/研究工作流的未提交文件。

第一批最早日期360项在46.368秒内全部empty，因此只作为精确请求诊断，不外推历史下界。第二批近期pending 360项在51.099秒内得到256 done/104 empty；两批均通过哈希、authority、schema6、共享锁、500rpm和100GiB门控，不发布、不切CURRENT。worker/Beat已恢复healthy，文档worker保持停用。

正常publish-only任务随后用220.122秒原子切换到 `data-d5d918ce4bc2cfd3ef6e58c5caeefa29c7d9f9715cd5b8cd0d03d4d07cab64de`。Mac自动镜像新增14028个文件、校验670543个文件后退出0；无Token、禁socket/DNS的 `fund_share` 固定版读取返回5行、上游调用0。最终worker/Beat healthy，部署后429/供应商频率错误/任务失败均为0。证据：`docs/tushare-fund-share-batch.md`、`docs/tushare-fund-share-batch-20260911.evidence.json`；生产清单和收据位于 `/data/tushare/validation/fund-share-batch-20260911/`。
