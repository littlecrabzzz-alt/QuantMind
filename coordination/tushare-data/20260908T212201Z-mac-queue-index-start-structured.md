# SQLite queue partial-index 性能候选
- Mac；独立 codex/tushare-queue-index，基于父 b0e1845；信用2a4bbb1仍保留原分支不带入。
- 归属：pipeline __init__/next_job/expand必要范围及新专项test；不改tick/配额/并发/生产。
- 临时50万jobs/40万pending：group P50 6.86→0.00425ms；fallback33.95→0.00421ms；expand31.06→0.00910ms；索引增加10.2MiB，一次创建0.240s。全family被gate挡住仍须扫描，未解决。
- 原TEMP排序被移除；最小v5三个partial indexes，unexpanded保持旧索引遍历次序，next_job显式INDEXED BY避免优化器选回旧排序索引。所有谓词/排序/公平/配额不变。
- 临时测量报告：/var/folders/6m/svdmp5hd6lj09292v8mt73fw0000gn/T/quantmind-queue-index-4iq2ur94/report.json；可重跑入口 /tmp/quantmind-queue-index-bench.py。非生产提速结论。
