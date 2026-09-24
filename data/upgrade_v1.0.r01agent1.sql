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
