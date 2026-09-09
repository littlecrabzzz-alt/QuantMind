# 下一批15接口与规划提速集成

- root，Mac独立codex/tushare-data-intake；主树631b229继续采集，未暂停/部署。
- 候选已依次pick foreign8 9fab→0379e90、d084→df0d4ea；publish575→4ef183f；stock7 dae→88b79f3、4d6→0056b55。双方registry/store/planner tuple/fixture冲突保留全部组，fixture179。联合测试运行/tmp/tushare-foreign-stock-publish-tests.log。
- text负责history预算循环最小修复；structured与remaining分别准备foreign8/stock7真实probe与固定版验收helper，仅/tmp不提前请求或启用。root集成不改agent同名worktree文件。
- 正式批次需全部候选及脚本备齐、测试通过，再自然排空自己的采集/文档队列，核对Syncthing和Git后发布。权限/空返回按接口记gap继续；history/修订/PIT不视为完成。
