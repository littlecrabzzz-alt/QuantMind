# GLM 长期研究执行与额度恢复
- 节点：Mac 沙盒；状态：开发中。
- 用户授权补齐持续研究能力，包含真实余量检测、额度不足等待、恢复后程序重试；保留已有策略运行。
- worktree：`QuantMind.worktrees/glm-continuous-research`，分支 `codex/glm-continuous-research`，起点 `6f4ed993`。
- 范围：GLM quota / Pi 受控执行、外部课题接续与状态界面、必要测试与运维；不改公共 R01 账本与已有策略版本。
- 复用：research_agent 外部课题/存储/回报、R01 公共策略与回测、Pi 会话。运行身份独立于现有 H1/平台账户。
- 主仓与其他 worktree 修改保留；云端 handoff 已通过，当前固定沙盒保留，不切换数据快照。
- 密钥只通过用户指定 Pi 认证命令在受控进程内读取，不写日志/文档。
