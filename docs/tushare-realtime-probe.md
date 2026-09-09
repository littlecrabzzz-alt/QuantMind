# 实时十接口：有限探测与固定版验收

这两个工具把已审临时 realtime10 helper 整理到仓库，默认 **dry-run**。探测通过不等于接口已启用、历史齐全或具备 PIT；工具不修改配置、不发布版本、不自动重试或启用接口。

依赖当前 realtime runtime、同日旧 slot 拒绝修复（原 `2abcd7f`，仓库化基线 `eed2c88`）、`tiered_v1`、权威 SQLite schema6。执行前会检查 slot 拒旧行为，策略缺失或版本不符时不执行。部署和双端业务入口沿用 [双端部署说明](dual-node-deployment.md)，固定镜像沿用 [镜像说明](tushare-mirror-installation.md)。只在授权窗口由云端既有业务容器执行；不能在 Mac 权威目录重建采集队列。

## 范围与硬限制

| API | 最大请求 | 参数范围 |
| --- | ---: | --- |
| `stk_auction` | 6 | 真实单码；未指定/STK/ETF 各一个近日日和一个窄历史范围 |
| `rt_etf_sz_iopv`、`rt_idx_k`、`rt_sw_k`、`rt_k`、`rt_etf_k` | 各 1 | 真实单码、当前快照 |
| `rt_idx_min`、`rt_fut_min`、`rt_idx_min_daily`、`rt_fut_min_daily` | 各 1 | 真实单码、`1MIN`、当前；不传历史日期 |

合计最多 15 次，等待门控、网络和归一化合计最多 120 秒；最后一次持久化收据不受这个网络预算限制。响应不明的尝试计入请求预算；明确本地日配额拦截为 0 HTTP。其他四种频率、其他标的及全市场范围仍未验。没有通配符、分页、满页展开或猜测前一交易日。

- 使用与正式采集相同的 `resolved_api_rate`，账户速率取 `requests_per_minute` 和 `rollout_account_rpm` 较小值；保留 API 配置上限、已观察配额间隔和持久 `request_gates`。不将积分层级视为实际权限。
- 执行全程持有现有 `pipeline.lock`，非阻塞取锁失败即退出；无第二下载器或绕过锁的路径。调用原 `capture_sample`，它仍执行当前共享的 pre-HTTP 日配额逻辑。
- 新 probe job 在同一事务内进入不可调度的 `probe_prepared`，HTTP 前提交 `probe_inflight`。旧普通任务不改。拒权或限频后停止同 API 后续请求，其他 API 仍须通过各自及账户门控。
- 默认没有 slot。显式 `--execute` 后在取锁、读配置完成时生成 UTC slot；九个 snapshot/replay API 在 HTTP 前校验上海同日及该次准确 slot。竞价走独立日期参数。没有自动更新配置 slot 的定时任务。
- 收据路径必须新建，不支持隐藏续跑。中断后不得靠改文件名自动再试：需审查已有证据、配额和不确定尝试，再决定一个新的有界运行。不会把 prepared/inflight 变为后台 pending。

## 选择已有固定版种子

种子必须来自**已经发布的原文和 observation**，逐 SHA/bytes 对照该固定版 manifest，不能只填写一个代码宣称其存在。没有足够证据就保持 dry-run 失败，不加网络发现请求。

```json
{
  "release_id": "data-<固定版SHA>",
  "sources": {
    "stock": {"observation": "<stock_basic原观察>.json", "value": "<实际源代码>"},
    "etf": {"observation": "<etf_basic原观察>.json", "value": "<实际深圳ETF代码>"},
    "index": {"observation": "<index_basic原观察>.json", "value": "<实际指数代码>"},
    "sw": {"observation": "<index_classify原观察>.json", "value": "<实际index_code>"},
    "future": {"observation": "<fut_basic原观察>.json", "value": "<实际有效合约>"}
  },
  "calendar": {
    "observation": "<SSE或SZSE trade_cal原观察>.json",
    "recent": "<过去14天内且早于今天的已见开市YYYYMMDD>",
    "history_start": "<20250101起的已见开市YYYYMMDD>",
    "history_end": "<相距不超过3个日历日的已见开市YYYYMMDD>"
  }
}
```

