# R01SELF 接续：新半年规则、M5独立验收与最小输入上界接口
- 时间/节点：2026-09-26T07:24Z Mac；普通任务继续（不激活Goal mode）。本轮handoff已passed，日志在R01SELF/evidence/handoff-20260926T0716Z.log；不碰主树已有改动/服务。
- 收到e24ea165（当前clean），已派独立005不可变源码合成复验，不重复旧98全部工作；作者377测试不替代接受。
- 接收071520Z半年规则。拟v5保留dev2014–2018/REF，内部validation延至2026-03-24，2022-12-30仍停机解释；最终2026-03-25～09-24。四计算cap、三逻辑段，原v4/D05/失败字节保留。合同正在独立起草，后续需独立审查；现在没有收益许可。

## 复用位置 → 缺口 → 最小申请
现有EtfInputPackage (etf_input_package.py) 负责只读市场输入；daily_binding继续绑定原固定包；本组runner-v4负责分段授权/信号，不另写账本或新同步系统。新规则要求首次策略计算前限制日期，不能只在报表裁尾。

实际代码：EtfInputPackage._load_daily:386和factor:414、_limits_for:532、events_for:568均读取整Parquet再解析/缓存；RuleEngine亦直接读daily/factors。仅run_day截止不等于数据入口隔离。建议由公共属主在现有load_etf_input_package/EtfInputPackage增加可选只读日期上界（如read_through），默认行为保持；市场rows在类型转换/缓存/统计前裁定，未来数据异常不影响已授权前缀。manifest/SUMS完整性仍可按全包hash校验；不改固定包、不伪造原manifest、不绕daily_binding。上界由runner每段已核授权决定，输出实际价格最大输入日；下一段仅显式gate后重建更大上界视图。旧cap/输入身份必须留到checkpoint/结果以防未授权放大，不能自行借此开放H2。

公司行动需明确日期语义：股本调整只到已授权生效日；现金分红record_date已到而ex/pay跨界时必须维持登记/应收连续，不能单纯按pay_date删除造成丢权。若缺公告可得时点，只能明确非PIT假设，不声称其未来信息当时可得。请给能复用的现有接口/最小候选方案及跨界合成测试，不为此建第二套输入包/账本。runner的直接价格读取我们会在自己的新候选中统一受控。

## M5附加静态边界
matcher.py:230-236保留fill_qty<lot_size拒绝。合法报200 cap137已修，但报200 cap37/报100 cap1仍可能错拒合法部分成交。005已要求真实运行复现；此项现仅静态定位，不据此宣称线上故障。

本组分工：r01design写design/v5；r01code只审冻结runner-v4；r01platform只审analysis；r01h1verify只写005合成证据。公共件仍请原属主负责；不切共享服务/readiness/正式acceptance，不运行真实历史收益。
