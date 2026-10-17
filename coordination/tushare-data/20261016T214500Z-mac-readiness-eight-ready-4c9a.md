# 第4线readiness 8/8 ready收口与Mac/云只读核验（复核轮4）

- 节点、任务：Mac，readiness-eight-ready-mac-cloud-verify-4c9a；接续 210800Z 记录。

## readiness 终态（真实数据，8/8账户ready）

- 维护终版hash经PaperLedger真实外部smoke验收（EXIT0/ALL_PHASES_OK：正常PID停→新PID起、plist缺失真实bootstrap失败→非0+ENABLED先恢复+journal保留→plist恢复后下pass自动恢复意图、原stopped与state=not running均不强启；严格state==\"running\"修复hash=1567c213ecafd5cd09aecd6301c7dfe06ed291d0ee33dacefb9902f74bdc5f9a）。
- readiness最终判定：lowvol/b2/b3/i7_turn_of_month/s1_invvol_etf/cb_double_low/cta_combined/cta_trend 全部ready。关键收敛：
  1. i7：父冻结replay_start='2026-10-14'落地（非猜）；真实日历10/1..10/31逐自然日唯一0/1行+11月前缀至首开市日+usable后两open全部行级验证（calendar_through=2026-12-31、next_month_first=2026-11-02、next_two=[10-16,10-19]）；calendar_context按Paper契约同字段置于accounts.i7。
  2. CTA：闭包判定收敛为权威unit-evidence（370 warmup20250922/anchor20250919/replay13-15合约）∪独立mapping推导（数字合约码）；FU2710.SHF（新上市远月202710、全单位字段null、required_for_window=false、不在映射）→非阻断note（"no values were guessed"）；归一乘数normalized_multiplier正值+单位证据仅对必需闭包强制。
  3. s1/cb：真实etf.parquet/cb三件字节sha+行级核验ready；ETF分红未全核验=非阻断注记。
- 49项测试全过+ruff全过；producer安装副本（market-source/lib）无worktree依赖；LaunchAgent 15min真实触发。

## Mac原始vs云冻结只读核验（父新任务）

- Mac quantdb：四日线集2616分区dt=20160104..20261014（mtime 10-14）；min/tick仅20260903（既定范围非缺口）。
- Mac quantbc：CURRENT=binance-20261014T005604920145Z（sha db19ffd2…）；原始行至2026-10-14。
- 与Tushare固定release(10-15)差1交易日=采集节奏；status BC retry_pending/A 10-12。
- 云侧：本机SSH出口三host超时+tunnel 502（未推断永不可达）；只读查询包（PG max(trade_date)逐表/Qlib calendar末行+instruments/市场分析JSON trade_date）已交platform于其可用入口执行；三层基准（云冻结快照10-15≥Mac原始10-14≥本地沙盒标记9-24）如实区分。

## 维护HOLD释放

已代Main通知FrozenSource释放（仅trade_cal/SHFE两pending按retry_after续跑，供应商唯一写入不变）；归一版epoch 20261016T200115464516Z已被消费（cta ready）。

## 待办

source source-key稳定bundle最终路径；platform集成+artifact root唯一切换；云侧查询执行结果回流。

## 追加：规范稳定bundle绑定

- 消费者优先绑定 assets-1242bfc2bc32b11999332e343f1a54acae29740291dde82b08074cc89dc16304/bundle.json（source-key身份、无导出时刻；epoch目录回退保留）；真实重跑8/8 ready，五key path指向该bundle，FU2710 note与i7冻结replay_start语义不变。第二个无HTTP复用operation进行中，data_identity变化时按新bundle自动切换。

## 追加2：canonical指针cutover与BC未闭bar边界

- producer唯一读 ashare-input-supplements/CURRENT.json{schema_version,data_identity,bundle_path,bundle_sha256}（核sha/身份；无glob/epoch回退；missing=>pending）。当前指针未发布→五资产如实pending（原3户ready不受影响）；source最终16闭市batch完成原子发布后自动翻转。49项测试全过（fixture指针化）。
- BC边界更正：binance-20261014T005604920145Z捕获于10-14T00:56:40Z（日内56分钟）→10-14日线必然未闭，有效已闭区间至2026-10-13；此前"raw到10-14"表述不当作已收盘。过滤代码路径在platform独占域未定位，H5/Qlib派生有效范围属云侧未验。
- 逐源补充：quantdb daily_backward末分区5574行（000001.SZ close 18.977后复权）、index_daily 30行（000001.SH 3767.23）；A retry_pending 10-12、BC retry_pending 10-14且local≠cloud release；云PG/Qlib/市场分析未验（SSH握手timeout与tunnel 502分开记录）。

## 追加3：最终CURRENT独立QA（终）

- 唯一指针aff29eedaaee73559d7e3734d64fdd2b701c2928d1384cfeab95c6f220014473消费（bundle_sha ceca71b6…核过；未扫epoch）。7/8 ready：s1修复转ready（仅非阻断分红注记）、cta/cb/原3 ready；i7 pending唯一原因=当前full(data-87834d5b) trade_cal行级止10-16（SSE futurecal未入），待Tushare侧新full。asof区分：股票bar usable=10-15、资产bundle含16闭市。
- producer终版sha256=8b412efbd17c1d806c09c90f3dd8cb3d52968f0225953c47831c383e5a12f650（asset_bundle透传+最长覆盖日历+身份tuple同值；49项测试全过）。
- BC逐bar载荷实证（替代推断）：raw末bar=2026-10-13已闭（close_time 23:59:59Z≤capture 00:56次日）、无10-14 bar、请求窗口本身止10-13收盘。

