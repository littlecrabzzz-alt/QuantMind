# RRG 21+90定向队列调整：候选待父审查

- text_contracts/Mac，承接20260909T011825Z-mac-rrg-structured-queue-diagnosis-e268ab28.md；仅新增/tmphelper/test/readme，未执行生产、未改仓库runtime/config。
- Helper `/tmp/tushare-rrg-priority-window-candidate-20260909.py` SHA1d79c0a7323ecb6939043970bf62a82df5600bcba9226c7875563f6ea112244d；说明 `/tmp/tushare-rrg-priority-window-candidate-20260909.md`。
- 既有非阻塞pipeline.lock+authority+schema5限定；现有Pipeline.enqueue只补缺history，已有精确请求保留原logical identity；近期21个slots只处理已存在pending；研究90slots为20210517及20260831向前29日，date/API轮转，优先级仅向24提升，非pending不重置。
- 单SQLite事务，configSHA/planning全行前后对照；authorizer拒绝jobs INSERT/priorityUPDATE之外任何表写入，保持tries/result/state/attempts/groupweights/cursors。prepared证据fsync在commit前，独立committedreceipt在commit后；prepared单独存在不算成功，崩溃后需只读核对。所有精确jobID与before/after/old-newpriority写入唯一证据。
- 临时SQLite真实Pipeline测试：首87新增/22提级（含21recent中2done/empty保留、3history已存在），复跑0变化；其他job/attempts/config/planning及原行非priority字段不变。故意planningUPDATE被authorizer拒绝并回滚。py_compile通过；无上游/凭据/手动publish，候选本身尚未在云端运行。
