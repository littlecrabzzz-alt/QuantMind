-- Additive: planning/discussion never enters the experiment queue without approval.
CREATE TABLE IF NOT EXISTS research_drafts (
    draft_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    state JSONB NOT NULL,
    lease_owner TEXT,
    lease_until DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, user_id, node_id, input_hash)
);
CREATE INDEX IF NOT EXISTS research_drafts_owner ON research_drafts(tenant_id,user_id,node_id,updated_at DESC);
-- R01 P0.4 (R01P0-W2P)：外部执行模式持久化表。
-- research_workbench_v2.sql 同步包含本 DDL（新库初始化即建）；本文件用于既有库升级。
-- 外部回报事件全量长期保留（state.events 仅是截断镜像，见 TG-004 盘点）。

CREATE TABLE IF NOT EXISTS research_external_events (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    draft_id TEXT NOT NULL REFERENCES research_drafts(draft_id) ON DELETE CASCADE,
    project_key TEXT NOT NULL,
    workstream TEXT NOT NULL,
    source_task TEXT NOT NULL,
    source_run_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL,
    payload JSONB NOT NULL,
    payload_hash TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    apply_status TEXT NOT NULL,
    apply_note TEXT,
    applied_at TIMESTAMPTZ,
    confirmed_at TIMESTAMPTZ,
    confirmed_by TEXT,
    UNIQUE (draft_id, source_task, source_run_id, event_id)
);
CREATE INDEX IF NOT EXISTS research_external_events_stream
    ON research_external_events(draft_id, id);
CREATE INDEX IF NOT EXISTS research_external_events_runs
    ON research_external_events(draft_id, source_task, source_run_id, seq);

CREATE TABLE IF NOT EXISTS research_project_readiness (
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    project_key TEXT NOT NULL,
    object JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id, node_id, project_key)
);
-- R01 P0.4 F1P1（AC-06 正式准入门控）：验收绑定快照列。
-- research_workbench_v2.sql 同步包含该 ALTER（幂等）；本文件用于既有库升级。
-- 绑定在验收首次翻 passed 时由服务端快照（commit/manifest_sha256/contract_hash），
-- 代码/输入/合同漂移后正式准入自动失效（stale），详见 external.evaluate_formal_admission。

ALTER TABLE research_project_readiness ADD COLUMN IF NOT EXISTS acceptance_binding JSONB;
-- R01 P0.4 J2P1（H2.2-P1）：持续虚拟运行状态表（runner 直写，平台只读展示）。
-- research_workbench_v2.sql 同步包含本 DDL（幂等）；本文件用于既有库升级。

CREATE TABLE IF NOT EXISTS research_r01_run_status (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    ledger_run_id TEXT NOT NULL,
    decision_date TEXT NOT NULL,
    run_state TEXT NOT NULL,
    schedule_configured BOOLEAN NOT NULL DEFAULT FALSE,
    payload JSONB NOT NULL,
    received_at DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, node_id, ledger_run_id)
);
CREATE INDEX IF NOT EXISTS research_r01_run_status_list
    ON research_r01_run_status(tenant_id, node_id, updated_at DESC);
