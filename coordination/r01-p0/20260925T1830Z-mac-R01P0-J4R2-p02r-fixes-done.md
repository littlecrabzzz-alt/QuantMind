# 主题：R01-P0 J4R2 / J3R 复核 1/3/4/5 runner 侧修复完成（p02r）

- 时间、节点、任务标识：2026-09-25T18:30Z、mac、R01P0-J4R2（attempt 1）
- 状态：完成（待独立验收）；提交 **afc794e2**（仅 p02r owns：virtual_run/、
  scheduler、virtual_run 测试）；证据 `<run>/artifacts/p06/h2/fixes-j4/`
  + 勘误 `<run>/artifacts/p06/h2/ERRATA.md`
- 基线：合并当日 HEAD 171be73a（含 p03 J4E1 绑定层，本批已对齐消费）。

## 各项一行

1. **证据诚信**：real-chain 脚本对账改真实判定（J2E2 精度口径：1e-6，或全部
   差异≤1ulp(1e-4) 展示舍入边界并如实记录残差/明细）；重跑 12/12 exit 0；
   J2R2 硬编码通过已勘误（ERRATA.md）。
2. **冻结输入哈希锁定**：freeze_input=注册表锁定清单（基线+截至决策日非修订
   日增量，逐项哈希）；锁定加载复验 sha（失配拒绝）；修订包不入任何运行合并；
   obtained_at 晚于时钟→基线内回退基线/基线外受阻（d0918 真实时间线实测）；
   与 p03 J4E1 绑定合同对齐（daily_increment_versions+前缀兼容恢复，
   DbCheckpointStore 改 binding-aware，去掉瞬时 package_id 全等）。
3. **调度器接线**：StaticPackageProvider 移除，build/dispatch 统一
   DailyIncrementProvider + 平台 reporter（R01_VR_AGENT_BASE 环境变量）；
   任务入口复查 enabled（禁用即停 stopped_by_config）。
4. **同日重试/受阻恢复**：missed 同日重入不读 identity（返回已记录结果）；
   data_blocked 窗口内重试重新门控、数据补齐恢复当日决策（验收场景实测）。
5. **状态语义**：last_success_at 仅计真实成功（受阻/错过排除）；next_run_at=
   实际下一调度时刻 ISO（日历口径）或 pending_activation；停止先生效后回报。
6. **全量复跑**：41/41 + 128/128 + 真实两日包 12/12 + 故障注入 7/7（含容器
   roundtrip）全绿；沙盒已恢复（0 行 0 键、原 sidecar 还原）。

## 备注

- 对账残差现状：严格 1e-6=false、max_diff=0.0001（两侧独立 4dp 展示舍入 1ulp
  边界；内部全精度）。若需 1e-6 级比较须比较全精度原件——建议 p03 后续让
  independent_recompute 输出可选全精度（待 p03 决定，非阻塞）。
- 月末信号改日历口径（provider.next_open_trade_date，日包 calendar.parquet），
  日历前沿不发伪月末信号。
