"""Bounded continuation on the existing cloud Celery worker."""

from backend.services.engine.qlib_app.celery_config import celery_app


@celery_app.task(
    name="engine.tasks.tushare_acquire",
    soft_time_limit=160,
    time_limit=180,
    acks_late=True,
    reject_on_worker_lost=True,
)
def tushare_acquire():
    from backend.shared.tushare_pipeline import tick

    return tick()
