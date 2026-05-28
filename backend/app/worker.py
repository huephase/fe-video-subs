from __future__ import annotations

from rq import SimpleWorker

from app.database import init_db
from app.queueing import job_queue, redis_connection


def main() -> None:
    init_db()
    worker = SimpleWorker([job_queue()], connection=redis_connection())
    worker.work()


if __name__ == "__main__":
    main()

