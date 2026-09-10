# Tushare 精确批次继续开始

- 时间/节点：2026-09-10T15:46Z，Mac 主集成人；基线 `4b359b29076ff6336cd5b5d52eb26268217794f9`。
- 并行只读审计财务第八批、`fund_nav` 第三批及 `fund_share` 精确执行路径；不得访问生产SQLite、凭据或Tushare，代码工作必须位于独立worktree。
- root等待当前任务自然终态后暂停Beat并停稳专用worker，重新冻结新manifest；所有生产批次串行占有共享锁，不复用旧清单，不发布或切换CURRENT。
- 100GiB停线、500rpm账户闸门、接口分层频控及360请求/90秒硬边界保持。
