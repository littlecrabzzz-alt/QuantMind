# Electron 桌面端

本目录是 React + Vite 渲染层与 Electron 主进程的开发入口。后端部署与数据准备见[本地 Mac 运行与部署](../docs/部署指南.md)：Main 是开发源码，主业务运行在 Library 受管快照中，不由桌面进程隐式启动另一套后端或接管数据库。

## 开发与打包

在 `electron/` 下执行，命令以 `package.json` 为准：

```bash
npm ci
npm run dev
```

`dev` 同时启动 Vite（3000）和 Electron；只调浏览器页面可用 `npm run dev:react`。

| 命令 | 用途 |
|---|---|
| `npm run build` | 构建 `dist-react` 与 `dist-electron` |
| `npm run build:package` | 按当前平台的 electron-builder 配置生成安装产物，不发布 |
| `npm run build:package:win` | 经 `scripts/package-win.js` 生成 Windows 包 |
| `npm run typecheck` | TypeScript 检查 |
| `npm run lint:changed` | 检查 Git 变更中的前端 TypeScript |
| `npm run test -- --run` | Vitest 非监听运行 |
| `npm run test:e2e` | Playwright 端到端检查 |

构建产物不代表所有平台已验证；签名、系统依赖与安装运行须在目标平台确认。Electron 安装路径异常时先执行 `npm run postinstall`，其修复脚本位于仓库 `scripts/frontend/`。

## 修改入口与边界

- `electron/main.ts`：窗口生命周期、主进程 IPC 与更新；IPC 处理器在 `electron/ipc/handlers/`。
- `src/App.tsx`、`src/features/`、`src/pages/`：路由和业务页面；通用组件在 `src/components/`。
- `src/config/services.ts`：后端地址、服务端口与桌面用户保存的连接配置。本地 HTTP 业务经 API 网关 `http://127.0.0.1:8000`，不要在页面硬编码后端主机；独立沙盒不能与主业务同时占用该端口。
- `src/services/api-client.ts`：通用 HTTP 客户端；认证逻辑在 `src/features/auth/`。凭据不能写进前端源码或 Vite 公共环境变量。
- 管理后台 `/admin/overview` 保留服务健康指标、节点性能历史和「刷新数据」；不提供后端代码更新或服务重启。源码修改不发布到 Library 运行快照，版本查询也不执行更新。
- `src/services/backtestService.ts` 与后端 [Qlib 合同](../backend/services/engine/qlib_app/README.md)：回测请求、状态与结果排障入口。
- QuantBot 的 `src/features/quantbot/services/agentApi.ts` 使用 `/api/v1/openclaw` 网关适配层；聊天以 SSE 接收，不能按旧 WebSocket 演示接入，也不能由组件存在推定上游技能可用。
- `public/` 是复制到构建产物的静态资源；`scripts/` 是本模块构建辅助。目录职责可从源码读取，不另设逐目录 README。

本机后端暂时不可达时，不应为恢复界面而启动另一套数据栈。排查顺序：桌面设置是否仍指向本机 8000、主业务脚本 `status`、`/health`、认证/租户头、网关响应、对应后端服务日志。
