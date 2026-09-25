-- R01 P0.4 F1P1（AC-06 正式准入门控）：验收绑定快照列。
-- research_workbench_v2.sql 同步包含该 ALTER（幂等）；本文件用于既有库升级。
-- 绑定在验收首次翻 passed 时由服务端快照（commit/manifest_sha256/contract_hash），
-- 代码/输入/合同漂移后正式准入自动失效（stale），详见 external.evaluate_formal_admission。

ALTER TABLE research_project_readiness ADD COLUMN IF NOT EXISTS acceptance_binding JSONB;
