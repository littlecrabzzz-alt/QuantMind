# Mac 本地部署入口

- [本地运行与部署](../docs/部署指南.md)：已准备实例的启停、状态、排障和代码快照安装命令；日常操作的唯一指南。
- [运行快照合同](../docs/local-primary.md)：Main / Library 边界、文件选择、manifest、角色、挂载和启动门控。
- [本地市场数据源](../docs/local-market-source.md)：独立采集与校验发布合同。

本目录保存 Compose 覆盖、登录启动模板和构建辅助文件。主业务使用 Library 下已核准快照中的 `scripts/local-primary.sh`；修改 Main 不会自动发布，文件安装也不代表数据恢复或服务就绪。
