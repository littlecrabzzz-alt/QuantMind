# v5 索引与信用7集成开始

- 父worktree quantmind-tushare-data-intake 基于e7eedbf；已pick性能6ce645c→c843b73、信用2a4bbb1→9a42da7、实时纯合同bb24b33→2e4ce32。生产仍e7eedbf/schema4，本阶段尚未发布。完整目标保持active。
- 父负责129数据集通用fixture、候选审查/测试、备份/迁移/发布、7真实请求/本地镜像、台账和进度。structured新分支只负责split_request及期货观察值成对/周编号分片helper与新测试，不动父迁移/next_job/expand/tick；text只做PCF471/472纯合同；remaining信用probe spec已交付/tmp/tushare-credit7-probe-spec.json后待命。
- v5索引保持原查询谓词/公平/限频/排序，迁移前须正式一致性SQLite备份，自然排空后同步发布，旧v4-only代码不能直接打开v5。实时两接口只保存纯合同，尚未注册/调度，不得绕过实时过期拒绝与实际观察时间门槛。
- 非阻塞历史/权限/满页缺口仍逐项保留；不改其他用户研究文件/正式结果。队列是否暂停以最新实际操作为准，此开始记录时尚未暂停。
