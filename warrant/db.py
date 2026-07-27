from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine
from sqlmodel import Session, SQLModel, create_engine

from warrant.config import settings

_engine: Engine | None = None


def engine() -> Engine:
    global _engine
    if _engine is None:
        url = settings.database_url
        kwargs: dict[str, object] = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kwargs)  # type: ignore[arg-type]
    return _engine


def reset_engine() -> None:
    """Test hook: drop the cached engine so a new DATABASE_URL takes effect."""
    global _engine
    _engine = None


def create_all() -> None:
    import warrant.models  # noqa: F401  (register tables)

    SQLModel.metadata.create_all(engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    with Session(engine()) as session:
        yield session


def get_session() -> Iterator[Session]:
    with Session(engine()) as session:
        yield session
