-- ============================================================
-- QuantMind Database Upgrade Script v1.0.5
-- 全局股票池 v2 简化：成员唯一事实源改为 TXT，保留旧版本/成员历史
-- ============================================================

-- 背景：v1（v1.0.4）股票池用了「单表元信息 + 版本表 + 成员表 + 混合
-- parquet 快照」的重型模型，维护成本高、对用户心智负担大。v2 收敛为：
--   - 成员 = 前缀式 TXT（/data/stock_pool/<code>.txt，一行一个，保存即生效）
--   - PG 单表 qm_stock_pool 只存元信息（新增 file_path 列）
--   - 引用守卫 qm_stock_pool_binding 保留（被引用的池不可删）
--   - 保留 qm_stock_pool_version / qm_stock_pool_member 的历史记录
--
-- 内置池（csi300 等）成分改由「启动 seed + 每日 worker」刷新成 TXT，
-- 指数成分调整自动跟进，无需人工发布。
--
-- 本脚本幂等，可重复执行。新库由 backend/shared/db_init.sql 第 64 节直接建全，
-- 且启动期 ensure_tables 也会执行同一份 DDL（migrations/001_create_stock_pool.sql）。

-- 1. 元信息表补 file_path（若库还是 v1 结构）
ALTER TABLE qm_stock_pool ADD COLUMN IF NOT EXISTS file_path TEXT;

-- 2. 保留 v1 历史表（v2 不再写入）
-- Fork: retain legacy membership history; new resolver does not write it.
-- Fork: retain legacy version history for audit and rollback.

-- 3. 状态归一：v1 的 draft/published 行统一改为 active（无发布语义了）
UPDATE qm_stock_pool
   SET status = 'active'
 WHERE status IN ('draft', 'published');
