# 并行采集提速部署与接续
- 节点/任务：Mac，01a0817d-7378-7673-9b7f-59c302713981；云端正式数据唯一写入者。
- 状态：本批部署，完整接入目标仍进行中；main master已集成487b581，相关代码c864a24已双端核对。
- 本批：v4分区闭环、97注册合同、15类other实测并启用、真实API/QuantBot查询、v2文档分片、稳定十年周月分区、具名API限额隔离、2下载/1解析、rsync压缩。159项专项隔离检查通过。
- 实际证据：云端validation/{v4-deployment,api-agent-acceptance,other-probe,global-other-recovered,parallel-speed-deployment}.json；Mac固定data-bad7ca3db1f1a31565355a5116195f47046109f245f918c55527f05c324786c1的52692文件校验/5类other禁网读取通过。
- 重点限制：hk_daily真实1次/小时，持久配置3605秒；只能按实际权益估时。两个已因限频终止的旧任务恢复pending，保留所有尝试。期权满页是完整性待拆分，不是无权限。
- 接续：先确认两专属消费者运行且限频隔离后吞吐/双下载结果，详见docs/tushare-progress.md；再接入5个supplement候选（b1a417d原提交，7e8b12e已在main），目前未注册或实测。补全263目录、历史版本清单闭包/修订/历史边界与PIT，RRG保持blocked_data。
- 本批所有子执行者文件已释放；无新的用户任务。保留主树其他研究任务未提交文件。
