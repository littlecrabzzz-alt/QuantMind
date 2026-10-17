---
name: model-train-infer-backtest-report
description: "模型训练-推理-组合回测-专业报告全流程：提交T+N模型训练、批量推理、自定义组合回测（分数阈值、大盘MA、止损）、导出MD与PDF。模型类型以 backend/shared/training/request.py 的 ALLOWED_MODEL_TYPES 为准。触发词：训练模型、模型训练、推理全年、回测策略、周期对比、止损、大盘过滤、出报告、效益分析。"
---

> ## ⚙️ 运行环境契约（最高优先级，先于本文其余内容执行）
>
> QuantMind 只在本地 Mac 运行：主业务由 Library 中已核准运行快照的 `scripts/local-primary.sh` 管理，Main 是开发源码；`local-dev.sh` 沙盒数据独立，不能与主业务同时占用 8000。执行前确认本地 Docker Desktop context、项目和挂载：
>
> 1. **后端 API 地址**：主栈 QwenPaw 与后端同在 `quantmind-local_quantmind-net`，使用 Compose 服务名 `http://quantmind:8000`；Mac 宿主机用 `http://127.0.0.1:8000`。正文 API 示例的回环 8000 地址仅在该容器场景替换为服务名；不要改写其他服务端口或 API 路径。
> 2. **取数脚本执行**：凡 import 了 `pandas / duckdb / psycopg2 / numpy / sqlalchemy` 等重依赖或 `backend` 包的脚本，**在主栈后端容器 `quantmind-local-quantmind` 内执行**（QwenPaw venv 无这些依赖）：
>    ```bash
>    docker cp <脚本路径> quantmind-local-quantmind:/tmp/<脚本名> && docker exec -w /app quantmind-local-quantmind python3 /tmp/<脚本名> <参数>
>    ```
>    脚本优先从当前 QwenPaw 已安装工作区 `/app/working/workspaces/default/skills/<name>/scripts/` 读取；宿主机源码在 Main 的 `skills/<name>/scripts/`。Library 运行快照不默认包含 `skills/`，仅在实际存在且版本匹配时使用 `/quantmind/skills/`。Main 的 `data/db` 不是主业务数据；读写以容器实际挂载为准。纯标准库脚本可在 QwenPaw 内直接跑。
> 3. **报告落盘**：股票报告页可见的 MD/PDF 报告，直接写 `/data/reports/trading_agents/{市场或类别}/{股票名}/`（QwenPaw 对 `/app/db` 有写权限，**直接写文件，不要 docker cp**）；过程数据 facts 写 `/data/reports/<类别>/`（`/data` 可写）。
> 4. **MD → PDF 转换（按优先级降级）**：
>    ① `docker exec -w /app quantmind-local-quantmind python3 backend/scripts/md_to_pdf_report.py <输入.md> <输出.pdf>`（研报级排版）；
>    ② docker 不可用时，**改用 QwenPaw 内置 `pdf` 技能**把 MD 转成 PDF；
>    ③ 两者都不可用则只交付 MD，并明确告知用户 PDF 未能生成及原因。
> 5. 本文中的 `~/.claude`、`cp -r ... ~/.claude/skills` 等说明仅适用于本地 Claude Code 维护者，**QuantBot 不要执行**。

# 模型训练-推理-回测-报告（全流程）技能

覆盖 QuantMind 量化策略的**完整闭环**：训练模型 → 推理历史 → 组合回测 → 专业报告。用于验证"改个参数（周期/阈值/风控）收益会不会更好"这类问题，用数据说话而不是猜。

## 架构总览

```
① 训练模型 (run-training API)
   ├─ 模型类型: 读取 backend/shared/training/request.py::ALLOWED_MODEL_TYPES
   ├─ T+N 周期选择 (T+1/T+3/T+5...)
   ├─ 特征: 读取当前 /api/v1/models/feature-catalog 返回
   ├─ GPU: 训练 GPU 满载; 推理已改 CUDA (train.py _predict_dl/_predict_nativetft, 有算力就用 GPU)
   ├─ 质量门禁: test_rank_icir<0.05 或 test_rank_ic 非正 → status=candidate (产品逻辑, 非失败)
   |  └─ 训练 2023-2025 → 推理 2026
② 推理历史 (批量推理 API)
   ├─ 单日 /models/inference/run
   └─ 批量 range 模式 推理全年逐个交易日
③ 组合回测 (自定义脚本)
   ├─ backtest_l2_top20.py      基本 Top20 每日滚动
   ├─ backtest_l2_year.py       全年严格版 (滑点+T+1+涨跌停+ST剔除)
   └─ backtest_l2_optimized.py  优化版 (分数阈值+大盘MA+止损5%)
④ 专业报告 (report_l2_optimized.py)
   └─ 回测数据 → 研报级 MD → md_to_pdf_report.py → PDF
```

