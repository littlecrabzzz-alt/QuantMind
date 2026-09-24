-- =====================================================================
-- R01-P0.3（R01P0-W2E）研究账本表结构升级
-- 属主：p03_execution（scope.json rev2 migrations_sql 规则）
-- 依赖：db_init.sql 已同步更新（新库直接建全新结构）；本文件只负责
--       存量库的增量升级，可重复执行（幂等）。
-- =====================================================================

-- 1) replay_orders：ledger-contract §4 状态机字段
ALTER TABLE replay_orders
    ADD COLUMN IF NOT EXISTS qty_remaining   FLOAT NOT NULL DEFAULT 0;
ALTER TABLE replay_orders
    ADD COLUMN IF NOT EXISTS client_order_id VARCHAR(160);
ALTER TABLE replay_orders
    ADD COLUMN IF NOT EXISTS signal_date     DATE;
-- 剩余量回填：存量行 filled 即无剩余
UPDATE replay_orders
   SET qty_remaining = GREATEST(quantity - filled_quantity, 0)
 WHERE qty_remaining = 0 AND status = 'filled';
CREATE INDEX IF NOT EXISTS idx_replay_order_client_oid
    ON replay_orders (client_order_id);

-- 2) replay_risk_events：两线独立触发、逐线确认（TG-010）
CREATE TABLE IF NOT EXISTS replay_risk_events (
    id              SERIAL PRIMARY KEY,
    ledger_run_id   VARCHAR(160) NOT NULL,
    risk_event_id   VARCHAR(200) NOT NULL UNIQUE,
    risk_line       VARCHAR(20) NOT NULL,
    event_date      DATE NOT NULL,
    nav             FLOAT NOT NULL,
    threshold       FLOAT NOT NULL,
    action          VARCHAR(32) NOT NULL DEFAULT 'pause_buys',
    blocked_orders  JSONB NOT NULL DEFAULT '[]'::jsonb,
    confirmed_by    VARCHAR(128),
    confirmed_at    TIMESTAMP,
    nav_at_confirm  FLOAT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_replay_risk_event_run_date
    ON replay_risk_events (ledger_run_id, event_date);

-- 3) replay_corporate_actions：typed 事件入账流水（DG-005）
CREATE TABLE IF NOT EXISTS replay_corporate_actions (
    id              SERIAL PRIMARY KEY,
    ledger_run_id   VARCHAR(160) NOT NULL,
    symbol          VARCHAR(20) NOT NULL,
    event_date      DATE NOT NULL,
    event_type      VARCHAR(24) NOT NULL,
    qty_multiplier  FLOAT NOT NULL DEFAULT 1,
    cash_per_share  FLOAT NOT NULL DEFAULT 0,
    qty_before      FLOAT NOT NULL DEFAULT 0,
    qty_after       FLOAT NOT NULL DEFAULT 0,
    cash_delta      FLOAT NOT NULL DEFAULT 0,
    applied         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_replay_ca_run_symbol_date_type
        UNIQUE (ledger_run_id, symbol, event_date, event_type)
);
CREATE INDEX IF NOT EXISTS idx_replay_ca_run_symbol
    ON replay_corporate_actions (ledger_run_id, symbol);
