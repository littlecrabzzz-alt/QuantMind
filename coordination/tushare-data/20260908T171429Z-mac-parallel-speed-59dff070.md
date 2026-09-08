# Tushare：并行合同与生产提速
- 节点/任务：Mac，full Tushare goal；父工作树 codex/tushare-data-intake。
- 接续 20260908T164603Z-mac-full-goal-start-a35bc190.md。
- 合同：9 text + 26 structured + 23 market 已提交集成到候选分支；PDF helper 7项离线测试通过。父负责 pipeline/registry/mirror/progress/ledger；text agent 当前负责 store + 新测试，structured agent负责独立扩展pipeline测试；不触碰其他任务的双端快照/研究功能。
- 生产：主树/云端 HEAD 9676ae0，4278源文件hash一致，handoff通过。只暂停専属Tushare consumer，确认自身active为空后配置240rpm、360请求/100秒并重启 tushare-worker；云端已迁移v2并恢复消费，实际吞吐待首批结束。其他 run_market_scheduled_sync 未中断。
- 云端 pypdf 确认存在。v3候选仍隔离未部署；历史完整性、附件队列、API消费、其余目录继续推进。
