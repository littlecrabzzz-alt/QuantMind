# Tushare 发布与 identifiers 尾延迟审计开始

- Owner `/root/document_throughput_next`；Mac 独立 worktree `quantmind-tushare-tail-latency`，分支 `codex/tushare-publish-identifiers-tail-20260910`，基线 `957d060b9e19a14125854239a7dc5a90c04980a3`。
- 只读审计当前 `Pipeline.publish`、`Pipeline.identifiers`、既有固定版/生产脱敏证据，并在临时目录做禁网离线基准。不得读取生产/Token，不修改生产、共享主工作树、Celery 超时、限速、批量或服务配置。
- 发布候选必须保持清单字节、SHA、不可变文件落盘、publication intent、CURRENT 原子切换和失败恢复顺序；发现候选必须保持 jobs/attempts 来源成员、请求敏感绕行、所有任务身份/游标及最终 identifier 集合。不能证明净收益的原型撤销，只提交证据。
