# Electron 与 Web 构建

用途：在本地开发前端、构建桌面包，并定位连接或产物路径错误。命令以根 `package.json` 与 `electron/package.json` 为准；前端不包含可替代后端的数据与服务。

## 开发

在仓库根目录安装锁文件中的 workspace 依赖：

```bash
npm ci
npm run dashboard:dev
```

`dashboard:dev` 同时启动 Vite（默认 3000）和 Electron。只需浏览器时：

```bash
npm run dev:react -w QuantMind
```

后端操作见 [运行与部署](部署指南.md)；先确认当前连接的是本地隔离后端还是已有远端服务，不自动切换或启动另一套后端。

## 连接配置

`electron/.env.template` 是配置模板，不覆盖已有私有配置。常用字段：

- `VITE_API_BASE_URL`：HTTP API 根地址；开发代理的 `VITE_API_URL` 也会影响目标地址。
- `VITE_USER_API_URL`：可选认证地址，若显式配置，应包含 `/api/v1`；未设置时由 API 根地址派生。
- `VITE_WS_BASE_URL`：WebSocket 地址，使用 `ws://` 或 `wss://`，不要用 HTTP URL。

构建后的地址不是靠修改已安装应用旁边的 `.env` 动态替换的。修改前先核实 `electron/vite.config.ts`、客户端配置和构建环境。任何 `VITE_*` 或前端注入值都可能出现在客户端包中，不得存放服务端密钥。

## 构建与打包

```bash
npm run dashboard:build
npm run build:package -w QuantMind
```

第一条只构建 React 与 Electron，不生成安装包；第二条调用 electron-builder，默认不发布。输出在 `electron/dist-react/`、`electron/dist-electron/`，安装包在 `electron/dist/`。

Windows 专用包装入口：

```bash
npm run dashboard:package:win
npm run dashboard:package:win:dir
```

`dir` 用于未安装目录包。平台目标、架构、图标和签名设置由 `electron/package.json` 的 `build` 字段控制；不要假定在 macOS 上能完成全部 Windows/Linux 原生依赖打包。正式分发需自行配置并检查签名、平台权限和更新源。存在 publish 配置不代表自动发布或更新服务已经可用。

## 排错顺序

| 现象 | 先检查 |
| --- | --- |
| Electron 等待窗口或开发启动失败 | 3000 是否被占用；Vite 是否启动；Electron 路径修复脚本是否在安装期间成功 |
| 空白窗口 | `dist-react/index.html`、`dist-electron/electron/main.js` 是否生成；主进程日志中的加载路径 |
| API 404/认证失败 | API 根地址、认证地址的 `/api/v1`、代理目标和实际后端；不要先清空用户数据 |
| WebSocket 不通 | URL 协议、路径、反向代理升级配置与后端实际监听入口 |
| 安装包失败 | 目标平台依赖、下载网络、`build` 资源、签名日志；不要把关闭安全设置当正式发布修复 |

可用检查命令：`npm run typecheck`。构建/测试由实际改动任务决定，本指南不声明任何平台包已经验收。
