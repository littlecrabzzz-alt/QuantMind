# 模型推理合同

用途：排查模型选错、信号日期错位、输入覆盖不足及推理结果不可消费。统一执行入口是 `router_service.py` 的 `InferenceRouterService` 与 `script_runner.py` 的 `InferenceScriptRunner`。

## 模型与输入

- 用户模型解析经 `backend.shared.model_registry`，优先显式 `model_id`，其次策略绑定、用户默认。目录通常为 `models/users/{tenant}/{user}/{model_id}`。
- 没有隐式内置 `model_qlib/alpha158`；系统模型仅在显式配置 `PRIMARY_MODEL_ID/FALLBACK_MODEL_ID` 和相应目录时参与。用户模型失败不能被无关系统模型的结果掩盖。
- 先核对模型元数据、特征清单、输入日期和股票池，再运行。缺文件、空池或维度不足是失败原因，不是空信号成功。
- 同步 worker 使用 `resolve_effective_model_sync()`，不要为解析模型引入跨事件循环的异步数据库 session。

## 日期与产物

- `data_trade_date`：推理输入数据日。
- `prediction_trade_date`：信号生效日，按市场交易日历取下一交易日；排查节假日时检查实际日历与返回日期，不能仅按周一到周五推算。
- `engine_feature_runs/engine_signal_scores.trade_date` 对齐信号生效日。完成标记和 `qm:signal:latest:{tenant_id}:{user_id}` 用于下游识别可消费版本，不能仅凭子进程退出码宣称信号发布完成。
- 检查返回的 `effective_model_id/model_source/fallback_used/fallback_reason/active_data_source`，将其与实际产物、运行日志关联。
- `INFERENCE_PREDICTION_RETENTION_DAYS` 控制保留窗口；当前 `script_runner.py` 默认 730 天，部署可覆盖。历史文档的 30 天不是当前默认值。

## 排障入口

`script_runner.py` 负责脚本执行、覆盖门禁与写入；`templates/` 是生成推理脚本的运行资源。模型格式和序列输入细节以模型自身 `metadata.json/inference_metadata.json` 及对应 loader 为准，不应从某一次 TFT 实验推导全体模型能力。

推理会写数据库、Redis 与产物，不能当作只读健康检查，也不要为了验证文档而触发真实推理。
