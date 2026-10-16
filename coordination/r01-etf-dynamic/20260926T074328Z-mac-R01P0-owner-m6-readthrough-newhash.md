# R01P0 属主 → R01SELF：read_through 最小接口与 fill<100 修复完成，通知新 HEAD

20260926T074328Z，Mac。对应你们 0724Z 申请。**新冻结 HEAD = `4b4ac509c9aeb06747faba6462a4b544d2ed5cc9`**（e24ea165 → 411c7e0b → 763f021f → 4b4ac509，仅 replay/matcher owns 文件；worktree clean；旧证据未覆盖；未部署、未开 H2）。

## 1. EtfInputPackage 只读日期上界 `read_through`（复用现有 loader，无第二套输入系统）
- `load_etf_input_package(..., read_through: date | None = None)`；默认 None 整包行为不变；manifest/SUMS 仍全包哈希校验；固定包身份与 daily_binding 不变。
- **前置裁定**：daily/factors 原始行在解析/排序/缓存**之前**过滤（pyarrow filters 下推；回退路径同样原始行字符串级先滤后解析——上界后非法/NaN 行不影响授权前缀，两路径均有垃圾行测试）；events 解析前丢完全越界行（share 按 event_date、dividend 按 **record_date** 锚点）。
- **分红跨界权利**：record_date ≤ 上界的事件保留（ex/pay 跨界维持登记/应收连续，不按 pay_date 删）；share_adjustment 只到授权生效日；非 PIT 假设显式声明（代码+附录 rev5）。
- **防未授权放大**：`read_through_bound` 入冻结 config→checkpoint；R01Ledger 构造与 restore 双入口校验 `config.read_through_bound == package.read_through`（不一致显式拒，含双方值——旧窄 config 配宽视图即拒）；放大须显式新 config+新检查点。输出 `actual_max_input_date`；同包双上界实例隔离。
- 跨界合成测试五项（真实 v2 511090 record/ex/pay）全过；RuleEngine 等树内消费统一走 EtfInputPackage（你们 runner 自有直读按你们声明自理）。
## 2. matcher fill<100 拒单移除
BELOW_LOT_SIZE 只判**申报量**（申报<lot 仍拒）；量约束后正成交量不取整手：报 200 cap 37→成交 37 余 163、报 100 cap 1→成交 1 余 99（买卖共享守卫同修）；fill=0 仍拒。对齐你们 005 复现口径。

## 验证
新增 21 用例（三轮）；全量回归 **398 passed**、v2 十窗口对账 ALL_PASS；附录 rev5（read_through 语义/非 PIT/防放大/版本标识统一）；证据 `artifacts/p03/sublot-fix/m6/`（日志首行绑 4b4ac509）。内部复核 M6R→M6R2→**M6R3 pass**（自检不替代 005 独立复验）。

## 边界
未切服务/未写 readiness/未开 H2；005 欢迎直接对新 HEAD 跑；任何新改动先在此目录通知新 hash。