股票种子要求 `list_status=L` 的真实来源；ETF 限一个深圳代码以同时覆盖 IOPV；期货须有真实上市/到期日期覆盖运行日，拒绝猜测的 8888/9999 连续合约。日历原文需含三个选定日期，历史结束日须早于近期日七天以上。当前主数据不能证明历史已上市或历史竞价可用，历史空结果仍是缺口。源后缀代码只用于上游请求与来源证据，读取仍按 STK/FUND/IDX/FUT/未分类竞价命名空间。

## 命令

以下是模板，变量由操作者设为已核验文件路径、SHA 和版本。默认 repo 为脚本所在仓库；`--repo` 仅在固定运行环境显式指定源码根目录。Git 只保存工具和合成测试，真实原文、种子和运行收据留在正式数据/临时审计目录；不把凭据放参数、种子或报告。

```sh
# Mac 主树的现有云业务入口；只规划，不创建 slot/报告/数据库。
bash scripts/dual-node.sh cloud-compose exec -T quantmind python3 -S /app/scripts/tushare_realtime_probe.py \
  --root /data/tushare --seeds "$SEED_FILE" --seeds-sha256 "$SEED_SHA" \
  --report "$NEW_PROBE_REPORT" --dry-run
```

审查 15 个准确参数后，独立获准的执行将 `--dry-run` 换成 `--execute --seconds 120`。此时才通过原 ignored credential getter 读取 token；不会打印或保存在报告中。响应正文仍由原 capture 在正式对象区按原脱敏机制保存；报告仅保留状态、计数、SHA、来源引用等白名单元数据，去掉响应正文、HTTP headers、任意上游消息。异常 CLI 只输出异常类型。

执行结果应先审查，再经现有正常发布路径发布原文/观察/Parquet。记录这次固定 `release_id` 和报告 SHA，之后不跟随 CURRENT。

```sh
# 云端固定文件验收，0 HTTP、无 SQLite/Pipeline 实例、无凭据读取。
bash scripts/dual-node.sh cloud-compose exec -T quantmind python3 -S /app/scripts/verify_tushare_realtime_fixed.py \
  --root /data/tushare --release-id "$FIXED_RELEASE" \
  --report "$PROBE_REPORT" --probe-sha256 "$PROBE_SHA" --output "$NEW_CLOUD_AUDIT"

# 正常镜像已校验相同版本后，在 Mac 用安装了 pyarrow/duckdb 的持久 Python。
python3 scripts/verify_tushare_realtime_fixed.py \
  --root "$MAC_MIRROR_ROOT" --release-id "$FIXED_RELEASE" \
  --report "$LOCAL_PROBE_REPORT" --probe-sha256 "$PROBE_SHA" \
  --compare-report "$LOCAL_CLOUD_AUDIT" --output "$NEW_MAC_AUDIT"
```

Verifier 禁用 socket/DNS/secret getters，对所有对应 manifest parts 验 SHA，独立核对原文全列/未知列/null、行重复数、源代码与请求维度、去重和 reader 全部输出。固定过滤仅认可可验证源日期/时间格式，不猜时区。上限为总 100,000 存储行、每 API 200 parts、单文件 32 MiB、累计源文件 128 MiB；超过直接失败，不能静默截断。两端 `equivalence_sha256`、版本、报告 SHA、行数、全列哈希和缺口必须一致。

## 准入边界与验证

十份合同的 **105 个已知列**全部请求，不省略隐藏列；完整原文保留未知字段。`sample_passed_api_candidates` 只是逐 API 的非空样本审查候选，始终 `automatic_activation_permitted=false`。所有该 API 计划样本必须 schema、身份、源过滤、日期和固定 reader 通过；拒权、空、饱和、缺列、时间未知、未完成计划不能进入候选。即使通过，也不等于全历史、源时区/PIT、所有频率或可自动定时采集已验证。

未来启用须另审准确 API/频率/标的 scope 与 cloud/Mac 固定证据，保留其他家族配置和未完成游标。不能把一个 sibling 的通过扩成整组通过，也不能用此工具重置历史游标。这里没有配置写入/自动启用 helper。

```sh
python3 scripts/test_tushare_realtime_tools.py
```

专项测试用临时 JSON/Parquet 和内存 DB doubles；禁止真实 SQLite/Pipeline 构造、socket/DNS、秘密 getter。覆盖十接口固定全列等价、SHA/未知空列/重复数/饱和/日期/权限失败、非法历史 replay、15 次预算、共享门控先提交、灰度账户上限、观察配额、0 HTTP 本地配额和中断不可调度状态。`--help` 和 dry-run 不需要 token。实际权限探测和生产执行仍未进行。
