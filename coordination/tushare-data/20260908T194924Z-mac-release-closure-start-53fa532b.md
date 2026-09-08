# Retained release closure start

text_contracts owns backend/shared/tushare_archive.py and scripts/test_tushare_archive.py only, isolated codex/tushare-text merged master b199eab. Parent owns pipeline/store/registry. Proposed incremental per-release manifest retention with immutable previous-release file closure and read-only archive lookup. Legacy frozen-scan misses receive release-only catchup; no full immutable-tree rescan each publish. Pending parent interface agreement; all verification temporary-directory offline only.
