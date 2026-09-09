# 扩展规划诊断与单次原文去重

七个真实采集批次的 planning 耗时为 25–29 秒。现有 tick 把 RRG 基金季度任务枚举计入 initialize（约 4 秒）；planning 只覆盖 plan_extended。后者既有全量标的发现，也有各冻结源序列的 islice 重放，当前不能凭总耗时确定各自贡献。本候选不改调度、额度或范围。

`timing.planning` 增加标的发现秒数、每 family/mode 的源 next、首次 next、enqueue、checkpoint 秒数及源项数。首次 next 包含原 islice 重放以及第一项，不冒称纯重放耗时；它是 source_next_seconds 的子集，不应相加。总时间含验证、签名和分配开销，各明细不构成穷尽分解。failed_stage、已完成的累积时间在异常时仍经现有 tick finally 写入状态；不记录异常原文。family 过程中失败时该段 total_elapsed_seconds 可能尚未产生，但相关 next/enqueue 时间和整体总耗时仍保留。timing 不进入 planning_state、manifest 或任务身份。

identifiers 仍遍历相同 jobs/attempts 结果，完整保留所有观察与任务。单次调用的 seen 集合按 API、原文 SHA、状态、响应格式及文件 stat 身份去重，避免不同观察引用同一原文时重复 JSON 读取与逐行建字典。没有跨 tick 缓存，不把行列表长期留内存；下一次调用重新发现。文件丢失或 stat 变化不会被旧缓存隐藏，原有错误状态不因缺文件变成正常行。

具有 request_identity_fields 的合同及 ths_hot/dc_hot 显式旁路。本次并行 market_sentiment 作者确认标的发现只映射 tdx/index/member/daily、kpl 概念及股票代码，不读请求 market，ths_hot/dc_hot 不用于发现；其 normalize 的请求身份逻辑不在本补丁范围。未来新增依赖 request 的发现必须继续旁路或完整纳入身份键，不能仅按 API/原文合并。

计数记录本次结果数、重复原文数、旁路数及可读取原文的 records 调用数。后续饱和拆分再次调用 identifiers 不会覆盖已保存的 planning 诊断。此优化不消除 SQL 全表扫描/UNION 临时树，也不解决 O(offset) 重放；大部分原文都不重复时收益可能很小。

隔离夹具：40 个不同观察引用同一份 375364 字节原文（3000 行、31 列），records 调用 40→1，约 0.18–0.20 秒→0.005–0.008 秒；标的输出字节及 SHA 完全一致。含不同 API/状态/格式、新原文与旧历史、请求市场维度旁路、缺文件、失败诊断及旧冻结 offset 测试。该比例仅适用于重复夹具，生产收益需读取新增计时与重复计数，不保证提升倍数。

```sh
PYTHONPATH=scripts UV_OFFLINE=1 uv run --python 3.10 --no-project --with httpx --with pyarrow --with duckdb python -m unittest scripts.test_tushare_discovery_timing scripts.test_tushare_history_budget scripts.test_tushare_planning_progress scripts.test_tushare_tick_timing scripts.test_tushare_extended_pipeline scripts.test_tushare_technical_extra_pipeline scripts.test_tushare_global_pipeline scripts.test_tushare_family_fairness scripts.test_tushare_publish_interval
```
