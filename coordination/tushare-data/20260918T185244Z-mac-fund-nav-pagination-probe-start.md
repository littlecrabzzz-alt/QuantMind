# Mac fund_nav 日期分页实证开始

- 时间、节点、任务：2026-09-18T18:52:44Z，Mac 全量归档唯一写入者，`fund-nav-date-pagination-probe-20260919`
- 状态：开始受控实证；不改变当前研究发布或云端缓存范围
- 依据：官方 `fund_nav` 文档明确支持 `nav_date` 与 `market=E/O`，但未公布单次行数上限、`limit/offset` 或完整性终止条件。当前近期规划按基金逐只请求，只有现场证明分页稳定、页间不重叠且出现不足页长的有限尾页，才允许设计等价替代。
- 范围：只在当前归档周期自然结束后短暂停 Mac worker；使用一个已结束交易日分别探测 E/O 市场，所有响应通过既有 `capture_sample` 写入不可变对象与 observation，并生成独立 probe release。禁止输出凭据、修改 `CURRENT.json`、改写现有任务或据满页推断完整。
- 回退：探针无论成功、失败或不确定都恢复原 `ENABLED` 内容和权限并重新启动 worker；证据不足时保留现有逐基金逻辑。
