# 分片复核全套验证补齐

本次仅更新生产验收证据，不修改运行代码或暂停采集。接续 20260919T022600Z-mac-reconciliation-observability-production.md。

旧临时测试入口在模块顶层执行 unittest.main，缺少 __main__ 保护；spawn 子进程可再次执行 discovery。先前将 BrokenProcessPool 归因于操作系统中断没有足够证据，现予更正。使用标准 python -m unittest 入口，并将已缓存依赖路径传给 -S 子进程，1396 项运行、5 项跳过、零错误/失败，120.203 秒。测试树 a058fa12 与 master 8f090cd2 的 backend/shared、scripts、config 完全一致。可复现命令和日志SHA存入现有生产验收JSON。

云端10:25缓存任务退出0，12个数据集、4113381152字节、status=verified、upstream_calls=0，来源为本地已发布fdebee7d版本；Mac定时发布尚未到期，实时采集数据不等于已发布缓存。全量历史与附件队列继续处理，目标未完成。
