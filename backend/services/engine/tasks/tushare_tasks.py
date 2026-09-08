"""Bounded, separate acquisition and public-document consumers on the authority."""

import json
import shutil

from backend.services.engine.qlib_app.celery_config import celery_app


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
    soft_time_limit=160,
    time_limit=180,
    acks_late=True,
    reject_on_worker_lost=True,
)
def tushare_acquire():
    from backend.shared.tushare_pipeline import tick

    dispatch = None
    if _document_config() is not None:
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
    report = tick()
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
    if config is None:
        report = {"status": "disabled", "processed": 0}
    elif shutil.disk_usage(ROOT).free < 100 * 2**30:
        report = {"status": "blocked_disk_reserve", "processed": 0}
    else:
        count = config.get("document_worker_max_documents", 100)
        seconds = config.get("document_worker_max_seconds", 90)
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not 1 <= count <= 100
            or isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not 0 < seconds <= 90
        ):
            raise ValueError(
                "Invalid document worker bounds: 1..100 documents, 0..90 seconds"
            )
        try:
            report = run_documents(ROOT, max_documents=count, max_seconds=seconds)
        except Exception as exc:
            atomic_json(
                ROOT / "document-worker-status.json",
                {
                    "status": "worker_failed",
                    "error_type": type(exc).__name__,
                    "updated_at": utc_now(),
                },
            )
            raise
    report = {**report, "updated_at": utc_now()}
    if ROOT.is_dir():
        atomic_json(ROOT / "document-worker-status.json", report)
    return report
