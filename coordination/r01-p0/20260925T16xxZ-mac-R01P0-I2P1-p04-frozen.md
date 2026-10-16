# R01P0-I2P1 冻结记录（2026-09-25T16:2xZ, mac）

- 最终 HEAD=`c3746c3a`（b7771fff → 331da788 → bab2ade7 → c3746c3a 证据脚本链；此后零代码提交；
  worktree clean）。
- 组合证据 artifacts/p04/h1/fixes-i1/final/：AC01（损失线 100 逐日对齐+适配层 6 日全等）、
  AC02（两路径 last_mark 全等+引用值复核）、AC03（四态+重放/重启一致）、回归四件（首行 HEAD：
  71 passed / E2E 53/53 / typecheck 0 / build 0）。旧证据保留历史轮。
- 沙盒恢复：r01 容器删、原 sidecar 健康、builtin-regress 清理。
