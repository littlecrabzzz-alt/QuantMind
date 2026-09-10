"""Bounded, separate acquisition and public-document consumers on the authority."""

import json
import shutil
from datetime import datetime

from backend.services.engine.qlib_app.celery_config import celery_app


DISK_RESERVE_BYTES = 100 * 2**30
DISK_WARNING_HEADROOM_BYTES = 40 * 2**30
DISK_TREND_MIN_SECONDS = 30 * 60
DISK_TREND_WARNING_HOURS = 72


def _disk_capacity_report(*, free_bytes, observed_at, previous=None):
    """Summarize the document volume without exposing paths or credentials."""
    baseline_at = observed_at
    baseline_free = free_bytes
    if isinstance(previous, dict):
        baseline_at = previous.get("baseline_observed_at", observed_at)
        baseline_free = previous.get("baseline_free_bytes", free_bytes)
    try:
        elapsed = (
            datetime.fromisoformat(observed_at) - datetime.fromisoformat(baseline_at)
        ).total_seconds()
        if elapsed < 0 or isinstance(baseline_free, bool):
            raise ValueError
        baseline_free = int(baseline_free)
    except (TypeError, ValueError):
        baseline_at, baseline_free, elapsed = observed_at, free_bytes, 0.0

    headroom = free_bytes - DISK_RESERVE_BYTES
    consumed_per_hour = (
        max(0.0, (baseline_free - free_bytes) * 3600 / elapsed)
        if elapsed >= DISK_TREND_MIN_SECONDS
        else None
    )
    hours_to_reserve = (
        max(0.0, headroom) / consumed_per_hour if consumed_per_hour else None
    )
    reasons = []
    if free_bytes < DISK_RESERVE_BYTES:
        status = "blocked"
        reasons.append("below_reserve")
    else:
        status = "healthy"
        if headroom < DISK_WARNING_HEADROOM_BYTES:
            status = "warning"
            reasons.append("low_headroom")
        if hours_to_reserve is not None and hours_to_reserve < DISK_TREND_WARNING_HOURS:
            status = "warning"
            reasons.append("reserve_within_72h_at_observed_trend")
    return {
        "status": status,
        "free_bytes": free_bytes,
        "reserve_bytes": DISK_RESERVE_BYTES,
        "headroom_bytes": headroom,
        "warning_headroom_bytes": DISK_WARNING_HEADROOM_BYTES,
        "observed_at": observed_at,
        "baseline_observed_at": baseline_at,
        "baseline_free_bytes": baseline_free,
        "trend_window_seconds": round(elapsed, 3),
        "consumption_bytes_per_hour": (
            round(consumed_per_hour, 3) if consumed_per_hour is not None else None
        ),
        "projected_hours_to_reserve": (
            round(hours_to_reserve, 3) if hours_to_reserve is not None else None
        ),
        "warning_reasons": reasons,
    }


def _previous_disk_capacity(status_path):
    try:
        status = json.loads(status_path.read_bytes())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(status, dict):
        return None
    capacity = status.get("disk_capacity")
    return capacity if isinstance(capacity, dict) else None


def _document_config():
    from backend.shared.tushare_pipeline import ROOT, authority

    authority()
    if not (ROOT / "ENABLED").exists():
        return None
    config = json.loads((ROOT / "pipeline-config.json").read_bytes())
    if (
        config.get("enable_documents") is not True
        or config.get("document_execution") != "worker"
    ):
        return None
    return config


@celery_app.task(
    name="engine.tasks.tushare_acquire",
    # A fixed-release publication currently spends about 155 seconds scanning
    # and serializing the authority manifest. Keep the Celery envelope above
    # that measured work while tick() retains its configured acquisition
    # request and wall-clock budgets.
    soft_time_limit=300,
    time_limit=330,
    acks_late=True,
    reject_on_worker_lost=True,
)
def tushare_acquire():
    from backend.shared.tushare_pipeline import tick

    dispatch = None
    document_config = _document_config()

    def dispatch_documents():
        nonlocal dispatch
        if document_config is None or dispatch is not None:
            return
        try:
            celery_app.send_task(
                "engine.tasks.tushare_documents",
                queue="tushare_documents",
                expires=110,
            )
            dispatch = {"status": "queued"}
        except Exception as exc:
            # A document broker failure must not prevent the API continuation.
            dispatch = {"status": "dispatch_failed", "error_type": type(exc).__name__}

    # Normal planning/acquisition starts the independent document worker before
    # doing its own work. A due fixed publication returns without calling this
    # hook, so the document task starts only after its long SQLite index
    # transaction and manifest write have finished.
    report = tick(before_nonpublication_work=dispatch_documents)
    if report.get("status") != "publish_deferred_documents_active":
        dispatch_documents()
    if dispatch is not None:
        report["document_dispatch"] = dispatch
    return report


@celery_app.task(
    name="engine.tasks.tushare_documents",
    soft_time_limit=105,
    time_limit=110,
    acks_late=True,
    reject_on_worker_lost=True,
)
def tushare_documents():
    """Read only the local queue/config; public attachments need no API token."""
    from backend.shared.tushare_documents import run_documents
    from backend.shared.tushare_pipeline import ROOT, atomic_json, utc_now

    config = _document_config()  # Authority check precedes every read/write.
    capacity = None
    free_bytes = None
    if config is not None:
        observed_at = utc_now()
        free_bytes = shutil.disk_usage(ROOT).free
        capacity = _disk_capacity_report(
            free_bytes=free_bytes,
            observed_at=observed_at,
            previous=_previous_disk_capacity(ROOT / "document-worker-status.json"),
        )
    if config is None:
        report = {"status": "disabled", "processed": 0}
    elif free_bytes < DISK_RESERVE_BYTES:
        report = {"status": "blocked_disk_reserve", "processed": 0}
    else:
        count = config.get("document_worker_max_documents", 100)
        seconds = config.get("document_worker_max_seconds", 90)
        workers = config.get("document_download_workers", 1)
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not 1 <= count <= 100
            or isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not 0 < seconds <= 90
            or isinstance(workers, bool)
            or not isinstance(workers, int)
            or workers not in (1, 2)
        ):
            raise ValueError(
                "Invalid document worker bounds: 1..100 stages, 0..90 seconds, 1..2 downloads"
            )
        try:
            report = run_documents(
                ROOT, max_documents=count, max_seconds=seconds, download_workers=workers
            )
        except Exception as exc:
            atomic_json(
                ROOT / "document-worker-status.json",
                {
                    "status": "worker_failed",
                    "error_type": type(exc).__name__,
                    "disk_capacity": capacity,
                    "updated_at": utc_now(),
                },
            )
            raise
    if capacity is not None:
        report["disk_capacity"] = capacity
    report = {**report, "updated_at": utc_now()}
    if ROOT.is_dir():
        atomic_json(ROOT / "document-worker-status.json", report)
    return report
