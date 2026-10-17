---
name: news-sentiment-research
description: "新闻情绪研究方法论：Huntly RSS 历史新闻与 FinBERT/词典情绪，事件研究、七维分析、策略回测和研报输出。样本量及结果从实际输入与本次产物读取，不沿用历史验收结论。触发词：新闻情绪、新闻规律、情绪分析、消息面、新闻回测、情绪策略。"
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

# news-sentiment-research — 新闻情绪研究方法论

把本地 Huntly RSS 新闻、情绪信号、事件研究和报告串成可复用流程。业务容器与数据库都在本地 Mac；执行前确认 `quantmind-local` 数据挂载、输入快照与研究授权，不混用隔离沙盒。本文不保存单次研究收益、验收结果或优化路线图。

## 数据链路

```
Huntly SQLite（路径以目标实际挂载为准；文章数从数据库读取）
  └─ page.connected_at = Asia/Shanghai 本地时间字符串（陷阱：无 tzinfo，需手动 replace）
      ▼
PostgreSQL news_article_enrichment 富集
  └─ huntly_page_id, tickers[] (后缀 600036.SH), sentiment_label, sentiment_score,
     event_tags[], industries[]
  └─ 情绪模型、融合权重与词典规模以当前服务配置和词表为准
      ▼
信号生成 |score| ≥ 0.25
  └─ 时间对齐: 盘中(9:30-11:30/13:00-15:00)→当日收盘成交；盘后/盘前/非交易日→下一交易日
      ▼
QuantDB 前复权日K线 data/quantdb/1_kline_data/daily_forward/dt=YYYYMMDD/data.parquet
  └─ compute_limits 涨跌停 / T+1 / ST 剔除 / 停牌顺延
      ▼
回测引擎 → 研报 MD → md_to_pdf_report.py → PDF → 落盘股票报告目录
```

## ⚠️ 核心陷阱（每个都实测踩过）

| 陷阱 | 正确做法 |
|------|---------|
| Huntly `connected_at` 是上海本地时间字符串 | `datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=SHANGHAI_TZ)`，不能用 UTC |
| 做空权益计算 | `equity = cash + (cost - close) * shares`，不是 `cash - close * shares`（曾因算错虚增 +516%） |
| 做空现金流 | 开仓 **加** 现金（收钱），平仓 **减** 现金（买回）；与做多相反 |
| 回测循环必须遍历所有交易日 | 只遍历信号日会漏掉持仓的每日止损/止盈检查（持仓 30+ 天无检查的 bug） |
| 消息日期需对齐交易日历 | 用 `bisect` 找下一交易日；盘中消息才当天成交 |
| 同股同日多篇文章 | 取绝对分值最高的一篇作为当日信号 |

## 执行流程

### 第 1 步：事件研究（消息出来后股价怎么走？）

```bash
docker exec quantmind-local-quantmind python3 /app/scripts/backtest_news_event_study.py
```

输出：利好/利空 T+0~T+20 平均累计收益曲线、胜率曲线、板块差异、强/弱信号对比、T+5 收益分布（分位数+盈亏比）。


### 第 2 步：七维深度分析（找规律）

```bash
docker exec quantmind-local-quantmind python3 /app/scripts/backtest_news_deep_analysis.py
```

| 维度 | 分析方法 |
|------|---------|
| 来源预测力 | 利好与利空后续收益差，按来源分组 |
| 时段特征 | 按消息发布时间分组比较 |
| 多篇集中 | 同股同日单篇与多篇信号对比 |
| 首日动量 | 消息日涨跌与后续收益关系 |
| 情绪反转 | 利好/利空切换后的收益 |
| 事件标签 | 按 `event_tags` 分组，标注小样本 |
| 连续信号 | 同股连续同向信号比较 |

### 第 3 步：优化策略回测（融合规律）

```bash
docker exec quantmind-local-quantmind python3 /app/scripts/backtest_news_optimized.py
```

**优化开关**（`scripts/backtest_news_optimized.py` 顶部，可独立控制每个优化项做消融实验）：

