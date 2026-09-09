# 沪深港通旧 4 API：官方契约仍阻塞

- Mac / remaining_markets；主树只读复核 6b18287，已重读新 AGENTS。范围仅 `/tmp/connect-legacy4-review-20260909/` 与本唯一记录，无 runtime/配置/生产写入，无候选代码提交。
- 47/49/196/197 均未注册；8 个官方网页/Markdown URL 有界读取仍为失效正文/404。官方仓库完整 18 路径树也仅总索引，没有完整契约，未发现合法替代页。
- 本地已知 4 raw + 4 observation 逐 SHA 通过：moneyflow_hsgt 1 行 7 默认列；ggt_daily 1000 行 5 默认列且 has_more=true；ggt_top10 50101；ggt_monthly 40101。这些均不能证明隐藏列、合法续页/历史/权限；不删除旧 scope，不用派生月统计替代原接口。
- 详细阻塞、来源 URL/SHA 和最小解锁步骤：`/tmp/connect-legacy4-review-20260909/handoff.md`，SHA `eded0c8cd60a68d94d538ba30f8b088c30d98153f187f00fcbd4cd7456bf5657`；机器审计 `current-official-pages.json`、`retained-raw-audit.json`、`official-repo-tree.json`，全部 SHA 见 `sha256.json`。
- 下一步优先官方 ggt_daily 分片参数及 moneyflow_hsgt 披露定义；ggt_top10 必填参数；ggt_monthly 合法名称/原月口径。没有完整 primary 证据，不创建推测纯合同；不阻其他采集。父集成时仅按需收此记录。
