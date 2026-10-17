# 第5线维护终版与第4线动态终判收口（复核轮3）

- 节点、任务：Mac，maintain-final-dynamic-verdict-8f21；接续 204500Z 记录。分支 HEAD=55328fbc。

## 维护链终版（PaperLedger strong review 三轮窗口全部修复）

- scripts/pdf_maintain.py sha256=bc4d73b6f05b0be7c31198b99530f959b202d4332364c285756490df663d547e（与已安装副本逐字节一致；repo或tushare-client安装树解析backend模块，无Documents依赖）：
  1. LaunchctlWorker 三态 state()（running/stopped/unknown；rc0无state行=unknown，launchctl stub fixture含blank用例）；running()恢复。
  2. 单一pause journal承载全部恢复意图（agent/enabled_sha256/worker_state_before），pause尝试前原子持久化；resume失败/异常→ENABLED先无条件恢复→非0传播+journal保留；无主backup绝不自动恢复（人工停采不被误启用）；journal按label+字段完整校验（legacy/畸形/双存在/字节不符→保留非0）；finally冲突保留意图。
  3. 四排空锁（pipeline/documents/.archive/.migration）全量非阻塞持有下pause（关worker flag检查后取锁的竞态），确认stopped后释放进body。
  4. driver最终drain：队列结束有待入库→强制maintain，busy(75)退避持续重试不退出。
- 测试48项全过（维护16：真实worker类经launchctl stub、并发协调锁、busy不bootout、crash恢复、异常恢复、blank=unknown、journal边界×4；readiness 10；driver 5；OCR 17）。
- 真实临时LaunchAgent lifecycle smoke（com.quantmind.maintain-smoke-test=/bin/sleep，真实系统launchctl）：P1=20556 running→body期pid=None/ENABLED absent/journal kept→pass后新P2=20587 running/ENABLED字节精确恢复/backup+journal清除，7项检查ALL_PHASES_OK；仅清理测试资源，权威worker全程未触碰。
- 真实busy零写入smoke维持有效：持协调锁→rc75+真实root不变。

## 第4线动态终判（真实5-key evidence消费）

- 安装副本 ~/Library/Application Support/QuantMind/market-source/lib/paper_readiness_qa.py（91d82eb6a0e5…）+ LaunchAgent com.quantmind.paper-readiness-qa（15min）触发exit=0；wrapper已切安装副本，无worktree依赖；artifact root经wrapper显式env（待platform部署真/app/output host root后改一行）。
- 真实终判：原3户=ready（usable 2026-10-15，confirmed_next=2026-10-16）；s1_invvol_etf=ready、cb_double_low=ready（791691行到20261015、premium 6日1887/1887行级核验）；cta两户=blocked（6541合约缺normalized_multiplier、运行闭包FU2710.SHF未覆盖——按官方doc135，raw商品multiplier NULL非缺口，待source normalized版manifest即翻转）；i7=pending（calendar_context完整产出：calendar_through=2026-12-31、next_month_first_session=2026-11-02、next_two_sessions=[10-16,10-19]、complete=false因evidence未含replay_start；仅I7受门禁不牵连他户，accounts.i7…calendar_context已按Paper契约同字段放置）。
- 18接口白名单修正（fund_adj入、etf_limit=补源不占位）；cutoffs缓存键v2；共享datasets()迭代器（4GB manifest流式，实测峰值1.10GB/42s冷）。

## 协同

- 已代Main通知FrozenSource释放维护HOLD（仅trade_cal/SHFE两pending按retry_after有界续跑，供应商写入唯一性不变）。
- PaperLedger：终版hash+smoke结果已交其strong review/复验；platform：HEAD范围+安装状态已交唯一集成。

## 待外部

source normalized_multiplier版manifest与replay_start补充→cta/i7翻转；platform集成与artifact root部署marker。
