# 基金净值空响应复核方案

固定版 `data-d5d918ce4bc2cfd3ef6e58c5caeefa29c7d9f9715cd5b8cd0d03d4d07cab64de` 中有77个 `fund_nav` 空叶阻断父区间闭包。它们都是77只不同基金的 `19900101..20080502` 请求，每项只有一次HTTP 200、完整字段、0行且 `has_more=false` 的不可变观察。相同基金在该版均有2013—2017年开始的非空净值，当前 `fund_basic` 生命周期也晚于空窗口；这些证据只适合选择正向控制，不能证明2008年以前的历史不存在。

## 状态与时间边界

空结果复核只用于决定何时停止自动重试，不授予数据覆盖闭包：

1. 首次有效空观察至少24小时后进入第一轮复核。
2. 每轮成对固定两个请求：A是原任务的字节级相同参数和字段；B是同一基金在固定版中已知非空净值日期的单日正向控制。
3. A必须再次得到HTTP 200、完整显式字段、0行且没有 `has_more=true`；B必须得到HTTP 200、`sample_ok`，并返回目标基金和日期。本轮才计作一次有效空复核。
4. 第一轮有效空后至少等待7天再做第二轮。三次独立空观察和两次成功正向控制后标记 `review_exhausted`，停止自动复核。
5. `review_exhausted` 不改变原任务的 `empty/empty_unverified`，祖先继续为 `split_pending/child_not_verified`，发布级 `history_complete` 和 `pit_verified` 继续为false。
6. 任一A返回合法非空数据，保留旧观察并沿现有标准化、artifact校验和 `reconcile_partitions()` 路径更新。错代码、窗外日期、封顶或schema异常进入 `review_conflict`，不闭包。

传输错误、429、API错误、权限错误或B失败时，本轮为 `review_inconclusive`，不计空观察且轮内不重放；分别至少1小时、24小时后最多重新冻结两次，再失败进入 `manual_hold`。正常两轮上限为308次请求，即77个目标乘每轮A/B两个请求再乘两轮。

## 实现合同

新增专用prepare和runner，保持schema 6、现有任务状态及 `reconcile_partitions()` 判据不变。prepare默认plan-only，manifest固定原任务完整job、首次空观察及object哈希、起始固定版及manifest哈希、控制自然键和observation/parquet哈希、轮次及 `not_before`。runner只能在停Beat和writer后的独占窗口运行；有效结果继续写入不可变objects、observations和attempts，但不能先把空任务改回全局pending，避免普通调度器误领。

prepare和runner已实现两轮完整契约。它们强制显式指定authority root、固定版root和release ID，不追随可变化的 `CURRENT`；prepare只读schema 6数据库和固定版文件，首次空观察满24小时后才生成round 1清单。runner默认只验证manifest，真实执行需要宿主先停Beat并自然排空writer，然后以非阻塞共享 `pipeline.lock` 确保排他。用显式 `data-d5d918ce…` 和从不可变证据重建的临时数据库离线验证，77个目标全部符合条件，任务集合SHA256为 `5c60a712975d54e269d97fe66fb52c81bdb234f2879e91a4e621d6ecd0cc312e`。该结果只验证准备逻辑，不是生产执行收据；生产重新冻结必须使用当时明确固定的release和停写authority状态。

第二轮通过 `--review-round 2` 显式启用，只接受唯一的 `round1_valid_empty`，固定第一轮attempt、当时的旧fixed release、round 1 manifest及A/B observation/object四个哈希，并重新从旧release校验当时的正向控制。round 2可以使用一周后的新fixed release及新控制，不会因 `CURRENT` 正常推进而永久选不到。跨release、恢复非空、conflict、manual hold、同manifest零HTTP收据恢复和 `review_exhausted` 不闭包均已纳入测试；生产round 1最早仍受 `2026-09-11T12:26:34.077603Z` 时间门控，目前没有上游复核请求。

验收覆盖manifest篡改、重复目标、字段或窗口漂移、旧CURRENT、UTC和时钟回拨、轮次幂等、崩溃恢复、双writer竞争、请求硬上限，以及A/B的全部成功和失败组合。发布和Mac镜像验收必须证明新观察、对象、attempt和receipt哈希可追溯，同时reader行数不会因空复核而虚增。

未来只有取得独立、版本化且具有可校验有效时间的权威成立范围，才可另记 `scope_excluded_verified`。该状态仍表示显式排除范围，不等同于数据存在或普通 `resolved`。
