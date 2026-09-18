# Tushare 供应商当前不可用接口低频复查生产验收完成

- 时间、节点：2026-09-18T17:38Z，Mac 全量归档唯一写入者。
- 状态：本次逻辑、测试、合并、部署和真实复查已完成；全量历史补采继续运行，尚未宣称全量完成。
- 分支、提交：候选 `codex/tushare-api-unavailable-reprobe-20260919` / `1e45617c`；已合入并推送 `master` 的 `393197b10b61b720094e23eea88d1c2df820b451`。
- 接续：`20260918T171804Z-mac-api-unavailable-reprobe-start.md`。

本次完成：供应商精确返回业务码 40101“请指定正确的接口名”时，结果仍保留为 `api_error`，另记录 `supplier_api_unavailable` 与 API/src 能力状态；同范围新任务直接进入 `blocked`，避免重复消耗请求。七天后复用原 `permission_reprobe_max_scopes` 有界调度一条代表任务；真实成功才恢复同范围中无结果或 `api_error` 的阻塞任务。权限拒绝、其他 API 错误、账户/API 限速和每日总量逻辑保持独立。固定覆盖审计现在把该状态报告为 `supplier_api_unavailable`，不会伪装成权限拒绝、空数据或完成。

验证：完整 Tushare 套件 1,362 项通过、5 项跳过，日志 `/tmp/qm-tushare-full-suite-api-unavailable-v1.log`，SHA-256 `383d231e03c7c97ae9685818c9409370597f6d5c93f60369ed10485b15bca807`；ruff、py_compile 与 diff check 均通过。部署前让旧写入周期自然排空，运行副本与 `master` 的 intake/pipeline SHA-256 一致，ENABLED 与 archive.env 仍为 0600；新 LaunchAgent PID 83993 运行且从未退出。

生产验收：首次规划只读 11 个旧 `blocked/api_error` 原始响应，建立 11 个 `api_unavailable` 能力状态，原 11 个结果和 11 条 attempt 均保持，`upstream_calls=0`。其中 4 个旧证据已超过七天，调度器按上限选择 `stk_account_old`、`film_record`、`teleplay_record`、`bo_monthly` 各一条代表任务；下一真实周期均得到 HTTP 200 / 业务码 40101，各新增一条 attempt、状态回到 `blocked`、能力时间刷新并带 `supplier_api_unavailable=true`。同轮完成 694 次结构化请求和 2,485 份文档，失败阶段为空。当前能力汇总为 `api_unavailable=11`、`permission_denied=33`。

下一步：本地全量采集持续运行；其余过期代表任务会在后续 15 分钟规划轮次中每轮最多调度 4 个，复查后进入七天冷却。发布新固定版本后重新生成覆盖审计，届时 11 个接口应由笼统 `api_error` 收敛为可观察的 `supplier_api_unavailable`。云端继续只运行研究缓存 timer，不启用全量写入者。
