# 第5线三点缺陷修复与第4线动态readiness（复核轮）

- 节点、任务：Mac，ocr-three-fixes-dynamic-readiness-91b4；接续 182647Z/193500Z/195800Z/201500Z 四记录。分支 HEAD=1a58c387。

## 第5线（父指出的三行为缺陷全修，38项测试+ruff全过）

1. 锁/备份安全（pdf_maintain.py 重写）：协调器专属非阻塞 flock（root/.maintenance-coordinator.lock）覆盖整个 pass——并发两维护不再互覆备份；遗留 .ENABLED.maintain-backup：ENABLED缺失→显式恢复、两者并存→冲突延期不动任何文件，绝不覆盖/删除陌生备份；仅恢复本次确实移动的 ENABLED；pause/resume 检查返回与实际状态（bootout 后验证 stopped、bootstrap 后验证 running），resume 失败/抛错只告警、绝不跳过 ENABLED 恢复；pause 失败→中止且不 resume。fixture 10 项覆盖并发/忙/异常恢复/原stopped不强启。
2. driver 最终 drain（pdf_text_driver.sh）：no_candidates 时若 staging 有待入库 {sha}.json→强制 maintain（无视24h标记），busy(75) 按退避持续重试、绝不留未入库文本退出；无待入库才走常规 maybe_maintain。fixture 2 项（入库成功退出/busy重试不退出）。
3. busy 恢复真实 smoke（真实 root、零写入）：持协调锁跑真实入口→rc=75、ENABLED/锁文件字节与 mtime 全部未变。
- 产量口径更正（追加，不改旧记录）：日志 document= 行数含历史重试，不作产量；唯一完成账本=ocr-staging/ingested/ 按 sha 去重（现649）+root待入库（现12）；最新入库 0131da69…=127页真实转写（审计报告文本抽验）。
- 部署：driver/maintain 副本与 repo diff 空；维护 shims（repo优先/worktree回退）；进程 driver 13023→stage 13025 单实例。

## 第4线（动态 QA 落地，不等补源）

- scripts/paper_readiness_qa.py 动态化：读取 ashare-input-supplements/<epoch>/asset-evidence.json（FrozenSource 定稿 schema）→字节sha+行级日期/列值独立核验（ETF归一parquet契约列/逐码行数与末日/执行窗涨跌停非空；CB行内trade_date非文件名；CTA basic.parquet/mapping.parquet/contracts逐码+运行合约乘数覆盖+settle值非空）；BAR_APIS缺任一必需→blocked不取剩余min；日历=usable后真实最近开市日（修尾15截断）；ETF分红核验False仅作非阻断注记；artifact根解析链（CLI→ASHARE_PAPER_ARTIFACT_ROOT→market-source marker，无候选worktree硬编码）；共享 aline scripts datasets() 迭代器（quality_state门控，4GB manifest流式，实测42.3s/峰值1.10GB/按release缓存）。
- 定时与真实翻转：LaunchAgent com.quantmind.paper-readiness-qa（15min）安装+kickstart 真实触发 exit=0；实测动态翻转——full release 补进 trade_cal 后原3户 pending→ready（confirmed_next=2026-10-16，usable 2026-10-15）；i7/s1/cb/cta pending 待最终5-key资产manifest（首批native release data-87834d5b…已发布；SSE futurecal/SHFE fut_basic 两 transport_error 不算补齐）。
- checked_at=UTC Z 后缀（契约）。

## 未完成/待外部

FrozenSource 最终 normalized 五key资产 manifest 到达后出终判；platform 按HEAD(1a58c387)集成8文件；PG/Qlib云侧核验在platform。
