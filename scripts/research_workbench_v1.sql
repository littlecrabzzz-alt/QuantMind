-- Additive migration; apply to the target environment before enabling research.
CREATE TABLE IF NOT EXISTS research_cases (
    case_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('strategy', 'method')),
    goal TEXT NOT NULL,
    contract JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS research_windows (
    run_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES research_cases(case_id),
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    checkpoint JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deadline_epoch DOUBLE PRECISION NOT NULL,
    lease_owner TEXT,
    lease_until DOUBLE PRECISION NOT NULL DEFAULT 0,
    UNIQUE (tenant_id, user_id, node_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS research_windows_owner ON research_windows(tenant_id, user_id, node_id, started_at DESC);
CREATE INDEX IF NOT EXISTS research_windows_pending ON research_windows(node_id, status, lease_until);
CREATE UNIQUE INDEX IF NOT EXISTS research_one_active_window ON research_windows(case_id)
    WHERE status IN ('queued', 'running', 'pause_requested', 'cancel_requested');
