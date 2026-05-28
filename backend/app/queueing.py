from __future__ import annotations

import os

from redis import Redis
from rq import Queue


def redis_connection() -> Redis:
    return Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        password=os.getenv("REDIS_PASSWORD") or None,
        decode_responses=False,
    )


def job_queue() -> Queue:
    return Queue("video-jobs", connection=redis_connection(), default_timeout="24h")

