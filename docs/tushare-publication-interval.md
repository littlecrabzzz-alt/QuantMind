# Tushare 常规批次的发布间隔

`pipeline-config.json` 可选 `publish_interval_seconds`（非负整数，默认 `0`）。零保持现有每次正常 tick 都调用 `Pipeline.publish()` 的行为。正值仅限制常规 tick 的发布检查；采集、原始响应、每次 attempts 提交、文档登记和独立附件 worker 仍按原任务节奏继续。直接调用 `Pipeline.publish()` 始终立即执行。

例如 `900` 是两次成功发布检查之间的**最小间隔**，并非严格每 15 分钟发布：下一个 120 秒 tick 完成采集后才检查，实际可能约 16 分钟或更久；任务失败、排队会进一步延迟。Mac 独立的 15 分钟轮询可能再晚一轮，不能将云端采集完成或已发布等同于 Mac 已镜像。启用这项配置由后续部署验收决定，本候选不修改生产配置。

启用时在已有 `scheduler_state` 保存 `publish_success_at` 整数 Unix 秒。首次没有 CURRENT 必须立即发布；已有 CURRENT 必须通过指针身份及固定 manifest 校验，损坏或不安全路径保持失败，不能借降频掩盖。没有成功时间记录时也立即发布。只有 `publish()` 成功返回后才提交时间；成功的无变化检查也更新该时间，避免空闲期每批重做全量发布扫描。时钟回退导致立即重新检查，而不会按未来时间无限推迟。默认零不写这个 checkpoint，不增加 schema。

手动发布不修改 tick checkpoint，最多使下一次到期 tick 多做一次发布/无变化检查。错误保持原异常与失败报告，不宣称成功，也不在 `publish()` 失败时推进时间。已有 CURRENT 损坏不会自动删除或覆盖以绕过校验。

## 状态字段

现有 `pipeline-status.json` 和任务返回增加 `publication`；原有顶层请求/队列计数仍表示本轮**采集状态**，`release_id` 表示云端已有固定版本。

- `status`: `not_attempted`、`published`、`deferred` 或 `failed`。`published` 表示本轮发布调用成功，也包括返回同一 release 的无变化检查。
- `performed`: 仅发布调用成功返回后为 true；延后/失败不会冒充已发布。
- `pending`: 延后或未完成时为 true，保守表示当前采集/登记状态尚未完成本轮发布检查；不是精确待发布行数。成功表示本轮工作已完成发布检查，独立文档 worker 仍可能在快照之后产生新版本。
- `current_release_id`: 校验过的现有固定版本或本轮成功返回的版本；无法确认时为 null。
- `last_success_at`、`next_due_at`: 启用间隔且已知 checkpoint 时提供整数 Unix 秒；下一时间是最早应检查时间，不是交付承诺。
- `mirror_status`: 固定 `not_checked`；Mac 是否完成必须另查镜像结果。

延后时 `timing.stage_seconds.publish` 只计调度和 CURRENT 校验；不会出现本轮 `timing.publish` 子阶段，因为没有调用发布函数。

## 保留与空间折衷

原始 JSON、观察、Parquet、附件及提取正文先持久保存；API `attempts` 和文档 `document_attempts` 持续追加，文档登记按 API attempt rowid 续跑。后续发布扫描所有已保留 attempts，文档分片包含全部 refs/attempts/原文文件。因此间隔内同任务多次更新不会只剩最后一份响应；专项测试覆盖最终版到全新离线镜像的完整文件闭包。

降频会减少中间发布时点的可浏览快照；可变队列/规划/文档最新状态合并到下一版，原始证据及尝试时间线仍保留。若需立即固定一个验收时点，显式手动发布；下线前尚未发布的数据仍在云端持久存储，但最后一批需成功发布并完成镜像才可离线访问。

最新 manifest 约 66.7 MB。在大小、任务成功率等均不变的假设下，120 秒一版约 720 版/天，900 秒最小间隔最多约 96 次常规发布检查/天；手动发布另计。这只是空间增长估算，不是已测日增长或吞吐提速。旧 manifest、archive 和文档索引均不删除，格式不变；本改动也不处理已有独立 inode 副本的一次性去重。

验证入口：

```bash
uv run --no-project --python 3.10 --with httpx --with pyarrow --with duckdb python scripts/test_tushare_publish_interval.py
```
