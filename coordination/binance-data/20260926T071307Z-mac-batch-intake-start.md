# 币安批量补录与现有数据验证
- 用户授权验证现有数据，批量补录常见币种与官方可核实A股相关、少量美股产品；已选择默认代表性范围。数据准备，不涉及下单/策略运行。
- 继续使用候选worktree `/Users/lizeyu/.codex/worktrees/quantmind-binance-data-20260926`，基线afc8ef80；不覆盖主树的研究改动。
- 复用现有Spot原始响应、发布/质量/Qlib/H5链路；扩大池用新root，保留原BTC/ETH日更池和已有固定研究版本。A股相关永续另用公共历史归档，真实类型/底层映射单独记录，不开放crypto研究准入。禁止绕过fapi地区限制。
- root负责现货登记、隔离采集/发布、证据和批次清单；products只读官方产品核实；data_fetch只读已有数据/调度验收；execution_audit负责新股票永续archive脚本/tests，不动核心Spot代码。
- 本轮不接管共享服务重启窗口。候选先本地隔离验证，符合条件后新增云端批次目录；旧CURRENT/调度、业务库与运行中研究保持原样。
