# RD-Agent 因子挖掘集成

用途：定位 QuantMind 到 vendored RD-Agent 的市场配置、数据准备和研究循环问题；不是独立部署教程。

## 接入链路

- `rd_loop_wrapper.py` 的 `RDLoopWrapper` 调用 `rdagent.app.qlib_rd_loop.factor.FactorRDLoop`，包装启动、监控、结果提取与取消。
- `market_adapters/` 提供 `MarketAdapter`；市场注册以 `get_adapter/list_markets` 为准。数据、回测参数与环境覆盖由适配器返回，不在前端重复维护。
- `llm_env.py` 统一构造模型环境；聊天/嵌入服务、密钥和 provider 前缀须由实例配置提供。不能将源码中有某适配器视为其数据和模型服务已可用。
- 包装器准备 HDF 因子输入，并可将 QuantDB `features_daily/l1_factors` 富化列合入。检查输入数据范围、列、索引及缓存来源后再启动研究。

## 必须随包保留的资源

- [`alphaagent/.../factor_data_template/README.md`](../../../../alphaagent/scenarios/qlib/experiment/factor_data_template/README.md) 描述实际输入字段；其 `experiment/utils.py` 将它复制到因子数据目录供模型读取。
- [`rd-agent/`](../../../../rd-agent/README.md) 中 Qlib 工作区模板、数据说明和 prompt/spec 文件是上游运行资源，不因扩展名为 Markdown 而删除。
- 包装器会追加中文输出与用户研究方向到上游提示模板。修改模板影响实际模型行为，不是纯文字美化。

## 排障边界

先核对市场适配器、provider/HDF 路径、数据覆盖、模型环境，再用任务日志关联 RDLoop 阶段与提取结果。运行研究会调用模型、生成代码并执行实验；不要在文档检查、安装探活或迁移只读验收中启动它。
