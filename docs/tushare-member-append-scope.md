# 成员 API 独立追加规划范围

候选基线 `79f4498`。不修改旧 `market_sentiment` 的五接口配置、规划流或游标；两个成员接口仍归原消费组，复用其配额、公平选择、原始响应及饱和拆分。新增 `market_members` 只是独立自动规划范围，使用既有 `planning_state` 的 `recent:market_members` / `history:market_members`。不新增表、永久手动调度或消费组，也不迁移旧任务身份。

`APPEND_PLANNERS` 仅进入 `plan_extended`，不进入 `next_job` 的消费组列表，因而不额外占用组份额。默认关闭。启用须同时满足原组已启用、原 API 清单明确排除两个成员接口；未指定原清单相当于原七接口默认值，也会拒绝重复规划。非法配置写明 `planning:market_members=validation_blocked`，不创建或推进本范围状态。

配置示例仅供后续审核，未在生产执行：

```json
{
  "enable_market_members": true,
  "market_members_apis": ["tdx_member", "kpl_concept_cons"],
  "market_members_history_start": "20260904"
}
```

起点可按 API 映射。示例只承诺从该日继续规划，不代表更早历史已完整；未设置时只规划近七个日历日，并记录未知历史起点。新范围不继承旧 `history_start` 或 `market_sentiment_history_start`，避免把旧组历史范围当作成员历史来源证据。不得修改未完成新范围的 API 清单/起点来重置流；以后改变自身 policy 仍需单独审查，和其他 family 一样。

每个日期保留 bulk 请求以发现新来源，并对已有 `tdx_indices` / `kpl_concepts` 的原始合法代码逐板块规划。字段和作业 identity 全部经原 `enqueue`；代码不会换成股票身份。发现集合按有限快照冻结，未完成时新增来源不会重置 offset；完成后已有 refresh 机制补入新代码的全部配置日期。近期快照跨多日时复用已有六日重叠追赶机制。日历日空响应仍不是“历史不存在”的证明。

工作量约为 `日期数 × Σ(1 + 各 API 已观察板块数)`；日期 bulk 饱和产生的同 epoch/params 子任务与直接逐板块任务使用相同 identity，幂等去重。启用后将增加原组内两个 API 的实际请求需求，不能保证总吞吐线性提升。历史枚举继续受现有 `plan_jobs_per_tick`、扫描数和时间预算限制。

已验依据：固定版 `data-0a5af2a613b00f3c8cf088662215614fb1d56ba38c162f480a270634370103a1` 的六个合法单板块响应（TDX 三个、KP 三个，合计 985 行、11 源字段）已 cloud/Mac 同版对账。这只证明这些查询合法且样本落盘：全集、其他板块可用性、完整历史、`con_code` 第二分片轴与 PIT 均未证明。保留原合同及新 `observed_board_scope_not_universe` gaps，不改变已有饱和父的 raw、attempt 或 `coverage_proven=false`。直接规划的新板块不会伪造旧父子覆盖关系。

离线回归：

```bash
uv run --offline --no-project --python 3.10 --with httpx --with pyarrow --with duckdb python -m unittest discover -s scripts -p 'test_tushare_member_append_scope.py'
```

覆盖默认关闭/拒绝重叠、旧五接口四轮逐任务/游标对照、新范围有界断点及来源/日期追赶、既有 worker 实际选中、权限和 account/API gates 保留、旧观察不变、饱和父增量合法子任务及未知全集不误判。测试使用临时 SQLite 和 MockTransport，禁止 socket/DNS/凭据读取；未验证生产吞吐或启用状态。
