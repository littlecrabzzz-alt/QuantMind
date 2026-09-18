# Tushare 港美股财报权限验证开始

- 时间、节点、任务：2026-09-18T22:27:32Z，Mac 全量归档唯一写入者，`foreign-financial-permission-probe-20260919`
- 状态：进行中；生产同步保持运行，代码在独立 worktree 开发。
- 分支、worktree：`codex/tushare-foreign-financial-probe-20260919`，`/private/tmp/quantmind-foreign-financial-probe-20260919`，基线 `5ce495bb950e47fefa031fc03ac6c20486d70cb4` 。
- 分工与文件：本任务只负责 `scripts/tushare_foreign_financial_probe.py`、对应测试和本记录；不修改主工作树未提交的 RRG/研究文件。

目标：在不盲目生成约 27 万个历史任务的前提下，对已实现但当前未启用的 8 个港股/美股财报接口各做 1 次有界真实请求。默认模式不读密钥、不访问上游；执行模式校验 helper SHA、Mac 归档权威标记、SQLite v6、固定标的发现记录和唯一写锁，最多 8 次、120 秒。结果通过现有 raw/observation/normalization/capability 链路落盘，另写脱敏收据。

下一步：实现并完成无网络测试，合入 master 后等生产周期自然结束，短暂停写运行真实权限验收。
