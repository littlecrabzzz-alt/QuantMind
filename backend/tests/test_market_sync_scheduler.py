"""市场定时同步调度器测试。

覆盖 _normalize 的市场建议时间预填（MARKET_SUGGESTED_TIMES）、未配置时保持
关闭、以及显式保存配置的覆盖行为，Redis 用桩对象替代。
"""

from __future__ import annotations

import pytest

from backend.services.engine.tasks.market_sync_scheduler import (
    DEFAULT_SCHEDULE,
    MARKET_SUGGESTED_TIMES,
    MARKETS,
    get_schedule,
    save_schedule,
)


class _StubRedis:
    """最小 Redis 桩：仅 get/set/exists，单测不依赖真实 Redis。"""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self.expiry = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._data[key] = value
        self.expiry[key] = ex

    def exists(self, key: str) -> bool:
        return key in self._data


@pytest.fixture()
def stub_redis(monkeypatch: pytest.MonkeyPatch) -> _StubRedis:
    stub = _StubRedis()
    monkeypatch.setattr(
        "backend.services.engine.tasks.market_sync_scheduler._redis", lambda: stub
    )
    return stub


def test_no_market_is_enabled_without_user_config(stub_redis):
    # Act：Redis 里没有任何配置时逐一读取所有市场
    got = {m: get_schedule(m) for m in MARKETS}

    # Assert：所有市场一律保持关闭，避免所有部署在同一固定时刻全量同步
    assert all(cfg["enabled"] is False for cfg in got.values()), got


def test_market_suggested_time_is_prefilled_without_enabling(stub_redis):
    # Act：Redis 里没有任何 HK 配置时读取
    cfg = get_schedule("HK")

    # Assert：建议时间只作预填，enabled 仍为 False；其余字段沿用全局默认
    assert cfg["enabled"] is False
    assert cfg["time"] == MARKET_SUGGESTED_TIMES["HK"]
    assert cfg["days"] == DEFAULT_SCHEDULE["days"]
    assert cfg["datasets"] == []


def test_suggested_times_are_staggered_and_after_midnight():
    # Assert：各市场建议时间互不错峰，且都落在次日 00:00 以后的凌晨窗口
    times = list(MARKET_SUGGESTED_TIMES.values())
    assert len(times) == len(set(times)), "各市场建议触发时间必须错开"
    assert all("00:00" <= t <= "06:00" for t in times), times


def test_ashare_has_no_market_default_and_stays_disabled_without_config(stub_redis):
    # Act：A 股不在默认表内，部署时显式保存开启配置
    cfg = get_schedule("A")

    # Assert：保持关闭，时间取 A 股建议值
    assert cfg["enabled"] is False
    assert cfg["time"] == MARKET_SUGGESTED_TIMES["A"]


def test_user_can_enable_market_explicitly(stub_redis):
    # Arrange：用户在前端显式开启港股定时
    save_schedule("HK", {"enabled": True, "time": "22:30"})

    # Act
    cfg = get_schedule("HK")

    # Assert：以用户保存的配置为准
    assert cfg["enabled"] is True
    assert cfg["time"] == "22:30"


def test_explicit_saved_config_disables_market(stub_redis):
    # Arrange：用户在前端显式关闭港股定时
    save_schedule("HK", {"enabled": False})

    # Act
    cfg = get_schedule("HK")

    # Assert：显式关闭生效；未覆盖字段沿用建议时间预填
    assert cfg["enabled"] is False
    assert cfg["time"] == MARKET_SUGGESTED_TIMES["HK"]


def test_save_and_get_roundtrip_keeps_fields_not_set_by_caller(stub_redis):
    # Arrange：只传 enabled/time 的部分配置
    saved = save_schedule("HK", {"enabled": True, "time": "22:30"})

    # Act
    loaded = get_schedule("HK")

    # Assert：保存与读回一致，调用方未传字段沿用默认值
    assert saved == loaded
    assert loaded["time"] == "22:30"
    assert loaded["days"] == DEFAULT_SCHEDULE["days"]


def test_invalid_time_in_stored_config_falls_back_to_global_default(stub_redis):
    # Arrange：绕过 API 层校验，直接把坏时间写进 Redis 配置
    save_schedule("HK", {"time": "25:00"})

    # Act
    cfg = get_schedule("HK")

    # Assert：非法 HH:MM 回退到全局默认时间而不是抛错
    assert cfg["time"] == "03:00"


def test_normalize_of_missing_config_for_unknown_market_uses_global_defaults():
    from backend.services.engine.tasks.market_sync_scheduler import _normalize

    # Act / Assert：未知 market 传入时仅应用全局默认，不抛错
    assert _normalize(None, "XX") == dict(DEFAULT_SCHEDULE)


