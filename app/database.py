"""Database engine, session factory and declarative Base.

Tables are created ONLY by Alembic migrations (never with create_all()).
"""

from collections.abc import Generator

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings

# Predictable constraint names keep models and migrations in agreement.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _build_engine():
    url = settings.DATABASE_URL
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and configure it.")

    if url.startswith("sqlite"):
        # SQLite is used only by the automated tests (in-memory database).
        kwargs = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
        engine = create_engine(url, **kwargs)

        @event.listens_for(engine, "connect")
        def _sqlite_connect(dbapi_connection, _record):
            # Let SQLAlchemy control transactions (needed for SAVEPOINT support).
            dbapi_connection.isolation_level = None

        @event.listens_for(engine, "begin")
        def _sqlite_begin(conn):
            conn.exec_driver_sql("BEGIN")

        return engine

    return create_engine(url, pool_pre_ping=True, pool_recycle=1800)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides one database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
