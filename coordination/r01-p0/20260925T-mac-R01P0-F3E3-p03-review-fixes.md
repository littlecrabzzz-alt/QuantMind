# 主题：R01-P0.3 F3R 复核修复（p03_execution F3E3）

- 时间、节点、任务标识：2026-09-25 · mac · R01P0-F3E3（wave F3-fix attempt 3）
- 状态：**done**（必修 1/2/4/5 归 p03 部分全部完成）
- 提交：`herdr/r01-p0` @ `fca2e90ca2bd5af2e69a8d0ace2d774228145df6`（仅 owns 2 文件）
- 证据：`<run>/artifacts/p03/fixes-f3/`（README、acceptance-equivalent-8.json 8/8、acceptance_equivalent_8.py、original-script-current-run.log）

## 要点

1. 必修1：`_eod` 估值最后的成本回退删除——首持仓日即缺行情时 mark=0+unavailable+快照不可信（不静默改成本价）；grep 级测试锁定 owns 文件无估值 avg_cost 回退残留（合法用途白名单注明）。
2. 必修2：CONTRACT_VERSIONS 对齐 v3/v3；旧 v2 checkpoint 显式拒绝（错误含双方版本）、缺绑定字段拒绝，不静默混用。
3. 必修4：等价探针扩到原 8 断言，全部跑在 HEAD+v2 包+合同 v3 上 → 8/8；AC-06 与验收方同法 AST 提取（readiness_passes 别名赋值语义补齐，正式门控 evaluate_formal_admission 验证 pending 关门）；原脚本 KeyError 兼容说明如实记录。
4. 必修5：diff-v1-v2.json pay 日说明更正为与数据一致的准确描述（v2 应收归零+现金+150、v1 无账务）。

## 验证

全量回归 287 passed（新增 test_r01_f3.py 5 例）；v2 包十窗口 ALL_PASS 残差 0.0%；沙盒 PG 11 项全 True；ruff 全过。
