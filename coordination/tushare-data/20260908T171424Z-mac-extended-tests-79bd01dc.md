# 新版采集器独立故障验收

- Mac / structured_contracts；提交 50663228d7e0fce6bfdceb7ec959515840bb8a47，分支 codex/tushare-structured。
- 接续主任务全目标及 20260908T170212Z-mac-market-ready-a96c532b.md；本次仅新增 scripts/test_tushare_extended_pipeline.py，不修改父候选代码。
- 测试通过显式 sys.path 导入 quantmind-tushare-data-intake 候选；支持 --pipeline-root 参数。候选 pipeline 文件 SHA256：3894c1574f75b2beae0e001bc97da7e9a7a3a596913a835c0085571f1e7b9f8c

7 项测试通过、Ruff 通过：规划器有界入队/连接重开/次日旧历史不重复；同 API 不同 src 的权限拒绝隔离；饱和闰年日期切分及单日停止；组公平挑选；每轮1请求+重开仍轮转；基金经理分页断点后空尾/短尾/重复页停止；v1/v2→v3迁移保留 jobs、attempts、rate gates。
只读公开目录、临时 SQLite/原始响应/Parquet，MockTransport 模拟全部 API；socket connect/DNS 和 get_secret 均禁止。
曾复现跨重开轮转位置归零，父执行者已添加 scheduler_state 持久化，本测试修复后通过；market fallback 参数与发现族由父修复。
下一步：主任务 cherry-pick 5066322，继续云端有界真实验收与镜像。离线通过不代表账号权限、全历史、正文/PIT完整。
