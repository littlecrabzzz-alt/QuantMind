# R01P0-G4P1 冻结记录（2026-09-25T09:4xZ, mac）

- 最终 HEAD=`e98feb70`（E2E 断言精修并入证据链后冻结；worktree clean，此后零代码提交）。
- 冻结轮组合证据：artifacts/p04/fixes-g4/current/（F-AC06 三反例+正例/幂等/重启；F-UI01 v2 包
  五日回放+页面数据一致+重启；F-UI02 被拒事件与文案；单测 66p+E2E 53/53+typecheck/build 0）。
- 旧 G1/G2 证据（fixes-g1/、fixes-g2/）绑定旧 HEAD，保留历史轮未覆盖。
- 沙盒恢复：r01 临时容器删、原 research-agent 健康、builtin-regress 清理。
