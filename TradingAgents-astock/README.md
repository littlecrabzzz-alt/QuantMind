# TradingAgents-Astock：集成源码

用途：保留 A 股多 Agent 投研组件的来源、关键修改入口与运行边界；此目录不是 QuantMind 的独立部署入口。

## 来源与许可

- A 股 fork：[simonlin1212/TradingAgents-astock](https://github.com/simonlin1212/TradingAgents-astock)。
- 原始框架：[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)；本 fork 记录的基线 commit 为 `7e9e7b8`（2026-05-04）。
- Apache License 2.0；完整许可与归属保留于 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。QuantMind 集成不表示原作者背书。

## 修改与排障入口

- `tradingagents/graph/`：分析、研究辩论、交易与风险决策图。
- `tradingagents/agents/`：模型提示和角色实现；A 股 fork 在基础角色外增加政策、游资与解禁分析。
- `tradingagents/dataflows/a_stock.py`：A 股数据工具；代码中存在某个上游 HTTP/TCP 接口不等于该接口当前可用，也不替代 QuantMind 的数据事实源。
- `tradingagents/llm_clients/` 与 `default_config.py`：模型客户端及运行配置。供应商可用模型和密钥由实例配置决定，不能从历史样例报告推定。
- QuantMind 网关集成在 `backend/services/engine/routers/trading_agents.py`，从项目[主入口](../README.md)配置和使用；不要为修复集成而先启动 vendored Web UI。

`pyproject.toml` 将本 README 作为包元数据读取，打包时必须保留。Python 依赖、可选 provider 和版本约束以该文件为准，不照抄旧 issue 中已经过期的 akshare/httpx 安装建议。

## 免责声明

本组件仅供学习研究与技术演示，不构成投资建议。AI 生成的分析和信号可能有错误；投资决策应咨询持牌专业机构。作者不对使用本工具造成的投资损失承担责任。