## 认证

```bash
BASE=http://localhost:8000
TOKEN=$(curl -s -X POST $BASE/api/v1/auth/login -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123","tenant_id":"default"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")
AUTH="Authorization: Bearer $TOKEN"
CT="Content-Type: application/json"
```

> ⚠️ **token 的 sub 决定模型归属**：登录签发的 JWT `sub=用户表 user_id`（如 admin 登录 → `00000001`），训练提交后模型注册到 `qm_user_models.user_id = sub`。**必须用登录接口拿 token**，不要手工构造 `sub='admin'` 之类的 token —— 否则训练模型归属错位，主栏"模型管理"（按登录用户过滤）看不到，只有后台（扫磁盘）能看到。```

---

## ① 训练模型（提交 T+N 模型训练）

### 1.0 支持的模型类型（以当前配置为准）

下表用于理解模型类别，不是固定支持数量或本机已验收声明。提交前读取 `backend/shared/training/request.py::ALLOWED_MODEL_TYPES`，并确认目标实例依赖、硬件和数据覆盖。

| 类别 | 模型 | 说明 |
|---|---|---|
| 树模型 | lightgbm / xgboost / catboost / random_forest | 快，CPU/GPU 都行；RF 注意 max_depth 限制 |
| 线性 | linear | 简单基线，常过不了质量门禁 |
| 深度学习 | mlp / gru / lstm / alstm / transformer / tabnet / tcn / nativetft | 依赖与设备支持以当前模型实现及目标训练节点为准 |

提交时 `model_type` 必须在当前白名单内；DL 参数用 `dl_params`，树模型参数用 `num_boost_round/early_stopping_rounds`。耗时从本次训练日志读取，不沿用历史机器测试数字。

### 1.1 从现有模型复刻（推荐：保特征，只改周期）

训练参数模型在 `admin_training_jobs.request_payload`。要训练 T+3 版本对比已有 T+5，**复制 T+5 的 payload 只改 target_horizon_days**，保证特征/时间/数据完全一致，只变量周期。

已有可复用脚本：`scripts/submit_t3_training.py`（从 T+5 复制改 T+3）

```bash
docker cp scripts/submit_t3_training.py quantmind-local-quantmind:/tmp/
docker exec quantmind-local-quantmind python3 /tmp/submit_t3_training.py
# 关键：从 admin_training_jobs 读 T+5 payload → target_horizon_days=3 → POST /models/run-training
```

核心逻辑（复制 payload）：
```python
async def get_t5_features():
    async with get_session() as s:
        r = await s.execute(text(
            "SELECT request_payload FROM admin_training_jobs WHERE id='train_XXXX'"))
        return json.loads(r.fetchone()[0])

t3 = get_t5_features()
t3["target_horizon_days"] = 3
t3["job_name"] = "L2_catboost_2023_2025T3"
t3["display_name"] = "L2 CatBoost T+3 (2023-2025训练)_CN"
# POST /models/run-training
```

### 1.2 训练提交后轮询状态

```bash
# runId 从提交响应拿 (train_YYYYMMDDHHMMSS_xxx)
curl -s -H "$AUTH" "$BASE/api/v1/models/training-runs/<runId>" \
  | python3 -c "import json,sys; d=json.load(sys.stdin)['data']; print(d['status'], d['progress'])"
