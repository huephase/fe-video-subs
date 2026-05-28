from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import BigInteger, DateTime, Float, Integer, Text, create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql+psycopg://{os.getenv('POSTGRES_USER', 'video_subs')}:"
    f"{os.getenv('POSTGRES_PASSWORD', 'change_me')}@postgres:5432/"
    f"{os.getenv('POSTGRES_DB', 'video_subs')}",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    processing_path: Mapped[str | None] = mapped_column(Text)
    output_path: Mapped[str | None] = mapped_column(Text)
    work_dir: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    stage: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    target_language: Mapped[str] = mapped_column(Text, nullable=False)
    source_language: Mapped[str | None] = mapped_column(Text)
    config_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text)
    error_detail: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    rq_job_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class JobLog(Base):
    __tablename__ = "job_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(UUID(as_uuid=False), index=True)
    level: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

