"""SQLite engine and session helpers (PRD-01: SQLModel on data/app.db)."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import Depends
from sqlmodel import Session, SQLModel, create_engine

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"

_engine = None


def get_engine(db_path: Path | str | None = None):
    """Return a cached engine for the app database, or a one-off engine.

    Pass db_path=':memory:' in tests for an isolated database.
    """
    global _engine
    if db_path is not None:
        url = f"sqlite:///{db_path}"
        return create_engine(url, connect_args={"check_same_thread": False})
    if _engine is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False}
        )
    return _engine


def init_db(engine=None) -> None:
    """Create all tables. Safe to call on an existing database."""
    from app import models  # noqa: F401 - register tables on the metadata

    SQLModel.metadata.create_all(engine or get_engine())


def get_session(engine=None):
    """FastAPI dependency yielding a session."""
    with Session(engine or get_engine()) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
