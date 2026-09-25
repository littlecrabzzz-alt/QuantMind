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
