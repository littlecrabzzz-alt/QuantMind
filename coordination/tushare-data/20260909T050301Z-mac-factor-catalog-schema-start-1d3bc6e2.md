# Factor486 catalog schema correction
- 独立worktree quantmind-tushare-factor-catalog-schema，codex/tushare-factor-catalog-schema，基线092dedf。
- Own backend/shared/tushare_intake.py only parse_document table guard; scripts/test_tushare_catalog_schema.py; config/tushare-catalog.json only486; docs/tushare-factor-catalog-schema.evidence.json. Parent runtime/ledger/progress unchanged.
- Distinguish actual 名称 header from 分类名/序号 explanation tables, retain compact/numeric fields. Preserve old/source HTML SHA and exact diff. No provider calls or production writes.
