# 策略和模型原生登记：导入准备

- 时间：2026-09-12T02:37:35.336423+00:00
- 分支/worktree：codex/strategy-model-research-import，/private/tmp/quantmind-strategy-model-research-import。
- 分工：本任务独立处理 scripts/prepare_strategy_model_import.py；未使用子 agent/Herdr。
- 范围：模型进入现有模型中心，策略进入现有策略库；不修改 Alpha Research、前端、skill 或研究调度。
- 已完成：原模型/信号/股票池逐项对照旧 completion 哈希；15 个准备文件清单验证；2 个策略代码语法通过；模型按既有质量入口得到 candidate，不设默认；策略待保存为 DRAFT、不标已验证。
- 输入：原固定研究目录；输出：/Users/lizeyu/.local/share/quantmind/strategy-model-import/prepared-20260912。尚未写平台数据库，状态 prepared_not_imported。
- 目标节点：当前 127.0.0.1:8000 为 quantmind-dev 本地沙盒。handoff 因云端既有 celery-beat 停止失败，未改云端服务。
- 阻塞：新打开的验证浏览器处于登录页，尚未获得目标账户的认证身份。
- 下一步：用户在验证窗口登录后，使用认证策略 API 和既有模型登记入口写入该账户，再验收模型中心/策略库。低波动策略仍需其专用排名信号及平台执行语义验证，不能宣称复现完成。
