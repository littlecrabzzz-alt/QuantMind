# Tushare：按运行证据隔离采集队列

- Mac / tushare-data-intake，发布中；接续 20260908T160755Z-mac-pipeline-tested-e0df15db.md。
- master c969c3d 已推送，双端源代码和 Git 对齐预检通过。
- 云端既有港股行情任务自 23:50 持续运行，不能重启现有 worker。为避免历史回填与研究互相排队，将 Tushare 路由至独立 tushare_acquire 队列，云端 compose 复用现有 worker 配置/镜像，限 1 GiB / 0.75 CPU / 单并发；只启动新增服务并重建 beat，不中断活跃 worker。
- 修改范围仍为本主题持有的 Celery 配置、deploy/compose.cloud.yml 和运行文档。下一步验证解析后的角色/挂载/限制，真实云端续跑和 Mac 镜像；不因此声称全量数据或 RRG 已完成。
