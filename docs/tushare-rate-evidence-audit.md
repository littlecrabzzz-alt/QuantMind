# 227 个 API 的官方频次证据审计

基线 `master@32fe472`，2026-09-09。只读取仓库、已归档官方 HTML 和公开文档 290/490；未读取 token、生产配置/DB、调用数据 API 或改变限速。输出为审计，不是可直接部署的配置。

## 分类结果

[机器可读报告](tushare-rate-evidence-32fe472.json)逐 API 包含 rate_class、文档频次候选、当前源码合同频次、默认 API gate、HTML/政策行 SHA、文档 ID、历史台账权限状态、有效期与未知事项。

| rate_class | 数量 | 解释 |
|---|---:|---|
| purchased_special | 9 | 用户已声明购买的新闻3、公告、董秘问答2、政策、研报、央行报告；不是本轮账户复查 |
| independent_unverified | 38 | 独立权益，不从积分推定；即使产品给出 rpm，仍不等于本账户有正式权限 |
| per_api_override | 19 | 有更具体的接口频次规则，优先于一般表；冲突保留 |
| points_special | 3 | 一般特色档候选，cyq_chips 已另归 override |
| points_general_candidate | 155 | 有接口积分说明，采用一般表作条件候选；特色适用性、当前权益与 live gate 未认证 |
| unknown | 3 | fut_weekly_monthly、hsgt_top10、namechange 的已保存正文没有充分的频次/积分说明 |

分类轴与“可否请求”分开：已有 sample_ok/permission_denied 仍保留在 source ledger 的历史 permission_status，本轮不刷新账户权益。源码已登记但尚未启用的接口也不丢失。未取得 rpm 的 independent 项仍为 null，不能用类别默认值填齐。

## 关键官方证据

