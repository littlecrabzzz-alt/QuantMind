# 13 接口已部署/镜像；下一批候选和性能迁移待验收

- 接续205632Z记录；本轮属于进展。父候选HEAD1aaed2f，生产代码b0e1845双端handoff passed（4425文件，SHA598114fae437a119e435fc3d014333576ed7ea09acd142b078253830e24607ed）。后续提交只为文档/台账/测试/协调，不需重启。正式pipeline schema仍v4。
- 所有采集/文档队列已经恢复，不能再当成暂停状态。最近实际acquire55ce1720-6d66-477d-ba2d-92dd7206395b、documents f01803b9-e75e-40f6-88f9-e089467f1c9d活跃；随后21:19:46Z已完成266请求，21:19:42Z文档39阶段完成。active任务必须重新查询，不据此旧ID启动重复批次。
- 已注册122数据集+6财务别名；本批期货7/财务研究6实际17请求，共9868原始行，全部13非空。144字段原值与Parquet一致；mainbz P/D/I=35/10/4。所有13在Mac禁网、禁止凭据下固定release读取通过。
- 固定验收release data-e3d0b8e8d539fb775b226e3e8799b131591e1b3c34965384ae7b287ef3adfcd5、81278files。云端validation/extra13-probe.json、extra13-empty-discovery.json、extra13-acceptance.json；Mac /tmp/tushare-extra13-mac-verified.json（source→Parquet+query全部13）。这些不是全历史完成证明。
- 初始futures_extra被6个DCE下划线源代码阻塞：L_F/L_FL/PP_F/PP_FL/V_F/V_FL（.DCE）；纯合同正则已修，21:16:10Z实际validation_passed。修复不是过滤掉异常代码。
- 饱和：stk_surv400→5909证券子任务（universe_complete=false）；fut_holding4000仍需exchange/symbol成对分片；fut_weekly_detail无条件4000仅本次2019—2020返回，混合week编号20191/201904，当前padding计划的覆盖要补核验。fut_weekly_monthly期标签20260904却带end_date20260831/20260907/20260908，原值保留，语义/PIT仍gap。不要声称这些source异常已经解决。
- Mac LaunchAgent曾指向已清理uv临时环境，退出78。已用持久 `~/Library/Application Support/QuantMind/tushare-client/.venv/bin/python -I` 修复并成功自动镜像，last exit0；安装helper会离线复用健康venv。root /tmp/tushare-extra13-mac-verify.py和各probe/accept脚本可读但不要盲重跑采集。根无仍运行exec会话需要接管。
- 实测timing首批263/90.028s、总110.677s；第二批266/90s、总110.843s，initialize2.524、planning4.202、archive5.050、publish8.202。/tmp/tushare-extra13-runtime-status.json保存第二批及文档状态、free302.64GiB，无需扩容。配额仍240/min；hk_daily学习门是5/天/17280s，不是旧1小时。
- 250项全Tushare回归通过；新增目录一致性连同旧目录检查5项通过。原36特殊页全部分类复核，台账保留263基线另加11正文链接，rt_k/rt_etf_k未知独立权限，缺页6个不推定端点，pro_bar属SDK、fut_tick属CSV交付、p_save/p_delete不采集。分类不等于子API完整。目录外188/422只列seed；代理随后复核发现正文404，待下一纯合同delta整合其证据。

## 下一步（候选尚未合并/部署）

1. 优先性能迁移候选 **6ce645cb1acd8c7fc7b5e3b6c732732c0a133a43**，独立worktree `/Users/lizeyu/.codex/worktrees/quantmind-tushare-queue-index`（核对实际path）、分支codex/tushare-queue-index，基于b0e1845，不含信用候选。v5三个partial索引+next_job/expand的INDEXED BY；41测试包括迁移失败rollback、幂等、公平及gate一致。父需审查、合入、全回归、生产一致性SQLite备份、自然排空后发布；确认没有旧v4-only进程会重新打开v5，回退需保留v5兼容判断。模拟收益不是生产吞吐保证。
2. 信用7运行候选 **2a4bbb1d444e9141ec8eeff970c8742a65e40dee** 在structured原worktree，基于d83c402；40测试。stage credit_extra registry/store/mirror名单一行、plan/gap/signature/identifiers仅margin_secs+stocks/ETF，未改tick/normalize/records/_dataset。父应只pick此delta，避免带其未需要历史。之后真实权限/字段/日期轴/饱和审查、配置启用及Mac验收。
3. text_contracts正在做目录外实时两API纯合同；rt_k372/rt_etf_k400仍有官方正文；hk_hold188/dc_concept_cons422当前正文404，只保留gap，不编合同。收到其ready提交后再集成，未完成的212252Z开始记录留未提交。
4. RRG消费前置说明见205934Z ready记录；已有固定行业价格切片通过，纯坐标适配/因果技术验收可并行，尚未做。分类历史/known_at/ETF门槛不变。不动其他用户研究配置/文档/脚本。

完整目标仍active：全可用数据、原文/全部字段/历史版本、云端持续采集与Mac完整镜像、API/Agent消费、缺口逐项补齐。不要以本批验收或待办还在运行标记完成。
