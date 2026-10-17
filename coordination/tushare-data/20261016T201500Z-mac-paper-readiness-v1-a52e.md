# paper-readiness v1 唯一QA生产者落地（第4线）

- 节点、任务：Mac，paper-readiness-v1-a52e；权威契约=quantmind-aline backend/README.md `唯一日更契约：paper-readiness v1`（父指定唯一节）。

## 交付

- `scripts/paper_readiness_qa.py`（分支 codex/ocr-quota-recovery-20261016，随 ee8d4b8d 入库；fixture 回归 scripts/test_paper_readiness_qa.py 5 项）：只读生产 host `~/Library/Application Support/QuantMind/market-source/paper-readiness.json`；按 release 缓存（相邻 paper-readiness-cache/，冷启动约 9 分钟、缓存后约 25 秒，适配 tick 15 分钟节奏）；两根相对路径、无 /Users、无 ..；不重造可用性判定（tick 只消费）。
- 真实首跑（2026-10-16）：schema_version=1，state=ready（基础身份+usable_date 合法），usable_date=2026-10-15（bar 类行级共同闭市日，非全接口 min）；per_api_cutoffs：12 时间序列=2026-10-15、index_weight=2026-10-13、维度表 null；market=data-1094f954…（manifest sha 校验过）、fundamentals=data-f9d120dc…（含 c7a 段完整 id）。
- 逐户真实状态：lowvol/b2/b3=pending（唯一原因：两个 release 的 trade_cal 行级均止 2026-10-15，无下一开市日；等 source future trade_cal 补源）；i7/s1=pending（prepared ETF parquet 未产出；且 research release stk_limit 三码 510300/511010/518880 行数=0——policy A 严格版必须 blocked 的数据实证）；cb_double_low=pending（cb_daily 日线止 2026-09-30；此前"CB到10/15"系误读上市/公告日期，已更正）；cta 两户=blocked（商品 basic 无 multiplier、日线止 9-30，拒绝猜乘数）。

## 已发协同

- platform-delivery：源→PG/Qlib/市场分析只读核验查询包+缺口清单（黄金 sge 权威缺、CFFEX 金融期货权威缺、done-but-empty 反例=manifest gaps ci_daily empty_unverified）；readiness 即刷新输入接口，无新 hook。
- FrozenSourceDelivery：trade_cal 无未来日实证+best分片 path/sha、etf三码零行实证、CFFEX/商品/CB refs（inventory JSON：~/.quantmind-line4-tmp/line4-source-inventory.json）。
- 文档：docs/local-market-source.md 增 paper-readiness QA 入口段。

## 未验证/待办

- 平台以真实 tick 消费本 JSON（含 blocked/pending 例证）为最终链路验收；补源与 prepared 产物落地后重跑 producer 翻转状态；producer 常驻调度（launchd）属平台服务域，未自建。
