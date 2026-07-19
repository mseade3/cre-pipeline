from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event

from cre_pipeline.config import Settings
from cre_pipeline.models import Base


def ensure_sqlite_parent(database_url: str) -> None:
    prefix = "sqlite:///"
    if database_url.startswith(prefix) and database_url != "sqlite:///:memory:":
        parent = Path(database_url.removeprefix(prefix)).expanduser().parent
        parent.mkdir(parents=True, exist_ok=True)


def create_db_engine(settings: Settings) -> Engine:
    ensure_sqlite_parent(settings.database_url)
    engine = create_engine(settings.database_url)
    if settings.database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)