```python
ENABLE_SOURCE_FILTER = True      # 来源白/黑名单
ENABLE_TIME_FILTER = True        # 时段过滤
ENABLE_MULTI_CONFIRM = True      # 多篇确认 ≥2 篇同向
ENABLE_MOMENTUM_FILTER = True    # 首日动量（利好+涨/利空+跌才入场）
ENABLE_REVERSAL_EXIT = True      # 情绪反转出场
ENABLE_CONSECUTIVE_BOOST = True  # 连续3天同向 → 仓位 1.5x
ENABLE_TAG_BOOST = True          # 事件标签 → 仓位 1.3-1.5x
```


### 第 4 步：研报生成与落盘

```bash
# 1) 手工撰写或脚本生成 MD（结构见下文）
# 2) 容器内转 PDF（研报排版：深蓝封面+金色双线+斑马纹+红涨绿跌）
docker exec quantmind-local-quantmind python3 /app/backend/scripts/md_to_pdf_report.py /tmp/report.md /tmp/report.pdf
# 3) 落盘前端可见目录（必做，只发 /tmp = 未交付）
docker cp report.md  quantmind-local-quantmind:/data/reports/trading_agents/每日复盘/新闻情绪研究报告_$(date +%F).md
docker cp report.pdf quantmind-local-quantmind:/data/reports/trading_agents/每日复盘/新闻情绪研究报告_$(date +%F).pdf
```

报告结构：数据基础与截止时间 → 事件研究 → 来源/时段/信号强度/价格行为/标签 → 策略与费用假设 → 极端案例 → 风险局限 → 结论。统计结果必须来自本次冻结输入和真实输出，不把旧策略“最优”“100%胜率”当作当前事实。

### 第 5 步：单股新闻面三步纵深（stock-market-analysis 的 L7 层）

单股分析复用以下三步，不需要启动完整回测；它们不是一次历史研报的固定规律或来源白名单。

**① 直接消息判定** —— 窗口 `[T-2, T]` 内 Huntly 库标题 + 正文搜 `{股票名}/{code}`：
- 命中 → 记录来源、发布时间、同向报道数量和当天价格行为；所有证据注明实际日期与样本量。
- **零命中 → 明确写「个股近期无直接催化」，禁止用行业新闻冒充个股消息**

**② 相关行业归类** —— 标题含行业词（超级电容/薄膜电容/电力设备等）的新闻按板块定性：
- 利好共振源（同行量产/业绩预增）vs 利空分化源（同行亏损/行业竞争叙事），写清"间接、板块级"

**③ 分维度对照** —— 对来源/时段/多篇/首日动量/反转/标签/板块逐项核对，输出有证据的新闻面结论；与个股深分的 L2 证据交叉，不用行业新闻冒充直接催化。

## 脚本清单

| 脚本 | 用途 | 输入 | 输出 |
|------|------|------|------|
| `scripts/backtest_news_event_study.py` | 事件研究 | Huntly+PG+QuantDB | T+0~T+20 收益曲线/胜率/板块/分布 |
| `scripts/backtest_news_deep_analysis.py` | 七维深度分析 | 同上+来源/标签/市值 | 8 个分析章节 |
| `scripts/backtest_news_sentiment.py` | 基线三模式回测 | 同上 | follow/fade/long_only 对比 |
| `scripts/backtest_news_optimized.py` | 优化策略回测 | 同上+优化开关 | 消融实验+最终策略 |
| `scripts/backtest_news_compare.py` | 三模式对比运行器 | 基线脚本 | 对比表 JSON |

所有脚本在容器内运行（本地 Python 缺 asyncpg）：
```bash
docker exec quantmind-local-quantmind python3 /app/scripts/<script>.py
```
宿主机副本在 `scripts/`，容器内 `/app/scripts/`（挂载同步）。


## 关联技能

- [[news-sentiment-finbert]] — 情绪识别管线（FinBERT+词典融合的源头）
- [[quantdb-fields]] — QuantDB 字段单位速查（volume 股/amount 万元等陷阱）
- [[daily-review]] — 报告落盘「每日复盘」目录的路径规范
- [[model-train-infer-backtest-report]] — md_to_pdf_report.py 研报排版细节
- [[stock-market-analysis]] — 单股深分主技能；框架见该技能 `REFERENCES/quantdb-full-analysis-design.md`，本技能为 L7 新闻面提供方法。
