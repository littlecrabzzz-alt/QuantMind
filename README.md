# QuantMind

量化研究与交易平台：Python/FastAPI 后端，Electron/React/TypeScript 前端，使用 PostgreSQL、Redis 和 Qlib。此工作树以 Mac 为唯一开发源；代码提交不等于服务发布，也不迁移数据库。

## 本地开发

以下命令在仓库根目录执行。已有本地沙盒时，先检查状态；首次初始化、恢复或切换后端前先确认现有卷和任务，不直接启动旧完整 Compose 栈。

```bash
bash scripts/local-dev.sh status
bash scripts/local-dev.sh start core
npm run dev:react --workspace=electron -- --host 127.0.0.1
```

桌面开发用 `npm run dev --workspace=electron` 替代 Web 命令，不重复启动 Vite。操作页面前确认实际后端节点，不能凭浏览器运行在 Mac 或地址为 `localhost` 判断数据库归属。

```bash
npm run typecheck                 # 前端变更
python backend/run_tests.py unit  # 隔离测试环境；不用正式数据库或采集目录
```

后端入口为 `backend/main_oss.py`，由 `SERVICE_MODE` 选择 API、engine、trade、stream。普通开发使用本地沙盒；可选 Linux 部署见 [部署指南](docs/部署指南.md)，不能把新实例部署命令用于覆盖现有数据。

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

市场原始数据由 Mac 采集；云端若继续提供服务，只消费已校验版本。本地业务库不整体回灌，运行中的研究不自动切换输入版本。

## 使用边界与来源

默认不启用实盘。研究与模拟结果不等于可交易证明；本项目不构成投资建议。

项目遵循仓库 [LICENSE](LICENSE)。集成来源包括 [Qlib](https://github.com/microsoft/qlib)、[RD-Agent](https://github.com/microsoft/RD-Agent) 和 [TradingAgents-Astock](https://github.com/simonlin1212/TradingAgents-astock)；各自许可和运行时模板保留在对应目录。