[官方290](https://tushare.pro/document/2?doc_id=290) 将积分与独立授权分开。10100 积分对应普通数据候选 500/min、特色候选 300/min，不能推给独立接口。叶子页有明确规则时另行审查：stock_basic 50、ths_member 200；专业版技术因子等在更高积分档可达 500。当前本地合同 60 项为 30/min、103 项为 50/min，这些不是普遍官方额度。未测实际吞吐，不据此宣称可以线性提速。

文本用户购买声明对应：新闻3为400/min，公告/问答/政策/研报500/min，央行报告200/min。有效期按用户声明截至2027-09-08，具体到期时刻/续费未核实。积分2000部分于2026-12-05到期，特色档需在该日重新评估；不把当前10100永久固化。

[官方490](https://tushare.pro/document/2?doc_id=490) 给出 factor_value 独立权限、试用条件与6000行单次上限，**没有 rpm 或每日请求额度**。因此 factor_value/factor_list 官方频率为 null；成功返回几次不能证明持续额度，也不把“6000行”当6000次。

两项有实质冲突/不足需保留：

- cyq_chips 单页在5000档写200/min，10000档只提高每日额度；一般特色档写300/min。报告保守记录200候选及歧义，没有声称10100已确认200上限。
- report_rc 单页与一般表对高积分每日总量描述不完全一致，单页“总量无限”不会被误解成频次无限。

分钟产品映射采用明确证据：不把股票/期货/期权/申万的产品频次自动推给ETF、交易所指数或港股试用；邻接 `rt_*_min_daily` 也不直接继承同页另一API的频次。实时 rt_k/rt_etf_k 的归档叶子 HTML 本目录缺失，但290有明确产品链接与频次；缺失仍标记，不伪造叶子SHA。

## 对现有 gate 的含义

`Pipeline.next_job` 的现有公式为独立 account gate，加 `min(config.api_requests_per_minute[api]或200, contract_rpm)`，另有 API 最小间隔/错误冷却。报告给的是无覆盖时默认 API gate，不是生产实际设置。本轮没有源码合同高于所记录文档候选的项，但这不认证候选权限或所有请求预算。30/min 的60项中48项有更高文档条件候选，适合后续逐项审查；不能批量去掉共享gate、每日额度或实际限流反馈。

官方文件只具有观察时间，没有承诺有效至某日。JSON 中 `official_rate_valid_until=null`；用户购买到期日单列，不冒充官方频率有效期。按证据再更新配置应由独立候选完成，本审计不被运行模块导入。

## 复跑及验证

```bash
python scripts/audit_tushare_rate_evidence.py \
  --archive-dir /tmp/tushare-full-schema-audit-20260909 \
  --current-doc-dir /tmp/tushare-rate-evidence-20260909 \
  --as-of 2026-09-09 --output /tmp/tushare-rate-audit.json
PYTHONPATH=scripts:. python -m unittest test_tushare_rate_evidence
```

脚本本身无网络代码。当前公开页290 SHA `18e4557232524672da08f47d89eef2a384919103de24680c37021e9641000d80`、490 SHA `3328603c3cc38b1d305a1b45d2e8adefda75fe0bd37b2baea300e21b95fd0962`，原HTML/采集时刻保存在上述`current-doc-dir`。旧叶子页以各自归档SHA为准，未声称重新访问227页。

Python3.10：8项专项测试通过，含真实CLI临时fixture、购买到期、行数/试用不冒充rpm、单页覆盖、冲突保留、邻接不继承、缺文档unknown、解析边界及禁网；Ruff通过。无新依赖、无生产改动。

## 155 项一般候选的进一步分类

新增 [精确集合及证据](tushare-general-rate-refinement.json)，只细化原155项，其他72项原类别不变。`api_sets.regular_500` 是明确147项 allowlist，不应以“227减去几个例外”的反向逻辑扩充。每项附现行290侧栏的类别祖先ID/名称、归档单页SHA、政策行SHA与积分条件。

- **147 项 regular_500**：归档单页明确积分制，官方类别路径不在290正文所链接的特色分类291之下，也不属于本轮发现的权益歧义；其引言所列积分档均不高于8100。按290的一般5000以上档，本次积分声明由10100降到8100后仍可保留500频次证据。这里的“可”仍以前置权限、单接口实际错误quota、account gate、最小间隔及冷却为条件，不代表解除它们。下一次已知积分到期为2027-09-08。
- **3 项 special_300**：`stk_ah_comparison`、`stk_nineturn`、`stk_surv`。290正文明确链接291特色类别，现行侧栏把这三个叶子放在其下，不能仅因它们不在总表的四个举例中而当作常规。10100时按特色300条件档，2026-12-05失去10000档后必须review；单页6000等访问条件仍可能满足，不代表届时完全无权，但本审计不自动续给300或升500。
- **5 项 uncertain**：`hk_basic`、`hk_tradecal`、`us_basic`、`us_tradecal` 的叶子说明积分可用，与290对港美股权限的总述存在范围张力；`hm_detail` 的单页10000门槛在8100时不满足。需要澄清或重新确认，不能列入跨到期日常规500白名单。

原特色3（report_rc/cyq_perf/broker_recommend）、cyq_chips等显式覆盖、9已购、38独立及原3unknown全部保持原审计，不被这次细化吞掉。`factor_value` 仍为独立且官方频次未知。

复跑：`python scripts/refine_tushare_general_rates.py --baseline docs/tushare-rate-evidence-32fe472.json --category-html /tmp/tushare-rate-evidence-20260909/290.html --archive-dir /tmp/tushare-full-schema-audit-20260909 --output /tmp/tushare-rate-refined.json`。脚本验证每个叶子与原审计HTML SHA一致，类别缺失/正文漂移不猜填。新增6项测试，连同原8项共14项Python3.10通过；含147+3+5完整分区、源篡改拒绝、嵌套类别不串到兄弟、8100与特色review边界、真实CLI。无网络代码、数据API或runtime修改。
