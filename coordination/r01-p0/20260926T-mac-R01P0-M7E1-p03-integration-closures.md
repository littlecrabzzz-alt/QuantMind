# 主题：R01-P0.3 三个集成闭环（p03_execution M7E1）

- 时间、节点、任务标识：2026-09-26 · mac · R01P0-M7E1（wave M7 attempt 1）
- 状态：**done**（不部署）
- **新 HEAD（冻结）**：`ed3a3d6b06577bd094242a1ea75399bbe04b6735`（仅 owns 3 文件；此后零提交）
- 证据：`artifacts/p03/sublot-fix/m7/`（README 代码行+测试对照+回归/对账日志首行 HEAD）；附录 rev6 §十

## 三项

1. ScopeExtension：显式授权同 run bound 扩展（from/to/auth 字段契约附录 rev6）；默认 restore 拒漂移不变；extension 模式其余 config 全等（夹带变化拒）；扩展入 extension_chain 留痕、状态连续、新检查点绑新 bound；合法扩展==宽视图连续运行复跑确认。
2. as-of gap 因果性：锚定日（share=event_date/div=ex_date）≤ as_of 才受阻；日初刷新=as-of ∪ 已登记 blocked；未来锚定不前视（cap 内修复）；锚定日起 fail-closed；既有 unknown_blocked 回归绿。
3. 受限 API：raw_close/adj_factor（缺行 blocked 不 ffill）/etf_limit（同上界）；raw 与 parquet 逐位相等；缓存 ≤ bound 两路径断言。

回归 415 passed（+15）；v2 十窗口 ALL_PASS。
