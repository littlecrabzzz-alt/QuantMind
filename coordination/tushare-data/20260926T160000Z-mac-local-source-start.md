# 统一本地数据采集开始

- 用户已要求整体梳理并修改，交付最终报告；承接晚间复查中的本地采集要求。
- 分支 `codex/local-data-source-20260926`，独立 worktree `/Users/lizeyu/.codex/worktrees/quantmind-local-data-source-20260926`；基线 `de76004a`，handoff passed。
- 范围：QuantDB/BTC-ETH 本地自动采集及验证后发布到云端、云端上游采集保护、Tushare 研究接口采集范围与发布频率、文档与数据验收。主要文件为 `scripts/local_market_source.py`、`backend/shared/data_source_config.py`、相关现有采集入口、`backend/shared/tushare_pipeline.py`、聚焦测试及部署说明。
- 保留其他任务的脏文件、业务库、研究输入与结果；不启动策略、回测或交易。当前本地独立研究服务正在运行，不重启这些服务。先验证新链路，再切换旧调度。已有历史不做无差别删除。
- 业务数据派生复用现有 PG/Qlib/market snapshot 入口，跨节点只传文件版本，不搬运本地业务数据库。
