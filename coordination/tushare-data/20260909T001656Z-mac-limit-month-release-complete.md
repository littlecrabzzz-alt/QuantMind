# limit4 / 月窗 / 发布计时上线与并行后续

- 当前master runtime bbe2f9e、验收文档6669e51；391隔离tests+Ruff，文档台账另12tests。双端runtime handoff已通过；本条随master提交后再核对元数据。正文进度见docs/tushare-progress.md 08:14条及docs/tushare-limit-extra-intake.md。
- 两专属消费者已恢复，并已核验新采集4c3447b8-ea3f-49d2-9ca8-c154a5e3a094、附件ba365ffd-bdc6-4b78-b098-9378578a65e1；US88fe98db-f897-42a9-932c-cc1a84860e10保持。329请求/118.014秒正常批完成，无阶段失败；所有本轮暂停均已解除。
- limit4已enable：20真实探测/1233来源行/55字段，10类别精确日/范围末日全列一致。固定d976b04a云端16查询和Mac禁网全部通过，去重975行；153348镜像文件verified。Mac验收脚本初次误读read_dataset metadata.keys，已改用实际dataset_schema接口并重跑成功，不是产品缺陷。
- 研报精确日85行仍缺file_name，保留schema_gap；source_challenge真实3786/3795原始988/984B哈希验证，不执行挑战。schema无迁移。
- 用户希望并行减少等待：今后先在独立worktree备齐候选/测试，再安排短发布窗口，固定版验收与采集并行；不得为尚未准备完的新候选长期暂停队列。RRG按所需数据范围验收，不等待全部其他市场/PDF，但保持PIT阻塞。
- 下一候选concept4严格顺序e1041f2→03d8d74→55848e1，40tests、未合入生产/未probe/未enable。下一步父独立整合全套检查；旧互联互通有界过滤probe仍未执行。全部目录/历史/修订/文档/RRG任务持续未完。
