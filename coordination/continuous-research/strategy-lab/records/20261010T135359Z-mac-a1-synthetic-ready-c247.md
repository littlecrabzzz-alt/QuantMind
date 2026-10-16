# A1 隔离实现与合成测试准备完成
- Mac；状态：待新准入文件与父会话执行指令；无真实收益/标签计算。
- 分工：仅 `a1-reversal-liquidity-prereg-20261010T134414Z/implementation/`、新增统计补充/实现冻结与本记录，未触碰已有修改。
- 复用：此前冻结费用/涨跌幅阈值/ActionBook/ShareActionBook提取，保留源哈希；原生Python无Qlib，不安装，Position薄适配不代替运行平台。
- 验证：14/14合成检查通过；包括T+1/截止/跨窗、滞后特征、独立Decimal费用现金、实际持仓送转/应收、拒单残留、日期聚合/重复事件拒绝。先前测试写路径错误已纠正，未涉及数据。
- 统计在结果前冻结：日期为单位；每窗固定5日移动块、2000次、seed20261010；缺测槽保留，不跨窗；无逐股独立性声明、无块长搜索或额外显著性通过门槛。
- 证据：`.local-dev/project/data/research/diagnostics/a1-reversal-liquidity-prereg-20261010T134414Z/implementation/synthetic-checks.json`、STATISTICS-ADDENDUM.md、implementation-freeze.json。
- 下一步：收到独立input-contract及父会话执行指令后才增加受限真实读取器、固定代码再计算。退出/权益失败完整保留，禁止用成功子样本通过成本验收。
