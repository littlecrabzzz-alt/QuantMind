# Mac 本地部署与运维

QuantMind 只在本地 Mac 单机运行。主业务入口是 `scripts/local-primary.sh`，Compose 项目为 `quantmind-local`。Main 工作树是开发源码；日常业务使用 `~/Library/Application Support/QuantMind/primary-runtime-*` 中已核准的独立运行快照，编辑 Main 不会自动更新已部署版本。详细边界见 [本地主节点](../docs/local-primary.md)。

## 当前实例的操作入口

在已核准的 Library 运行快照目录执行：

```bash
scripts/local-primary.sh status
```

需要启停时，在获得相应授权后使用同一目录的 `scripts/local-primary.sh start` 或 `scripts/local-primary.sh stop`。`start` 只用于已具有 `READY`、`AUTHORITY.json` 和恢复验证记录的实例；`stop` 保留数据卷。不要用裸 Compose 启停、初始化 SQL 或删除卷来绕过入口门控。

| 项目 | 本地边界 |
|---|---|
| 主业务数据 | `<运行快照>/.local-primary/project/{data,db,models,logs,user_pools_local}`，以实际挂载为准 |
| API / web | `http://127.0.0.1:8000` / `http://127.0.0.1:3080`，仅绑定本机回环 |
| 容器内 API | 同一 `quantmind-local_quantmind-net` 网络使用服务名 `http://quantmind:8000` |
| 隔离开发沙盒 | Main 中的 `scripts/local-dev.sh` 管理独立 `quantmind-dev` 项目与 `.local-dev` 数据；不得与主业务同时占用 8000，不复用主业务卷 |

## 安装代码快照

在 Main 中使用 `scripts/local-primary.sh install-runtime <新的Library运行目录> <已存在的Library产物目录>`。目标必须是 `~/Library/Application Support/QuantMind/` 管理根内尚不存在的真实目录；产物目录与代码快照分离。安装范围、凭据文件和 manifest 合同见 [本地主节点](../docs/local-primary.md)。

此入口仅安装文件，不启动 Docker、不恢复数据库、不创建就绪状态，也不安装登录自启。新实例恢复或重建须另行明确工具、输入、备份及授权，不能当作一次普通 `start`。

## 只读排障起点

先从运行快照执行 `status`，核对本地 Docker Desktop context、`quantmind-local` 标签、端口与挂载。后端日志可用 `docker logs --tail=200 quantmind-local-quantmind` 读取；其他容器名先从状态确认。API `/health` 只证明端点可达，不能代替数据库、队列和 Worker 状态。修改配置、恢复备份、重建或重启都是有副作用的运维步骤，须单独确认影响。
