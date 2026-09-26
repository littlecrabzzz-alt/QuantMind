"""An old high-priority backlog must not bypass the research acquisition scope."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from backend.shared.tushare_pipeline import Pipeline


class CollectionScopeTest(unittest.TestCase):
    def test_scope_filters_backlog_with_and_without_rate_policy(self):
        for rate in (None, 240):
            with self.subTest(rate=rate), tempfile.TemporaryDirectory() as d:
                pipe = Pipeline(Path(d), {"entries": []})
                try:
                    paused = pipe.enqueue("income_vip", {"period": "20260630"}, 1, "history")
                    core = pipe.enqueue("adj_factor", {"trade_date": "20260924"}, 10, "20260924")
                    pipe.db.commit()
                    cfg = {"collection_api_names": ["adj_factor"], "enable_structured": True}
                    if rate: cfg["requests_per_minute"] = rate
                    row = pipe.next_job(cfg, time.monotonic() + 1, mark_inflight=True)
                    self.assertEqual(row["id"], core)
                    self.assertEqual(pipe.db.execute("SELECT state FROM jobs WHERE id=?", (paused,)).fetchone()[0], "pending")
                    self.assertIsNone(pipe.next_job(cfg, time.monotonic() + 0.01))
                finally:
                    pipe.close()

    def test_checked_in_scope_is_a_valid_contract_subset(self):
        from backend.shared.tushare_registry import contract_for
        path = Path(__file__).resolve().parents[1] / "config/tushare-local-research-only.json"
        cfg = json.loads(path.read_text())
        for api in cfg["collection_api_names"]:
            self.assertIn("group", contract_for(api))
        for family in ("structured", "market"):
            for api in cfg[family + "_apis"]:
                self.assertEqual(contract_for(api)["group"], family)
        self.assertFalse(cfg["enable_documents"])


if __name__ == "__main__":
    unittest.main()
