# 主题：R01-P0.3 跨包恢复与日增量身份修复（p03_execution J4E1）

- 时间、节点、任务标识：2026-09-25 · mac · R01P0-J4E1（wave J4 attempt 1）
- 状态：**done**（J3R 第 2 项）
- 提交：`herdr/r01-p0` @ `171be73a01095bd4ade06e25ddea8eb7cd9e3e4e`（仅 owns 3 文件）
- 证据：`<run>/artifacts/p03/h2/fixes-j4/README.md`（身份语义合同附录+验证矩阵）

## 要点

1. 合并包身份语义（合同附录）：checkpoint 绑定=基线(id+sha)+已消费日增量有序清单（各含哈希，schema v5 `input_binding`）；恢复按绑定清单**重放合并**（`rebuild_bound_package`）得确定性 package_id——新发布未消费增量不可见；消费新增量=显式阶段（`extend_binding`→前缀兼容恢复→新检查点）。
2. restore 由瞬时 package_id 全等改为**前缀兼容**（同基线、逐项版本+哈希）；篡改/换基线/非前缀/缺绑定 → CheckpointPackageMismatch。
3. 测试 5 用例：checkpoint→发布 d+1→恢复→继续==连续（含折算日，nav ≤1e-9 全等）；未绑定新包不可见（not_trade_date）；四类篡改拒绝；基线前缀扩展；语义矩阵。
4. 回归 321 passed；v2 十窗口 ALL_PASS；33/33 分红对账；AB-QUICKSTART 增日增量运行段。
