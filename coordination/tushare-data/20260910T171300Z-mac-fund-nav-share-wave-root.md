# Tushare 基金净值与份额追加批次

- 时间/节点/任务：2026-09-10T17:13Z，Mac 主集成人，fund-nav-share-wave-root。
- 状态：精确执行完成，等待正常固定版发布与Mac镜像。
- 基线：源码 `c772307632830394419fdcbe84c254c4d71cf31c`；云端与Mac固定版 `data-d5d918ce4bc2cfd3ef6e58c5caeefa29c7d9f9715cd5b8cd0d03d4d07cab64de`。

停服后从权威库固定 `fund_nav` 第5批和 `fund_share` 第4批，720项均为 `pending/tries=0`。两次plan-only均验证360项、0 authority、0凭据、0网络、0发布；生产执行分别用46.609和46.919秒完成，得到净值212 `done`/43 `empty`/105 `split_pending`，份额279 `done`/81 `empty`。不可覆盖回执 SHA256 分别为 `2cdd1fba67d8cbeff8ce9f65433e0d5edec46e4a84e53367f5bddf603d73a287`、`dbc94660abb86a6f34bbea1ebcd748665edd0aeb0ce564b37d6cf18e6ba32d10`。

停机前的常规任务 `e366f80d…` 已被worker接收；停止worker后其Celery状态为revoked，重启时明确丢弃。它不在精确清单中，不能据此声明常规批次调用严格去重。权威管线按逐请求幂等终态保留已提交结果，未完成逻辑请求由恢复后的正常队列继续处理。服务已恢复，后续以新固定版发布、Mac镜像哈希和断网reader结果作为本轮最终验收。
