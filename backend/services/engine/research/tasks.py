"""Dedicated research queue on existing Redis/Celery; no other periodic jobs."""
import asyncio
import time

from celery import Celery

from backend.services.engine.qlib_app.celery_config import BROKER_URL, BACKEND_URL
from . import runtime
from .coordinator import tick

app = Celery("research", broker=BROKER_URL, backend=BACKEND_URL)
app.conf.update(task_default_queue="research", task_serializer="json", accept_content=["json"],
    result_serializer="json", task_acks_late=True, task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1, task_time_limit=240, task_soft_time_limit=220,
    broker_transport_options={"visibility_timeout": 360}, result_expires=3600,
    beat_schedule={"research-progress": {"task": "research.tick", "schedule": 5.0, "options": {"expires": 10}},
                   "research-discussion": {"task": "research.discussion", "schedule": 10.0, "options": {"expires": 10}}})

_loop = None


@app.task(name="research.tick")
def progress():
    global _loop
    if _loop is None:
        _loop = asyncio.new_event_loop()
    result = _loop.run_until_complete(tick())
    runtime.frozen.write(runtime.ROOT / "heartbeat.json", {"at": time.time(), "node_id": runtime.settings()["node_id"]})
    return result


@app.task(name="research.discussion")
def discussion():
    global _loop
    from .drafts import tick as draft_tick
    if _loop is None:
        _loop = asyncio.new_event_loop()
    return _loop.run_until_complete(draft_tick())