# 训练容器名: qm-train-<runId>
docker ps | grep qm-train
# 训练日志
docker exec quantmind-local-quantmind python3 -c "
import asyncio
from backend.shared.database_manager_v2 import get_session
from sqlalchemy import text
async def m():
  async with get_session() as s:
    r = await s.execute(text(\"SELECT logs FROM admin_training_jobs WHERE id='<runId>'\"))
    print(str(r.scalar_one())[-500:])
asyncio.run(m())"
```

### 1.3 训练完成 → model 注册

训练完成 status=completed，模型注册为 `mdl_cn_train_<runId>`：
- 目录：`/app/models/users/default/admin/mdl_cn_train_*`（metadata.json + model.* + config.yaml + result.json + pred.pkl）
- 数据库：`qm_user_models` 表，`user_id` = 提交时 JWT 的 sub，`status` = ready / candidate（见 1.0 质量门禁）
- 查模型 ID：
```bash
# 最近注册的模型
curl -s -H "$AUTH" "$BASE/api/v1/research/models" | python3 -c "
import json,sys
for m in json.load(sys.stdin)['data']:
    print(m['modelId'], '|', m.get('name'))"
```

### 1.4 T+N 周期选择建议（来自实际回测）

| 周期 | 特点 |
|---|---|
| T+1 | 最灵敏，但噪音大、换手高、滑点损耗大 |
| **T+3** | **平衡**：比T+5敏锐，噪音可控（推荐首选尝试） |
| T+5 | 稳定，低频 |
| 判断 | 需要真实回测对比，不能凭感觉 |

---

## ② 批量推理历史（全年）

训练完成后，要对**历史全年**推理出每日分数（回测需要）。

### 2.1 批量推理 API（mode=range，全年逐日）

```bash
curl -s -X POST -H "$AUTH" -H "$CT" "$BASE/api/v1/models/inference/batch" \
  -d '{
    "model_id": "<T+3_model_id>",
    "mode": "range",
    "start_date": "2026-01-06",
    "end_date": "2026-08-19",
    "top_k": 500,
    "reuse_existing": true
  }'
# 返回 {batch_id, status:"pending", trade_dates, window_meta}
```

### 2.2 轮询批量推理进度

```bash
curl -s -H "$AUTH" "$BASE/api/v1/models/inference/batch/<batch_id>" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status'), d.get('progress_done'), '/', d.get('progress_total'))"
```

### 2.3 验证推理结果（分数已写入 engine_signal_scores）

```bash
docker exec quantmind-local-quantmind python3 -c "
import asyncio
from backend.shared.database_manager_v2 import get_session
from sqlalchemy import text
async def m():
  async with get_session() as s:
    r = await s.execute(text(\"SELECT MIN(trade_date),MAX(trade_date),COUNT(DISTINCT trade_date) FROM engine_signal_scores e WHERE e.run_id IN (SELECT run_id FROM qm_model_inference_runs WHERE model_id='<model_id>')\"))
    print(r.fetchone())
asyncio.run(m())"
# 预期 (2026-01-06, 2026-08-19, ~151)
```

> 注意：批量推理 range 模式耗时较长（每交易日全市场），耐心等待或后台跑。

---

## ③ 组合回测（自定义策略脚本）

### 3.1 脚本家族（`scripts/`）

| 脚本 | 用途 | 规则 |
|---|---|---|
| `backtest_l2_top20.py` | 基本版 | Top20每日滚动+每只100股+涨跌停禁买卖 |
| `backtest_l2_year.py` | 严格版 | 全年+滑点0.2%+T+1+涨跌停+ST剔除+资金分配 |
| **`backtest_l2_optimized.py`** | **优化版（推荐）** | 分数阈值+大盘MA20过滤+止损5%+ST剔除+滑点+T+1 |

### 3.2 优化版策略规则（实测最有效）

```python
BUY_THRESHOLD = 0.015   # 买入门槛：分数 ≥ 0.015（避免垃圾区）
SELL_THRESHOLD = 0.005  # 卖出门槛：分数 < 0.005 卖出
STOP_LOSS = 0.05        # 止损：亏损5%卖出
MA_WINDOW = 20          # 大盘MA20过滤：大盘<MA不新买入
SLIPPAGE = 0.002        # 滑点0.2%
```

**三大风控（把 -40% 扭转到 +32%）**：
1. **分数阈值**：只买 ≥0.015 高分（胜率 82-92%），<0.005 卖出
2. **大盘 MA 过滤**：上证 <MA20 时空仓（躲开系统性下跌，回撤 51%→11%）
3. **止损 5%**：单票亏 5% 止损（控制单票风险）

### 3.3 运行回测（拷贝进容器，数据在 /data）

```bash
docker cp scripts/backtest_l2_optimized.py quantmind-local-quantmind:/tmp/
# 临时改模型/时间：
#   MODEL_ID 改为目标模型的 id；START_DATE/END_DATE 设回测区间
# 或用 python -c 注入：
docker exec quantmind-local-quantmind python3 -c "
import sys; sys.path.insert(0,'/tmp')
import backtest_l2_optimized as b
b.MODEL_ID = '<target_model_id>'
b.signals = b.load_signals()       # 自动读该模型全部信号
# ...然后 run_backtest + report
"
```

### 3.4 解读回测指标

| 指标 | 说明 |
|---|---|
| 累计收益 / 年化 | 年化短周期外推参考 |
| **最大回撤** | 流动性/风险核心，优化版目标 <15% |
| 夏普 / 索提诺 | 风险调整后收益 |
| 止损笔数 + 贡献 | 止损控风险的成本 |
| 大盘MA空仓天数 | 躲过多少系统性下跌 |
| 资金利用率 | 目标 >80%（资金没闲置） |
| 卖出胜率 | 单笔胜率（低是因为止损主动卖在-5%） |

---

## ④ 专业报告（MD → PDF）

### 4.1 报告生成器

```bash
# report_l2_optimized.py 复用回测数据生成研报级 MD
docker cp scripts/report_l2_optimized.py quantmind-local-quantmind:/tmp/
docker cp scripts/backtest_l2_optimized.py quantmind-local-quantmind:/tmp/
docker exec quantmind-local-quantmind python3 -c "
import sys; sys.path.insert(0,'/tmp')
from report_l2_optimized import main; main()
"   # 生成 docs/L2_CatBoost_T5_优化回测报告.md
```

### 4.2 MD → PDF（研报级排版）

```bash
# md_to_pdf_report.py：深蓝封面+金色双线+斑马纹表格+红涨绿跌
docker cp "docs/xxx_report.md" quantmind-local-quantmind:/tmp/rep.md
docker exec quantmind-local-quantmind python3 /app/backend/scripts/md_to_pdf_report.py /tmp/rep.md "/tmp/xxx_report.pdf"
docker cp quantmind-local-quantmind:/tmp/xxx_report.pdf "docs/xxx_report.pdf"
```

### 4.3 报告结构（9 部分）

1. **核心业绩指标**：收益/年化/回撤/夏普/索提诺/止损/空仓天数/资金利用
2. **阶段对比**：优化版 vs 基础版 vs 原严格版（体现改进）
3. **净值曲线**：逐日净值+日收益
4. **月度收益**：各月涨跌
5. **周度收益**：各周涨跌
6-7. **Top20 盈利/亏损股**：个股贡献
8. **交易明细**：买卖/价格/盈亏/原因
9. **策略规则说明**

---


## 6. 常见问题排查

| 问题 | 处置 |
|---|---|
| 训练进度卡住 | `docker ps` 看 qm-train 容器，`docker logs` 看 train.py 输出 |
| 推理慢/超时 | range 批量后台跑，耐心等；reuse_existing=true 断点续跑 |
| 回测无买入 | 检查 MODEL_ID 是否对、分数是否 ≥0.015（分数太低自然空仓） |
| 报告收益异常 | 确认 klines 覆盖区间、涨跌停/停牌处理、cron 时间 |
| asyncio 冲突 | 混用 load_signals(asyncio) 和 psycopg2 时，加载函数统一用 psycopg2 同步 |
| 年化离谱 | 短周期外推失真，看累计收益和回撤，别信年化 |
| 训练完主栏模型管理看不到 | 后台扫描磁盘目录，主栏按登录用户查 `qm_user_models`；先核对模型归属与登录用户，不因历史目录数量判断注册是否成功 |
| 模型 status=candidate | 质量门禁未过（IC 不达标），正常流程非失败；CatBoost/Linear/NativeTFT 常落此档，推理/回测仍可用 |
| DL 训练慢/卡 epoch1 | 查看目标训练容器日志、数据加载进度与设备使用，耗时以当前节点和本次输入为准 |
| 训练/推理为何 CPU 参与 | 核对当前模型实现、数据加载和实际设备选择，不把历史 GPU 验收当成本机硬件能力 |

## 7. 相关技能

- **[[backtest-center]]** — Qlib 单策略回测/专家模式/参数优化（不同的回测层面）
- **[[batch-inference-analysis]]** — 分析推理结果选股（本技能的重心是验证策略收益）
- **[[quantmind-operations]]** — 模型训练/模型管理的运营操作
- **[[ai-ide-strategy-writing]]** — AI 写策略并执行

## 8. 模型管理（训练完去哪看模型）

| 入口 | 数据源 | 说明 |
|---|---|---|
| 后台管理 → 推理引擎 → 模型管理（admin/models/scan） | 扫磁盘 /app/models 目录 | 实际模型数量、缓存与排序以当前接口返回为准 |
| 主栏 → 模型管理（GET /models） | qm_user_models 表按当前登录用户 | 只显示本用户模型；今天新训练的模型需要归属 user_id=登录用户才可见（见认证 ⚠️） |

- 归档：qm_user_models `UPDATE ... SET status='archived'`（每用户唯一 is_default 约束：`uq_qm_user_models_default_per_user`，改默认前先摘旧）
- 训练任务：admin_training_jobs（request_payload 可复刻、logs、result）

## 9. 相关脚本

- `scripts/submit_t3_training.py` — 复刻 T+5→T+3 训练提交
- `scripts/backtest_l2_optimized.py` — 优化版组合回测（分数阈值+MA+止损）
- `scripts/backtest_l2_year.py` — 全年严格版
- `scripts/backtest_l2_top20.py` — 基础版
- `scripts/report_l2_optimized.py` — 研报级 MD 生成
- `backend/scripts/md_to_pdf_report.py` — MD→PDF 研报排版