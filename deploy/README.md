# 可选部署与更新任务

Mac 是本仓库唯一开发源；这里的 Ubuntu 部署脚本是**明确指定目标后才执行的运维工具**，不是日常开发流程，也不表示远端运行服务、数据库或数据已经迁回本地。当前环境与数据边界见 [部署指南](../docs/部署指南.md)。

## 选择脚本

| 任务 | 入口 | 执行前确认 |
|---|---|---|
| 新 Ubuntu 节点在线部署 | `sudo bash deploy/deploy.sh --ref <分支或tag>` | 目标目录、网络、凭据和独立数据来源 |
| 从完整包部署 | `sudo bash deploy/full-deploy.sh` | `QUANTMIND_OFFLINE_BASE_URL` 包内容、校验和与数据覆盖范围 |
| 更新已有 Ubuntu 部署 | `sudo bash deploy/update.sh --ref <分支或tag>` | 目标实例、备份、停机影响；`--no-build` 仅用于不需新依赖的更新 |
| 可选 AutoDL GPU Worker | [autodl/README.md](autodl/README.md) | 仅卸载训练，不迁移开发源或生产数据库 |

脚本默认项目目录和支持系统以对应脚本开头配置为准。不要在本地工作树调用服务器更新脚本；`--force` 会覆盖目标未提交代码，不能用来解决开发目录冲突。

## 数据与镜像

- 完整包中的镜像、业务目录、PostgreSQL 和 QwenPaw 持久卷是不同资产。`QUANTMIND_REPLACE_QLIB`、`QUANTMIND_REPLACE_BUSINESS_DATA`、`QUANTMIND_REPLACE_DATABASE`、`QUANTMIND_REPLACE_QWENPAW_DATA` 都是有意覆盖开关，不作为常规部署参数。
- 部署前核对实际挂载和当前数据所有者，保留备份；不要用旧服务器路径或 Git 目录存在性判断数据已迁移。
- `deploy/req-fingerprint.sh` 计算镜像依赖指纹，构建时传入 `QM_REQ_SHA`；完整部署会比对镜像 Label `qm.req.sha`。指纹不同可能触发联网重建，纯离线环境需准备匹配代码的镜像。
- Compose 项目名、env 文件、override、服务数量和端口必须取自目标实际配置。不要直接在未知目录运行裸 `docker compose up`、`restart` 或 `down -v`。

## 只读排障起点

先确认本机 Docker context 和目标 Compose 参数，再使用同一组参数读取 `config --services`、`ps`、`logs --tail=200 <服务>`。API `/health` 只证明该端点可达，不能代替数据库、队列和 Worker 状态。修改配置、恢复备份、重建或重启属于另一个有副作用的运维步骤，须单独确认影响。
