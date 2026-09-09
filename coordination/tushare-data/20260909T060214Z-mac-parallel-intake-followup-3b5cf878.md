# 并行接入与提速接续
- 节点 Mac；主树 f627b896f63e96c109ad098503a1dfebcbf0b4be。接续 20260909T055223Z-mac-calendar-factor-runtime-deployed.md。
- 成员 scope enable 实际完成：/tmp/member-scope-enable-output.json；云端 receipt /data/tushare/validation/member-scope-enable-20260909T055627Z-7242ccfa.json；新增1000任务、0上游调用，发布 data-cf01c59247127378fed86d0f5c26d2d9dbe4b5cbe77906e145d540dfaef9f2fb。任务入队不代表下载完成。structured_contracts 接手只读事后验收，禁止重跑 enable。
- calendar5 12次探测已有结果，text_contracts 接手上述固定 release 云端核验；父任务启动标准 Mac mirror，session54224，输出 /tmp/calendar-factor5-mirror.json 与 .stderr。完成后通知 text_contracts 做相同固定 Mac 核验，再决定逐 API 启用。原 helper /tmp/tushare-calendar-factor5-enable.py v2 尚未执行。
- remaining_markets 接手有界隔离紧凑发现缓存评估，不改主树/运行配置、不调用Tushare。已有生产样本发现23.226秒/整轮137.667秒，仅说明该样本占比16.87%，不是整体提速证明。报告 /tmp/tushare-discovery-cache-audit/recommendation.md。
- 保持云端唯一数据写入与账户共享限流；历史采集不等待全接口开发完成，开发/只读校验/同步可并行。无新消费者或限流修改。
- 待办：镜像结束与固定读验收、逐API启用、真实探测/部署/审计归档当前 capsule、完成记录/主计划明确路径提交，保留无关 research 改动。
