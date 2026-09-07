"""Cloud training cap must override the single-tenant host-memory heuristic."""
import unittest
from unittest.mock import patch

from backend.services.engine.training.local_docker_orchestrator import _host_mem_limit_gb


class CloudTrainingLimit(unittest.TestCase):
    def test_explicit_shared_host_budget(self):
        with patch.dict("os.environ", {"TRAINING_MEMORY_LIMIT_GB": "4"}):
            self.assertEqual(_host_mem_limit_gb(), "4g")

    def test_invalid_budget_fails_closed(self):
        for value in ("0", "-1", "65", "unlimited"):
            with patch.dict("os.environ", {"TRAINING_MEMORY_LIMIT_GB": value}):
                with self.assertRaises(ValueError):
                    _host_mem_limit_gb()


if __name__ == "__main__":
    unittest.main()