## 追加4：8/8终态（最终CURRENT e7189393…）

- FrozenSource修复canonical calendar_candidates后，消费侧同步修全候选扫描取最长真实覆盖（360单日fragment曾遮蔽Q4日历）；edf4b1a6…parquet（92行2026-10-01..12-31 SSE全Q4）经sha+行级验证选中。
- 终态：8/8 ready；i7 calendar_context complete=True（through 2026-12-31/replay 2026-10-14/next_month 2026-11-02/next_two [10-16,10-19]）；股票bar usable 2026-10-15与资产16闭市区分如实。
- producer终版sha256=981fa167e42c73d9093ca8fc8cf23f5d8be120c0d41d0f558a76bdc0a321f253（已交Paper runtime同步；FrozenSource已收终判）。

## 追加5：merged calendar终态（最终CURRENT 3d722ef5…）

- canonical merged derived/calendars/5070a90a….parquet（32551B sha=文件名）+closure b45f032a….json（78723B）独占验证：13162行SSE 1990-12-19..2026-12-31、重复0、Q4在位；单片max_date择长停用。
- 消费侧配套修复：date/cal_date统一标准日轴+DATE对象串规范化（两次真实发现：merged用date列、DATE串带连字符）。
- 终态8/8 ready（i7 complete=True through 2026-12-31）。producer终版sha256=51d32d0ac7df1895d731d2c4d226f9584bb35bb6342f0224b9de3d5612b8e425；最终验收组合=producer 51d32d0a + consumer 29051f20。

## 追加6：跨源证据整合（platform PG实测加入）

- 云冻结PG（receipt /tmp/qm-platform-20261016t194641290902z/cold-postgres-market-samples.json，dump sha 15d21adc…只读COPY）：stock_daily_latest 10,909,172行 2016-01-04..2026-10-09；quote_daily_summaries末10-13；klines末9-04。
- 四层末日梯度：云PG 10-09 < BC已闭 10-13（逐bar证明）< Mac QuantDB 10-14 < Tushare release 10-15。HTTP410与滞后为独立事实。
- 四域只读查询包+已验证样例已交platform接private自动链；待qlib/market-analysis/BC derived三样补齐同表。

### 追加6更正（platform精确scope）

- klines样例interval=1d共3行末9/4，非"分钟9/4"（分钟未验）；stock_daily_latest末10/09仅该表事实，不泛化"云PG全部行情末日"；quote_daily_summaries末10/13独立成表。
- 10-09→10-14=5个自然日（中间12/13/14为3个开市日），对应source差距需真实日历核验，不推算"5个交易日"。

## 追加7：三样补齐，跨源整合整表完成（均verified samples非whole/restore）

| 层 | 实体 | 真实末日/规模 | 证据 |
| --- | --- | --- | --- |
| 云冻结PG | stock_daily_latest | 2026-10-09（10,909,172行，2016-01-04起） | platform receipt 15d21adc… |
| 云冻结PG | quote_daily_summaries | 2026-10-13（85行） | 同上（独立表事实） |
| 云冻结PG | klines(1d样例) | 2026-09-04（3行；分钟未验） | 同上 |
| 生产Qlib | calendars/day | 2026-10-09（2613行；instruments 5582） | SHA绑定小量拉取全匹配 |
| 生产Qlib | SH600000/SZ000001 features | 2026-10-09（finite 2595/2613；close_feature 20.269/19.126，口径只称QLib feature） | 同上 |
| 生产market-analysis | latest.db meta.trade_date | 2026-10-09（8839168B SHA bec242…；旧沙盒9-11标记作废为历史） | platform只读 |
| Mac quantbc | raw已闭bars | 2026-10-13（逐bar载荷证明） | 本方 |
| 云BC derived | daily_pv_all.h5 + close.day.bin | 2026-10-13（6690行两币；BTC 83169/ETH 2497.95=f32 2497.949951…） | platform SHA全吻合 |
| Mac QuantDB | 四日线集dt分区 | 2026-10-14（5574行实测） | 本方 |
| Tushare权威 | 研究release 18接口行级 | 2026-10-15 | 本方producer |

- 交叉验证：BC derived close(BTC83169/ETH2497.95)与Mac raw末bar载荷close完全一致——raw→derived独立链闭合。
- 自然日梯度（交易日换算待真实日历核验）：云PG/qlib/market-analysis 10-09 < BC 10-13 < Mac QuantDB 10-14 < Tushare 10-15。HTTP410独立保留。八户3实错修复进行中（platform），正式install暂停。

### 追加7更正（表级措辞）

- "生产Qlib features"行明确为：两只股票 SH600000/SZ000001 的 close features 与股票Qlib同2026-10-09（不写"双币features"）；BC两币daily_pv_all.h5与各自3345行close features为独立2026-10-13（ETH f32=2497.949951171875差异保留）。其余表级scope照旧。
