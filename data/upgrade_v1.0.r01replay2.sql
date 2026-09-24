-- =====================================================================
-- R01-P0.3（R01P0-W2E3）研究账本修复升级：幂等键唯一约束 + 时区口径 +
-- 完整账本 checkpoint 持久化表
-- 属主：p03_execution（scope.json rev2 migrations_sql 规则）
-- 依赖：db_init.sql 已同步；upgrade_v1.0.r01replay1.sql 先行。幂等可重入。
-- =====================================================================

-- 1) replay_orders.client_order_id 唯一约束（W2E3 修复#6）
--    先删旧的非唯一索引，再建唯一索引；存量 NULL 不受唯一约束影响。
DROP INDEX IF EXISTS idx_replay_order_client_oid;
CREATE UNIQUE INDEX IF NOT EXISTS uq_replay_order_client_oid
    ON replay_orders (client_order_id);

-- 2) replay_risk_events.confirmed_at 统一 TIMESTAMPTZ（aware UTC 口径）
ALTER TABLE replay_risk_events
    ALTER COLUMN confirmed_at TYPE TIMESTAMPTZ
    USING confirmed_at AT TIME ZONE 'UTC';

-- 3) replay_trades.executed_at 同口径对齐（审查引用的同类瞬时列）
ALTER TABLE replay_trades
    ALTER COLUMN executed_at TYPE TIMESTAMPTZ
    USING executed_at AT TIME ZONE 'UTC';

-- 4) 完整账本 checkpoint 表（W2E3 修复#7）
CREATE TABLE IF NOT EXISTS replay_ledger_checkpoints (
    ledger_run_id   VARCHAR(160) PRIMARY KEY,
    package_id      VARCHAR(128) NOT NULL,
    state           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
