---
name: quantmind-deploy
description: "QuantMind Mac 本地部署与运维：local-primary 运行快照、服务健康检查、启动失败排查及隔离沙盒边界。触发词：部署、部署失败、装不上、服务起不来、本地运行。"
---

# 部署与运维

此技能由 QuantBot 按需读取，不要求向根 `AGENTS.md` 复制正文。脚本安装方式见仓库 `/quantmind/skills/README.md`（本地为 `skills/README.md`）。

## 先确认本地运行边界

1. QuantMind 只在本地 Mac 运行。Main 是开发源码；主业务使用 `~/Library/Application Support/QuantMind/primary-runtime-*` 中已核准的运行快照，入口是该目录的 `scripts/local-primary.sh`。Main 编辑不会自动更新业务运行版本。
2. 主业务 Compose 项目为 `quantmind-local`，数据在 `<运行快照>/.local-primary/project/` 与该项目独立卷内。核对本地 Docker Desktop context、实际挂载、env 文件和 override；代码目录不是业务数据目录。
3. 同一 `quantmind-local_quantmind-net` 网络内，QwenPaw 调 API 用服务名 `http://quantmind:8000`；Mac 宿主机用 `http://127.0.0.1:8000`，web 用 `http://127.0.0.1:3080`。
4. Main 中 `scripts/local-dev.sh` 管理独立 `quantmind-dev` 沙盒与 `.local-dev` 数据，不复用主业务卷；沙盒与主业务不能同时占用 8000。

## 任务入口

- 当前本地运维边界：读取 `/quantmind/deploy/README.md` 与 `/quantmind/docs/local-primary.md`（宿主机使用仓库相对路径）。
- 在已核准的运行快照目录用 `scripts/local-primary.sh status` 查看状态。已授权的启停分别用同目录 `scripts/local-primary.sh start` / `stop`；`start` 要求实例已有 `READY`、`AUTHORITY.json` 及恢复验证记录，不能作为首次初始化或通用恢复入口。
- 代码快照安装：Main 中的 `scripts/local-primary.sh install-runtime <新的Library运行目录> <已存在的Library产物目录>` 只安装文件，不启动服务、不恢复数据、不创建就绪状态。完整路径和 manifest 合同按 `docs/local-primary.md`；新实例恢复或重建另定任务。
- 数据路径与口径：读取 `skills/quantdb-data-structure/SKILL.md` 和 `skills/quantdb-fields/SKILL.md`。
- 技能或人格初始化：先查运行工作区已安装的技能，读 `scripts/quantbot_init.sh` 与 `skills/README.md`。Library 运行快照不默认包含 `skills/` 安装源，缺失时须另行准备完整源树；在本地 QwenPaw 容器内选择 `--skills-only` 或 `--persona-only`，不要照抄脚本的宿主机默认 8088 地址或裸 `qwenpaw` 容器名。

## 健康检查与定位

1. 从已核准运行快照执行 `scripts/local-primary.sh status`，确认 `quantmind-local` 服务及 8000 归属；不要启动沙盒来替代故障主业务。
2. 按状态中的实际容器名读取 `docker logs --tail=200 <容器名>`，记录第一处根因与时间；API `/health` 成功不代表 Worker、数据库或队列健康。
3. 检查实际端口、容器网络别名、挂载、磁盘空间及镜像依赖；需要读取 Compose 配置时沿用 `local-primary.sh` 中完整的 project/env/overlay 参数，不运行裸 Compose。
4. 数据库报缺表先确认连接的本地项目、数据库和 schema 迁移状态。初始化 SQL、升级补丁或备份恢复都可能写入数据，不能作为无条件重试。
5. 需要修复时先给出目标、影响和回滚所需备份；重启、重建、覆盖配置、恢复或清理数据必须明确授权后执行。

输出目标实例、观察到的状态、根因证据、已执行动作与未验证边界。不要把一次历史验收或部署脚本存在当作当前实例已可用的证据。