@pytest.mark.parametrize("with_qlib,errors", [(True, []), (False, ["upstream failed"])])
def test_ashare_updates_pg_and_reports_upstream_failures(monkeypatch, stub_redis, with_qlib, errors):
    import sys
    from types import ModuleType
    from unittest.mock import Mock
    from backend.services.engine.tasks.market_sync_scheduler import run_market_sync
    source = ModuleType("backend.scripts.quantdb_daily_sync")
    source.run_daily_sync = Mock(return_value={"parquet": {"errors": errors}})
    jobs = ModuleType("backend.shared.quantdb_sync_jobs")
    for name in ("release_lock", "celery_progress_cb", "upsert_job", "_now_iso"):
        setattr(jobs, name, Mock())
    jobs.acquire_lock = Mock(return_value=True)
    jobs.new_celery_job = Mock(return_value={"job_id": "fixture"})
    monkeypatch.setitem(sys.modules, source.__name__, source)
    monkeypatch.setitem(sys.modules, jobs.__name__, jobs)
    result = run_market_sync("A", {"with_qlib": with_qlib, "datasets": ["kline"]})
    assert source.run_daily_sync.call_args.kwargs["skip_pg"] is False
    assert source.run_daily_sync.call_args.kwargs["skip_qlib"] is not with_qlib
    assert source.run_daily_sync.call_args.kwargs["datasets"] == ["kline"]
    assert result["status"] == ("partial" if errors else "completed")
    jobs.release_lock.assert_called_once()
    source.run_daily_sync.side_effect = RuntimeError("offline")
    with pytest.raises(RuntimeError, match="offline"):
        run_market_sync("A", {})
    assert jobs.upsert_job.call_args.kwargs["status"] == "failed"
    assert jobs.release_lock.call_count == 2
    source.run_daily_sync.reset_mock()
    jobs.acquire_lock.return_value = False
    assert run_market_sync("A", {})["status"] == "skipped"
    source.run_daily_sync.assert_not_called()
    assert list(stub_redis.expiry.values()) == [900]


def test_late_dispatch_catches_up_on_market_queue(monkeypatch, stub_redis):
    import sys
    from datetime import datetime
    from types import ModuleType
    from unittest.mock import Mock
    from backend.services.engine.tasks import market_sync_scheduler as scheduler
    class Late(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 9, 11, 8, 0)
    app_module = ModuleType('backend.services.engine.qlib_app.celery_config')
    app_module.celery_app = Mock()
    monkeypatch.setitem(sys.modules, app_module.__name__, app_module)
    monkeypatch.setattr(scheduler, 'datetime', Late)
    monkeypatch.setattr(scheduler, 'MARKETS', {'A': 'QuantDB'})
    scheduler.save_schedule('A', {'enabled': True, 'time': '03:00'})
    assert scheduler.dispatch_due_syncs()['dispatched'] == ['A']
    assert app_module.celery_app.send_task.call_args.kwargs['queue'] == 'market_sync'
    assert scheduler.dispatch_due_syncs()['dispatched'] == []
    stub_redis._data.pop(scheduler._LAST_RUN_KEY.format(market='A', date='2026-09-11'))
    app_module.celery_app.send_task.side_effect = RuntimeError('broker offline')
    with pytest.raises(RuntimeError, match='broker offline'):
        scheduler.dispatch_due_syncs()
    assert not scheduler._last_run_today('A', '2026-09-11')


def test_pg_partial_is_not_completed(monkeypatch):
    import sys
    from types import ModuleType
    from unittest.mock import Mock
    from backend.services.engine.tasks.market_sync_scheduler import run_market_sync
    source = ModuleType('backend.scripts.quantdb_daily_sync')
    source.run_daily_sync = Mock(return_value={'pg_fill': {'status': 'partial'}})
    jobs = ModuleType('backend.shared.quantdb_sync_jobs')
    for name in ('release_lock', 'celery_progress_cb', 'upsert_job', '_now_iso'):
        setattr(jobs, name, Mock())
    jobs.acquire_lock = Mock(return_value=True)
    jobs.new_celery_job = Mock(return_value={'job_id': 'fixture'})
    monkeypatch.setitem(sys.modules, source.__name__, source)
    monkeypatch.setitem(sys.modules, jobs.__name__, jobs)
    assert run_market_sync('A', {})['status'] == 'partial'


@pytest.mark.parametrize("result,failed", [
    ({"sources": {"north": {"error": "source missing"}}}, True),
    ({"result": {"kline": {"errors": 2}}}, True),
    ({"sources": {"north": {"status": "failed"}}}, True),
    ({"parquet": {"errors": []}, "qlib": {"status": "ok"}}, False),
])
def test_nested_source_failure_is_not_reported_as_success(result, failed):
    from backend.services.engine.tasks.market_sync_scheduler import _has_sync_errors
    assert _has_sync_errors(result) is failed
