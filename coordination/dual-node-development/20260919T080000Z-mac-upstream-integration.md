# 上游完整集成候选
- 用户已要求继续推进全部剩余更新；基线313f41e0，上游bf65f66c，独立worktree /private/tmp/quantmind-upstream-integration，分支codex/upstream-integration-sep19。
- 负责上游diff和19个合并冲突的适配；不修改Tushare独立采集实现，不操作正在运行的服务/数据库。请其他任务避开训练、simulation、market_snapshot、前端入口和部署配置。
- 已迁移本地训练标签purge、WFA独立早停、OOF和独立记账保护至上游拆包结构；不引入torch作为树模型导入依赖。保留断网数据归属、快照新鲜度、原子更新、Qlib内存限制。
- 保留股票池历史表，固定输入缺失时不回退当前缓存，推理交易参考价不回退复权价格。数据库迁移在网络隔离临时容器中验证本地只读dump副本，不更改现有数据库。
- 已通过前端typecheck；后端当前155通过/1跳过，另2项为测试临时data挂载遮蔽SQL文件，调整隔离挂载后复测。候选尚未提交合并至主树。
