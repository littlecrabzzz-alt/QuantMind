# 固定切片 RRG 坐标消费验收开始
- 节点 Mac；任务 remaining_markets；独立 worktree quantmind-tushare-other-markets / codex/tushare-other-markets。
- 接续 20260908T205934Z-mac-rrg-consumer-review-ready-cce7c93d.md。
- 本轮仅拥有新增 scripts/verify_tushare_rrg_coordinates.py 与 docs/tushare-rrg-coordinate-acceptance.md；不改运行模块、研究配置/笔记/research_case 或数据。
- 复用 verify_tushare_rrg_slice、固定 release 和本机已下载的冻结作者 factor_algo.py；校验源码 SHA 后直接调用等权基准/compute_rrg，测试 220/60/20 预热、截断及未来扰动因果性、缩放和日期映射。
- 输出仅隔离临时目录；无上游请求、策略发现或收益回测，整体 blocked_data 保持。父继续生产采集。
