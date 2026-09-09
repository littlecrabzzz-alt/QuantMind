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


## 2026-09-09 真实自动周期验收

生产已保留 `publish_interval_seconds=900`。自动发布从01:09:52Z的data-e9da1c41f9c3b8e6846db9dc3d778092f9001f52a7c764b5d5f29afb563057a4，到01:25:39Z的data-6a46d2c09cc5038ad359a7f18919abbe2d0ca26d7519e2b057b7e43d5ae9780b，实际947秒。全程没有手动发布、修改时钟、额外上游请求或暂停采集。

抓取5个真实deferred批，CURRENT校验0.98—1.08秒、整批104.27—105.81秒；到期批336请求、整批130.27秒，完整publish26.69秒。不同批请求内容和数量不同，此处证明减少常规发布开销，不是长期吞吐或线性提速结论。

以首次manifest实际覆盖水位API55186/doc4432为基线，至最终57676/4605：2490条API响应对应的raw/observation与1325个Parquet，以及73附件、60提取正文，共6438文件/261619850字节，逐个SHA校验且全部出现在新manifest，缺失0。不是用抓基线时已更高的DB水位55367/4444冒充已发布，因此中间新增181个API和12个文档尝试也纳入检查。

另读取受影响的1个document_attempt分片，173条逐一对比id/document_id/phase/created_at/完整result规范化SHA及文件引用，全部一致。API事件数表示源DB行，对应响应文件闭包已验证；没有新增或声称完整API-attempt元数据镜像格式，也不以这次测试证明全部历史完整。Mac是否追平本周期版本另查mirror状态。

证据：`/tmp/tushare-live-interval-acceptance/report.json`、同目录`state.json`，helper `/tmp/verify_tushare_live_interval.py` SHA dad6d2b8b5b6ed1b7294dfeee45c7e1a444eb4785c0ddd4fe2b2d64d967a255b。此前离线夹具验证和本次生产周期分别提供保留逻辑与实际运行证据。


同一6a46d2c0固定版本随后经标准Mac mirror同步成功：新增6448、共188149文件校验。父另外在Mac逐个重算本周期6438增量文件的SHA与字节数，261619850字节全部一致，涵盖2490原文/2490观察/1325Parquet/73附件/60提取正文。证据`/tmp/tushare-live-interval-mac-acceptance.json`及`/tmp/tushare-interval-mirror-result.json`；这补足本次周期的离线文件闭包，不代表其他历史缺口已完成。
