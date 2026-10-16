# R01P0-W2P4 更正记录（2026-09-25T05:3xZ, mac）— 更正 W2R3 第④项

## 被更正的表述（不成立）

artifacts/p04/README §6 表 #2 与 W2P2/W2P3 coordination 记录曾称：
"正式验收若沙盒为全新库：db_init.sql 已含全部列则无前置"。

## 核实（2026-09-25 本 worktree 当前代码）

1. `backend/shared/db_init.sql:1882-1904`：`CREATE TABLE IF NOT EXISTS user_profiles` 仅有
   `api_key TEXT`（:1900），**缺 `llm_base_url/llm_model/llm_provider/llm_extra_headers` 四列**。
2. `backend/services/api/user_app/services/auth_service.py:466` `register()`：:498-503 直接构造
   `UserProfile(...)` 并 `session.add(profile)` 后 commit；全仓 grep `_ensure_profile_table` 在
   profile_service 之外无调用者 → ORM INSERT 带全映射列，缺列即 `UndefinedColumnError`。
   `register_by_phone`（:113）同构风险。

## 更正后的延期边界（已同步 README §6 表 #2）

所有未经 ALTER 的库均缺 llm_* 四列——**含全新 db_init.sql 建库**与历史沙盒库；register 均会失败。
正式验收前置（任何库）：先执行幂等 ALTER（api_key/llm_base_url/llm_model/llm_provider/
llm_extra_headers），或属主已合入下述修复。

## 属主修复建议（两选一；最小 diff 说明，p04 不实际改文件）

- a) `db_init.sql` user_profiles 在 api_key 后补四列（`llm_base_url VARCHAR(512)`、
  `llm_model VARCHAR(128)`、`llm_provider VARCHAR(32)`、`llm_extra_headers TEXT`），
  **并**在 auth_service 的 register/register_by_phone 建档路径前置
  `ProfileService._ensure_profile_table(session)`——两处都改才同时覆盖新库与存量库；
- b) 只出发布迁移 SQL（`data/upgrade_*.sql`：`ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS ...`
  四列），按既有升级入口执行，db_init.sql 可不动。

属主：db_init.sql→p03（scope 唯一属主）；api/user_app→api 侧。分类不变：non-blocking
（A/B 历史研究与 external 回报不依赖 register）。
