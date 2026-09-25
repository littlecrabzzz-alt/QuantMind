-- =====================================================================
-- R01-P0.3（R01P0-J2E1 / H2.1-L3）虚拟运行配置与恢复点载体
-- 属主：p03_execution（scope h2 增量；幂等可重入）
-- 依赖：db_init.sql 已同步；upgrade_v1.0.r01replay1/2.sql 先行。
-- =====================================================================

-- 1) r01_virtual_run_config：启用配置（r01vr-；未配置=待启用不自动跑六组）
CREATE TABLE IF NOT EXISTS r01_virtual_run_config (
    ledger_run_id           VARCHAR(160) PRIMARY KEY,
    enabled                 BOOLEAN NOT NULL DEFAULT FALSE,
    strategy_id             VARCHAR(128) NOT NULL,
    strategy_version        INTEGER NOT NULL,
    "group"                 VARCHAR(8) NOT NULL,
    initial_cash            FLOAT NOT NULL DEFAULT 30000,
    granularity_check_cash  FLOAT NOT NULL DEFAULT 20000,
    risk_config             JSONB NOT NULL DEFAULT '{}'::jsonb,
    data_source             JSONB NOT NULL DEFAULT '{}'::jsonb,
    execution_window        JSONB NOT NULL DEFAULT '{}'::jsonb,
    schedule_key            VARCHAR(200),
    source_plan_ref         VARCHAR(300),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_r01vr_config_enabled
    ON r01_virtual_run_config (enabled, "group");

-- 2) r01_virtual_run_state：H2.2-R3 恢复点（阶段幂等键 run+date+stage）
CREATE TABLE IF NOT EXISTS r01_virtual_run_state (
    id              SERIAL PRIMARY KEY,
    ledger_run_id   VARCHAR(160) NOT NULL,
    decision_date   DATE NOT NULL,
    stage           VARCHAR(24) NOT NULL,
    status          VARCHAR(16) NOT NULL DEFAULT 'done',
    detail          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_r01vr_state_run_date_stage
        UNIQUE (ledger_run_id, decision_date, stage)
);
CREATE INDEX IF NOT EXISTS idx_r01vr_state_run_date
    ON r01_virtual_run_state (ledger_run_id, decision_date);
