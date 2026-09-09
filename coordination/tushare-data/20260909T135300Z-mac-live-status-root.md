# 当前状态及接续

- 时间/节点/任务：2026-09-09 13:53 UTC，Mac，01a0817d-7378-7673-9b7f-59c302713981；完整接入目标仍进行中。
- 主树 master/origin master 为 9f629af；已读取本次更新后的 AGENTS 双端规则。父候选 35980cbc 含开户纯合同 0d251f1，融资运行时 006b293 + 起点签名修复 6236ca1 尚未由父合入。主树其他研究文件保持原状。
- 实时云端 13:52:28 UTC：Tushare acquire 7f411f4f 运行中，附件队列已注册、该瞬间空闲；未暂停或重启服务。
- 13:52:47 UTC只读查询：factor_value done307、empty205、pending76491。这是已规划请求状态，不是数据行数或最终范围。
- 最新持久批次状态 13:50:37 UTC 为 SoftTimeLimitExceeded：总159.985秒、planning66.556秒（identifiers60.030秒、body_reads27786）、acquire78.976秒、publication_check9.617秒。下一轮在运行，不能称停机或无错误；优先诊断发现耗时，structured agent 接续只读分析，涉及 pipeline 修改先协调 text 文件归属。
- 云端 CURRENT 为 data-079a77085ce4b2affe64712008bf5189c0e02deab402d0143f0a62ebb0d606f1；本次读取 Mac CURRENT 为 data-f2a06e652d00082826c4c354ebc6a75374b9dd7c3395ae8eb4c0372555f9d08c，二者尚未对齐。已有镜像 session99169 仍运行，stdout/stderr /tmp/stk-followup-mirror.{json,stderr}；不要重复启动。
- 股票分钟独立后续探测只调用一次，真实返回40203、2次/天；持久频控已记录，今天不追加。证据 /data/tushare/validation/stk-narrow-followup-probe.json SHA4fc6f7ec889d5231e0b58e440a405370151350fc610513a3bcd00f42b6441311。固定发布1d96532云端核查为 unavailable_no_success_claim，Mac此项仍待镜像结束及核查。原241行样本保留，六个其他分钟接口权限缺口不变。
- 因子月窗口控制helper与idx_anns追加启用helper均已准备且子任务隔离测试通过，尚未生产执行；不要把准备完成计作已落库或提速生效。
- 融资运行时修复后相关39项测试通过，旧638全套针对修复前版本。开户纯合同父9项测试通过；开户运行时待接线。
- 下一步：核查同一镜像handle并完成固定版本云/Mac对照；父审融资两个提交；先解决发现耗时，再验证月范围采集与idx_anns追加启用。原始对象、进度和缺口继续保留云端，Mac只读发布镜像。
