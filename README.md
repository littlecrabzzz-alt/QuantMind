# QuantMind

量化研究与交易平台：Python/FastAPI 后端，Electron/React/TypeScript 前端，使用 PostgreSQL、Redis 和 Qlib。在 Mac 本地开发和运行，源码、业务数据与部署快照分开管理。

## 本地开发

以下命令在仓库根目录执行，用于已准备的独立开发沙盒。先检查状态；启动前确认主业务已停妥、端口与数据卷没有冲突，不直接启动完整 Compose 栈。

```bash
bash scripts/local-dev.sh status
bash scripts/local-dev.sh start core
npm run dev:react --workspace=electron -- --host 127.0.0.1
```

桌面开发用 `npm run dev --workspace=electron` 替代 Web 命令，不重复启动 Vite。操作页面前确认当前 Compose 项目和数据库，避免把主业务库当成测试库。

```bash
npm run typecheck                 # 前端变更
python backend/run_tests.py unit  # 隔离测试环境；不用正式数据库或采集目录
```

后端入口为 `backend/main_oss.py`，由 `SERVICE_MODE` 选择 API、engine、trade、stream。业务服务使用已核准的本地运行快照，见[本地运行](docs/local-primary.md)；隔离开发与服务维护见[运行指南](docs/部署指南.md)。

## 找到实现与文档

| 位置 | 用途 |
| --- | --- |
| [AGENTS.md](AGENTS.md) | 编码助手常驻规则：开发边界、验证、数据和研究约束 |
| [docs/README.md](docs/README.md) | 按任务选择现行指南，区分人工文档与运行时 Markdown |
| `backend/services/`、`backend/shared/` | 服务实现与共享存储、配置、代码格式转换 |
| `electron/` | Web/Electron 界面及前端开发说明 |
| `scripts/`、`deploy/`、`docker/` | 开发、数据和部署入口；执行前确认目标环境 |
| `prompts/`、`skills/` | QuantBot 提示词卡片、技能及参考材料；不是所有会话默认加载的规则 |
| `tools/qmt_agent/`、`tools/bridge-windows/` | Windows 交易桥工具，只有明确交易接入任务才配置 |

市场原始数据由 Mac 采集，校验并发布固定版本后供应用读取。主业务库与沙盒隔离，运行中的研究不自动切换输入版本。

## 使用边界与来源

默认不启用实盘。研究与模拟结果不等于可交易证明；本项目不构成投资建议。

项目遵循仓库 [LICENSE](LICENSE)。集成来源包括 [Qlib](https://github.com/microsoft/qlib)、[RD-Agent](https://github.com/microsoft/RD-Agent) 和 [TradingAgents-Astock](https://github.com/simonlin1212/TradingAgents-astock)；各自许可和运行时模板保留在对应目录。
