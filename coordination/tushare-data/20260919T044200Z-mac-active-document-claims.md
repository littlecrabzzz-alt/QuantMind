# 活动附件租约到期误回收

Mac 04:40:33Z 轮次报告 DocumentError，采集主进程仍存活。该轮 wall 时间跨度约 256 秒而 monotonic elapsed 约 108 秒；旧报告只存类型，尚不能确认这一次异常的具体代码。

检查发现 _claim_documents 在同一 owner 领取下一个任务时删除所有到期租约，包括仍在运行的本 owner。隔离测试把 wall time 从 1000 推进到 2000 后稳定重现重复领取相同 ID。修复仅回收其他 owner 的过期租约；当前 owner 由全局 documents.lock 保护，进程退出后的新 owner 仍可回收旧任务，_finish_document 的所有者校验不变。

负责 backend/shared/tushare_documents.py 与 scripts/test_tushare_document_parallel.py，worktree /private/tmp/quantmind-active-claim-20260919。验证后自然排空部署，不重启业务后端。
