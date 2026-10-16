# 主题：R01-P0.5 交接包终审修复完成（p05，R01P0-W3S2）— 待独立验收

- 时间、节点、任务标识：2026-09-25 05:5x（本地）/ 2026-09-24T21:5xZ · mac · R01P0-W3S2（wave 3s-fix attempt 2）
- 状态：**done（W3R 终审必修 1/2/3/5 + 两建议全部落实；待独立验收）**

## 修复对照（W3R 必修项 → 落点）

1. **AB checkpoint/环境入口**：`handover/AB-QUICKSTART.md` §5 改实际签名
   `ledger_persistence.load_checkpoint(db, package, config)`（含 async session 构造、参数一致性提醒、None 语义）；
   `handover/CHECK-COMMANDS.md` §E 补干净 shell 完整入口（.env.local 导出、DB_*/INTERNAL_CALL_SECRET/QM_NODE_ROLE/
   HOST_PROJECT_PATH/HOST_RUNTIME_PATH/RESEARCH_ENGINE_URL/RESEARCH_EXTERNAL_CONTRACT_NODE 全键、
   网络别名 research-agent、健康检查、恢复步骤），**并按文档实跑**：容器 running+jsonschema OK+capabilities 200，
   日志 `handover/evidence-w3s/06-sidecar-run-and-real-input-e2e.log`；跑完已恢复原沙盒 sidecar（:local）。
2. **真实输入绑定平台证据**：`handover/w3s2_real_input_e2e.py` 经 8000 真实网关：登记 external P0 课题 →
   data-check-report 回报（fixture=false，data.input_package_id/manifest_sha256/source_release_id=真实包值
   cd8b807e…5245 / data-fcbabbb7…）→ 同键重试 200 duplicate → POST 实际 handover/readiness.json →
   GET 回显真实绑定 → overview 两读一致；**8/8 exit 0**，归档 06 日志+06b JSON。曲线子项显式标 fixture
   （P0 无真实研究曲线），SELF-CHECK 第 8 行表述同步改写（本地沙盒范围+fixture 曲线子项）。
3. **口径统一**：511260 缺日 2017-08-17→**2018-08-17**（2017-08-17 早于上市日不可能）；就地更正
   `artifacts/p01c/scope.json`（+顶层 `errata`，revision/schema_version/frozen 不变）、`gaps.json` DG-003、
   `artifacts/p01b/{verification-pool.csv,data-gaps.json,data-inventory.md}`、handover/ASSUMPTIONS-DEFERRED；
   勘误方式记录于 `artifacts/p01c/REVISION.md` 尾节；原始探查证据（p01c/evidence，SHA256SUMS 覆盖）与
   replay-evidence.json（包级交易日历真实日期）不勘误。validator 复跑全过；残留 grep 干净（除勘误说明）。
   HANDOVER 覆盖摘要改逐标的行数表（合计 24,390 行，缺日另计）。
4. **readiness 校验归档**：`handover/evidence-w3s/07-readiness-validation.log`（jsonschema 4.25.1，
   Draft7+FormatChecker，PASS，含绑定复核）。
5. **建议项**：contract_versions.data=2 语义（主版本 2、现行 v2.2、hash 5337b291…）写入 HANDOVER §2 与
   SELF-CHECK 第 10 行；"四门 true"全部改写为"**本地 A/B 历史研究门通过**"，云端发布/register 漂移单列延期
   （HANDOVER §5、SELF-CHECK 8/10、学习入口）。
6. W2R4 稳定证据 `evidence/p0r1-w2r4-verify.md`（主控已存档），SELF-CHECK 复核链引用已更新。

## 边界遵守

- 仅写 `<run>/handover/`（含 evidence-w3s/）、`artifacts/p01c|p01b` 勘误（REVISION.md 记录方式）、学习目录入口、本记录；
  代码零改动（worktree clean @9a1f94f0）；未部署云端、未启动 A/B；沙盒临时容器已删、原 sidecar 已恢复健康。

## 下一步

- 交接包回 W3R 复核或直接独立验收；平台本地 readiness 已携带真实输入绑定（06b），独立验收通过后由验收方置
  independent_acceptance=passed。

## 追加（W3S3，2026-09-25T06:0xZ：W3R2 第 1 项小修）

- 缺陷：CHECK-COMMANDS §E 容器名（r01-accept-research-agent）与 scripts/r01_p04_e2e_validate.py:293
  硬编码重启目标（quantmind-dev-research-agent-r01）不一致，照文档跑 E2E 会失败。
- 修复（最小方案，仅文档）：§E 统一容器名并标注约束；补 builtin-regress 清理步骤
  （正确路径 state->'input'->>'key'）；按新文档干净 shell 全流程实跑（含 45/45 E2E 与真实绑定 8/8、
  清理与恢复），归档 handover/evidence-w3s/08-checkcommands-e-rerun.log；SELF-CHECK 增 W3S3 记录。
  零代码改动（worktree clean @9a1f94f0），原沙盒 sidecar 已恢复。
