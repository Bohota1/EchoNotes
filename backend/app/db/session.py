"""Engine, session factory and schema creation.

The only module that opens the database.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import Base

settings = get_settings()

_is_sqlite = settings.database_url.startswith("sqlite")

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    future=True,
    # Test a pooled connection with a cheap round trip before handing it out,
    # and replace it transparently if it has died. Managed Postgres closes idle
    # connections from its side - Neon's free tier suspends the database
    # entirely after a few minutes of inactivity - and SQLAlchemy otherwise
    # hands the next request a socket that is already gone, which surfaces as a
    # bare Internal Server Error on the first capture after a break. Costs one
    # trivial query per checkout. Pointless for SQLite, where there is no
    # connection to go stale.
    pool_pre_ping=not _is_sqlite,
    # Retire connections older than this rather than waiting for them to fail
    # the ping. Comfortably under the idle timeouts managed providers use.
    pool_recycle=280 if not _is_sqlite else -1,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


if _is_sqlite:

    @event.listens_for(Engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):
        """SQLite ignores FKs unless asked, so ON DELETE CASCADE would not fire."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def init_db() -> None:
    """Create the data directory and any missing tables."""
    if _is_sqlite:
        db_path = settings.database_url.replace("sqlite:///", "")
        parent = db_path.rsplit("/", 1)[0] if "/" in db_path else "."
        from pathlib import Path

        Path(parent).mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session for use outside a request (scripts, pipeline, tests)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
