# 三项 Tushare 候选已集成，准备生产发布

- master 已依次集成 `stk_rewards` 已观察报告期补采、固定版 RRG 股票单时点输入工具、饱和标识拆分延迟恢复；对应提交 `760a817`、`c80e384`、`cdc4e20`。保留其他未提交研究文件，不改配额、超时、资源、配置、schema 或已发布数据。
- Python 3.10 全部 `test_tushare*.py` 共 836 项通过、5 项因本机缺少科学计算依赖按设计跳过；关键组合路径 50 项通过。Ruff 与 `git diff --check` 通过。固定版 RRG 科学计算路径另有 Python 3.12 九项通过证据。
- 云端部署前只读基线 2026-09-09T20:05:28Z：CURRENT `data-480261b...`；`stk_rewards` 2 个作业（1 个 code-only、1 个 end_date；done1/blocked1）、2 次 attempts；延迟标记 0；stock_context 已启用，planning/publish 均 900 秒。压缩 JSON SHA256 `9bc1f26abbc6576d061440b2e87e8527ea6427fc670dd29694da6df3bc6ee6e0`。
- 发布只需对齐源码/Git，停止采集 consumer 接新任务并让当前 `8c6a1bc0-9b58-4387-ba85-3ff02cde72fb` 自然排空，随后仅重启 `tushare-worker` 并恢复该 consumer。文档/普通 US worker 不动。真实验收分别核对新报告期任务、零 HTTP 延迟拆分和后续正常采集；未观察到对应事件前不宣称生产超时已修复。
