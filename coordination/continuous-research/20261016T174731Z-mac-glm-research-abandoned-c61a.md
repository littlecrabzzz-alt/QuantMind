# 第六条 GLM 持续研究线：用户决定放弃

- 节点、任务：Mac，glm-research-abandoned-c61a；状态：本机停止完成，平台状态写回受认证阻塞。
- 用户决定：本轮未完成工作梳理的第六条「GLM 持续自主研究」放弃，不再推进；不启动新课题、策略验证或收益实验。其余五条仅作工程收口，可在独立范围准备/验证，主目录集成、数据接管与服务切换串行。
- 接续：[此前暂停记录](20260929T0610Z-mac-user-paused-glm.md)。本次是撤出后续计划，不是等待修复后自动恢复。
- 分工：仅停止 `com.quantmind.glm-continuous-research` 及专用 `glm-research-worker` / `glm-research-engine`；不改研究源码，不触及 R01、PDF/OCR、采集及其它服务。历史输入、报告、账本、代码、日志与容器卷保留。

本次发现该 LaunchAgent 仍在运行，控制器近期连续 APIError。已成功 `launchctl disable` 并 `bootout`；实测 disabled 列表为 disabled，服务查询返回不存在，进程查询不再有该 controller/Pi 隔离调用。两个专用容器均已停止，Docker 实测 `state=exited restart=no`，保留容器、卷和原件；Docker 重启后不会因原 `unless-stopped` 策略恢复它们。

现有 `manage.py stop` 返回 `401 platform_auth_refresh_failed`，故没有宣称平台 programme 状态已改为 stopped；不为此恢复认证或继续研究。本机执行端已经停用，该历史状态标记不作为重启理由。`r01-h1-research-agent` 仍 running，PDF/OCR 驱动及识别进程仍在，未对其它服务启停。

五线并行边界：本地化、成果归并和 PDF/OCR 可分别准备；虚拟盘与数据 QA 同时进行工程适配，但正式日更依赖数据验收，迁入 QuantMind 依赖本地化和成果接管。PDF/OCR 复用现有唯一写入者；共享服务启停、主目录合并、数据接管和账本切换由单一集成负责人串行。此次没有启动五线实施或新增研究。
