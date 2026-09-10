# Tushare 对账预算、Connect 与 RRG 审计集成记录

- 时间/节点：2026-09-10 04:27Z，Mac集成，云端数据权威`lzy-vm`。
- 集成提交：`840e7d2b`、`6c7ed745`、`0c367391`、`1cda5e42`、`aff29192`、`5de3ec17`、`c07f176f`；最终`master=c07f176f81d3c22fbef573e86e328bf9624213e9`，已push并完成Mac→cloud Git handoff。
- 生产发布：采集consumer先停止接新任务并自然排空，只重启`tushare-worker`加载纯Python变更；恢复后healthy、OOM false。最终consumer已恢复。batch360/90秒、账户与灰度500rpm、规划/发布900秒均未改。
- 生产验证：两个原子`identifier_fanout`仍分别需102.781/108.592秒、0上游调用并生成1044子任务；待拆父任务随后为0。普通批`a4d49e6f-8521-4cb1-9d71-b227e8f1cbc5`为360请求、pipeline63.203秒、总90.356秒。收据`/data/tushare/validation/reconciliation-deadline-20260910T0426Z/acceptance.json` SHA256 `fecc73dcf2c397adcf07db93be35bb7b357721adc423d2752a8e232736ddca20`。
- 范围：新增`moneyflow_hsgt`和`ggt_daily`为默认禁用的可读合同，冻结命名范围runtime可读229/236；7项剩余分类明确。文档锁只增测试和证据，不改运行码。RRG四年窗口审计只读固定版并输出未入队参数，状态保持`blocked_data`。
- 验证：候选分支分别完成Python3.10全量895项、文档68项、RRG6项及Ruff。最终带完整仓库与依赖的主工作树Python3.10联合回归903项全部通过、skipped5；Ruff check与`git diff --check`通过。云容器另一次因`.git`/`deploy`未挂载及子进程环境产生9项错误，仅用于确认环境边界，不作为最终测试结论。
- 数据边界：不包含Token、订单或生产密钥；没有从Mac回写权威数据，没有把当前成员或ETF生命周期推成PIT行业映射，没有补价格、收益或交易结论。
