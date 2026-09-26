"""Run with unittest inside the real Engine image (which provides Qlib)."""
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock


class ComparisonOwnership(unittest.IsolatedAsyncioTestCase):
    async def test_result_identity_is_authoritative(self):
        from backend.services.engine.qlib_app.schemas.backtest import QlibBacktestResult
        from backend.services.engine.qlib_app.services.backtest_service_query import QlibBacktestServiceQueryMixin
        service = QlibBacktestServiceQueryMixin()
        rows = [QlibBacktestResult(backtest_id=str(i), user_id='10000001', tenant_id='default',
            created_at=datetime.now(timezone.utc), status='completed',
            config={'executor_kind': 'r01_ledger'}) for i in range(2)]
        service._persistence = type('Store', (), {'get_multiple_results': AsyncMock(return_value=rows)})()
        result = await service.compare_backtests('0', '1', '10000001', 'default')
        self.assertEqual(result['backtest1']['user_id'], '10000001')
        rows[1].user_id = 'other'
        rows[1].config['user_id'] = '10000001'
        with self.assertRaisesRegex(ValueError, '无权访问'):
            await service.compare_backtests('0', '1', '10000001', 'default')
