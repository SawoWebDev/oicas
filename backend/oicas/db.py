from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    kwargs: dict = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite:///:memory:"):
            from sqlalchemy.pool import StaticPool
            kwargs["poolclass"] = StaticPool  # one shared in-memory database across threads (tests)
    eng = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _):  # pragma: no cover - sqlite only
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return eng


_engine: Engine | None = None
_factory: sessionmaker | None = None


def engine() -> Engine:
    global _engine, _factory
    if _engine is None:
        s = get_settings()
        if s.database_url.startswith("sqlite:///./"):
            s.data_dir.mkdir(parents=True, exist_ok=True)
        _engine = make_engine(s.database_url)
        _factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def set_engine(eng: Engine) -> None:
    """Used by tests to point the app at an isolated database."""
    global _engine, _factory
    _engine = eng
    _factory = sessionmaker(bind=eng, expire_on_commit=False, future=True)


def session_factory() -> sessionmaker:
    engine()
    assert _factory is not None
    return _factory


@contextmanager
def session_scope() -> Iterator[Session]:
    s = session_factory()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
