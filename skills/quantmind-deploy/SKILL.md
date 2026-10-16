---
name: quantmind-deploy
description: "QuantMind 可选部署与运维：部署前环境确认、服务健康检查、部署失败排查、数据库初始化和更新。触发词：部署、部署失败、装不上、数据库初始化、服务起不来。"
---

# 部署与运维

此技能由 QuantBot 按需读取，不要求向根 `AGENTS.md` 复制正文。脚本安装方式见仓库 `/quantmind/skills/README.md`（本地为 `skills/README.md`）。

## 先确认环境

1. Mac 是唯一开发源，远端开发已退役；不能据此假定运行服务、数据库或数据已经迁移。先识别用户要操作的实例、Docker context、Compose 项目、env 文件和 override。
2. QuantBot 通常运行在 QwenPaw 容器：同一网络的 API 示例为 `http://quantmind:8000`；宿主机地址以实际端口映射为准。容器名、地址和挂载均须核对，不能照抄旧服务器 IP。
3. 检查实际挂载及数据所有者；代码仓库不是运行数据目录。不要对未知实例运行裸 Compose 启停、删除卷、初始化数据库或恢复数据。
4. 不执行远端开发 handoff、双向代码同步或将服务器变成第二开发源。

## 任务入口

- 完整部署、在线部署、更新脚本及副作用边界：读取 `/quantmind/deploy/README.md` 与 `/quantmind/docs/部署指南.md`（宿主机使用仓库相对路径）。
- AutoDL 仅作为可选训练 Worker：读取 `/quantmind/deploy/autodl/README.md`，不在 GPU 实例部署整个平台或生产数据库。
- 数据路径与口径：读取 `skills/quantdb-data-structure/SKILL.md` 和 `skills/quantdb-fields/SKILL.md`。
- 技能或人格初始化：读取 `scripts/quantbot_init.sh` 后选择 `--skills-only` 或 `--persona-only`；不要通过手工复制绕过技能池注册。

## 健康检查与定位

只使用已经识别的目标 Compose 参数：

1. 查看 `config --services` 与 `ps`，服务数量和名称从配置读取，不维护固定清单。
2. 查看故障服务 `logs --tail=200 <服务>`，记录第一处根因与时间；API `/health` 成功不代表 Worker、数据库或队列健康。
3. 检查实际端口、容器网络别名、挂载、磁盘空间及镜像依赖是否匹配；不要因容器名相似就操作另一个项目。
4. 数据库报缺表先确认连接的是哪个数据库和迁移状态。初始化 SQL、升级补丁或备份恢复都可能写入数据，不能作为无条件重试。
5. 需要修复时先给出目标、影响和回滚所需备份；重启、重建、覆盖配置、恢复或清理数据必须明确授权后执行。

输出目标实例、观察到的状态、根因证据、已执行动作与未验证边界。不要把一次历史验收或部署脚本存在当作当前实例已可用的证据。
