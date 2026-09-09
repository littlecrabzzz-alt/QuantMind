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
