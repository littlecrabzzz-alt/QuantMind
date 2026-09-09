# 风险技术及自动发布修复维护窗口
- 状态：开始短时发布；父任务01a0817d-7378-7673-9b7f-59c302713981，候选91225ac已push，470隔离测试21.014秒及Ruff/diff通过。
- 文件：risk5/technical5/structured schema6与tick发布次序，具体diff在codex/tushare-data-intake；本轮不纳入foreign8 runtime或下一轮publish SQL建议。
- 修正：02:01:04Z采集316请求成功，但publish在serialize_manifest遭SoftTimeLimitExceeded；90秒采集+初始化/规划+约58秒publish总168秒。CURRENT仍ea8，Mac仅收49/111 RRG优先目标。91225ac在interval>0到期tick专做publish，下tick继续采集，保持原160/180秒时限，单独publish未来超时仍为扩展缺口。
- 动作：只cancel两Tushare消费者的新任务接收，不revoke在途；自然排空后旧schema5先SQLite一致备份，再源码快进/handoff/schema6迁移/17请求上限实测/固定版校验后启用，再恢复quantmind与两专属worker。其他US/research/general worker不重启。
- 已向并行“优化本地云端开发交接”任务通知主容器发布协调，请其正式Qlib构建避免此短窗口；其隔离开发继续。维护后补完成记录。
- 帮助脚本已安装业务容器/tmp；风险技术enable SHA046ed6ffc14e42d3bb138af84e7586bdb40d48b6caf331277a33fd7cd09fb1c0；必须按真实文件运行。云端validation/risk-technical-pause.json记录实际暂停、活动task IDs。
