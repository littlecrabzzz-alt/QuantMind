# 状态核查与接续

- 时间/节点/任务：2026-09-09 14:31 UTC，Mac，01a0817d-7378-7673-9b7f-59c302713981；完整接入仍进行中。此记录回答用户状态询问，不取消原目标。
- 当前主树 master 6b18287，已读更新后的 AGENTS.md。后续按项目共享尚待实现；当前 Tushare 继续云端采集、固定版本单向镜像到 Mac。保留其他研究文件未提交修改。
- 前段部署完成：融资3及开户2运行时经自然排空、master adf4e23 推送、双端 handoff、仅 quantmind/tushare-worker 重启、Mac 客户端更新、8000-8003健康200；14:15:39 UTC consumer已恢复。随后其他任务文档提交6b18287；无消费者遗留暂停。新5接口自动历史默认关闭。
- 融资3实际探测成功：slb_sec 2254、slb_sec_detail 937、slb_len_mm 131行；原始对象和Parquet保存，尚待本批固定版本云/Mac阅读校验。报告 /data/tushare/validation/lending-history3-probe.json，SHA 2baf339ed9f7f9095c51ea0aeaa104dc1959e055574a072bf23246450026e502。
- 开户探测 session95590 本轮确认终止0，等待共享锁48.899秒后实际3次调用。stk_account 2018年51行及真实20181228单日1行，全列对照一致；weekly_hold/weekly_trade为源端空值。stk_account_old返回api_error代码40101，不能当作成功或自行归因权限。报告 /data/tushare/validation/account-history2-probe.json，更新14:24:00 UTC，待取回计算SHA、不可变归档、固定版本云/Mac校验。不要重跑此探测。
- 14:29:51 UTC只读inspect：acquire 32f7abdd、documents70d6505c和原市场任务88fe98db运行；research空闲，相关队列均注册。
- 最新批次14:29:38 UTC为publish_only SoftTimeLimitExceeded，总170.0056秒，requests0；retain_previous95.1659秒、serialize_manifest20.6745秒、coverage_and_closure19.5979秒。CURRENT同时在变化，不能称持续全量发布失败或采集停机。structured_contracts已接只读发布瓶颈诊断，不改生产。
- 14:29:32 UTC云CURRENT data-fc6747298150d36345c840839310d1819d977536a0253d17ecc9550d1db675c2：380050文件条目，已规划状态done50967、empty43894、pending2119354；该动态任务数不是最终范围或数据行数，不计算总完成百分比。云盘可用250982694912字节。
- Mac镜像状态最后成功14:26:13 UTC：verified，data-4cd678b24c40b90e03597a19671539747847055eafd6b6548355357c2e195909，379693文件条目，本次下载912；清单bytes合计47219751547，不等于实际du占用。此时云/Mac版本尚不同。
- 月因子优化候选7307f677已push、agent51项测试通过：单代码1990起历史计划13394→441，近期7日不变。未父审、未上线、未迁移旧未完成日游标，不能计入实际提速。
- 其余待父审候选：发现磁盘缓存b78953f+08a54f6（默认关闭，未证实生产收益）；实时8项2233d3d；只读自选组合2项005c47e。均非已启用。相关独立worktree测试与完整限制见各自ready记录。
- 接续优先级：取得开户报告SHA并归档141000胶囊；完成本批5项固定发布/云Mac阅读校验；诊断发布耗时并父审缓存/月窗口，保护已有游标与历史数据后才做迁移；继续其余候选接线，非阻塞源端缺口保留。分钟独立权限/每日额度、旧互联互通4官方schema、RRG历史成员PIT和交易日缺价未解决。
