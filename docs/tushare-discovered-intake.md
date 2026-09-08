# 目录外接口：实时快照合同与失效历史线索

2026-09-09 复核，代码基线 `b0e1845`。纯合同模块 `backend/shared/tushare_discovered_contracts.py`；未接 registry/pipeline/store，未调用数据接口或检查账户权益。

## 当前有效契约

| 官方来源 | 导出合同 | 输入及字段边界 | 权限 / 历史 |
|---|---|---|---|
| [372 A股实时日线](https://tushare.pro/document/2?doc_id=372) | `rt_k` | ts_code 必填，允许多值及代码通配符；15 个源字段含隐藏盘口价量和 trade_time；文档上限 6000 | 独立实时权限未探测；不支持历史日期输入。 |
| [400 ETF实时日线](https://tushare.pro/document/2?doc_id=400) | `rt_etf_k` | ts_code；沪市 topic=HQ_FND_TICK；13 个字段含隐藏买卖一量和 trade_time；未公布最大行数 | 独立实时权限未探测；无历史日期参数。topic 表中必填但深市示例省略，保留差异。 |

全部源字段在模块 `FIELDS/extra_fields` 中，包括非默认字段；父请求构造器应通过既有 fields 通道选择它们，不能把生成字段送上游。`vol` 是股，`amount` 是元，不能沿用历史日线的手/千元单位。停牌、无成交或盘前的零值/空值不是价格有效性证明，也不能用严格正数约束丢掉原始响应。代码按 supplier SH/SZ/BJ 边界保留，T 前缀与普通同数字代码不合并。

`row_cap_verified=False`；ETF 的 1000 只是保守满页报警阈值，文档没有证明这个上限。没有 offset/limit/date 分割，满页只能按已发现标的细分；发现不全或单标的仍满页应保留缺口，不把分片请求合并解释为原子市场快照。

## 实时语义与最小集成点

导出：`DISCOVERED_CONTRACTS`、`DISCOVERED_GAPS`、`iter_discovered_jobs(config, today, identifiers=None)`、`discovered_prerequisites(identifiers=None, enabled_apis=None, config=None)`。

- `config.discovered_apis` 选择复核过的名称，默认仅两个有效实时接口。选择 gap 名称只返回缺口，不生成假请求。
- 必须显式提供 `discovered_snapshot_epoch=YYYYMMDDTHHMMSSZ`（UTC），并且对应 `today` 指定的上海日历日；没有 epoch 就没有请求。这里仅检查规划一致性，不会读取系统时钟。
- `identifiers.stocks/etfs` 来自已存发现表，支持 supplier ts_code 字符串或记录。股票每批 100 个代码，ETF 先按官方示例查询 `5*.SH`/`1*.SZ`，再为发现表中不匹配这些模式的每个代码生成单标的请求。无硬删除退市/特殊代码；北交所 ETF 等 topic 语义未知仍在 prerequisite gap，真实响应需单独核验。
- 作业只有近期优先级 20 和 `snapshot-<epoch>`，没有 history 作业，不接受/生成历史日期请求。不同 API 流交错生成。默认通配符只能发现其中覆盖的标的，不能证明没有其他模式；prerequisites 始终保留 universe 完整性未知。
- **父执行器负责权限、权威节点、实际当前时间、过期作业拒绝和请求/响应时间记录。** 若排队迟到，不能用旧 epoch 将新价格标成旧时刻。当前通用历史队列尚未集成这些实时门槛，不能仅注册合同就启用。
- `close` 是观察时刻最新价，`vol/amount/num` 是截至该时刻累计值，不等于已确认最终收盘。trade_time 格式、时区、各标的更新滞后及盘后最终性没有实测；缺失时保持空值，不能用任务 epoch 填造。
- 合同 keys 包含源 ts_code、可空 trade_time 和**生成的 `_observation`**；父消费者应再沿既有 `preserve_distinct_rows` 保留 `_row_identity`。这样不同观察即便价格未变也不会被默默合并。同一源时间的不同正文也保留，不能仅按 ts_code/trade_time 取最后值。`_observation` 不在源字段清单里、不发上游。
- 尚未观察的旧盘中快照不能靠该接口补回；获取历史日线是另一数据集与定义。本模块不会为实时页编造历史下界。

## 当前失效的两个历史线索

首批官方搜索缓存曾返回这两个名称与字段，**本轮实时打开页面及独立 curl 均返回 HTTP 200、正文 `404, 文档不存在！`**。因此现在仅导出 `DISCOVERED_GAPS`，没有它们的输入字段表、cap 或可执行合同；搜索缓存不能覆盖当前文档失效证据。

| 来源 | 当前处理 | 仍需核实的历史问题 |
|---|---|---|
| [188 `hk_hold`](https://tushare.pro/document/2?doc_id=188) | `official_document_missing`，权限未验证 | 先前缓存提到北向持股于 2024-08-20 后由日度转为季度披露；当前接口、历史取得方式和公布时间需官方重新确认。不能自己生成季度记录或将持仓期末日当公告日。 |
| [422 `dc_concept_cons`](https://tushare.pro/document/2?doc_id=422) | `official_document_missing`，权限未验证 | 先前缓存声称历史从 2026-02-03、3000 行、6000 积分；这些不作为当前有效合同。概念解释/热度等修订不能用当前成分回填，亦不与 dc_member/KP 成分接口自动合并。 |

两页相同失败正文为 23 字节，SHA256 `bbf4318386ca0ea4c5072fc5e67fe0302f473ccbeba7238c45607226236dfadf`。当前有效页面原始字节哈希：372 为 `58905ec12e31c14a168bb781892ee3c89547d879252ac9ebbaad1062bb755912`；400 为 `4395c969142c0818405e4ce17fea6a1bbefde370a287edfa52c05253b5e5c478`。临时原页在 `/tmp/quantmind-discovered-contracts/`，不作为运行依赖。

## 验证

`python3 scripts/test_tushare_discovered_contracts.py`：6 项纯离线测试，禁止 socket/DNS；覆盖字段、隐藏列、快照身份、无历史请求、缺页不生成任务、股票批量边界/特殊代码、ETF 模式外标的、UTC/上海日期边界、幂等与流交错。Ruff 与 diff 检查通过。没有权限成功、真实报价质量或端到端可用性的宣称。
