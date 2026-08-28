from __future__ import annotations

import os
import threading
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, make_url, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT_DIR / "data"
DatabaseBase = declarative_base()

_engines: dict[str, Engine] = {}
_engines_lock = threading.Lock()
_schema_lock = threading.Lock()
APPLICATION_SCHEMA_VERSION = 2


def resolve_database_url(data_dir: Path = DEFAULT_DATA_DIR) -> str:
    configured = os.getenv("DATABASE_URL", "").strip()
    if configured:
        if configured.startswith("postgres://"):
            return "postgresql+psycopg2://" + configured.removeprefix("postgres://")
        if configured.startswith("postgresql://"):
            return "postgresql+psycopg2://" + configured.removeprefix("postgresql://")
        return configured

    database_path = (data_dir / "chatgpt2api.db").resolve().as_posix()
    return f"sqlite:///{database_path}"


def database_backend_name(database_url: str) -> str:
    return make_url(database_url).get_backend_name()


def is_postgresql_url(database_url: str) -> bool:
    return database_backend_name(database_url) == "postgresql"


def display_database_url(database_url: str) -> str:
    try:
        return make_url(database_url).render_as_string(hide_password=True)
    except Exception:
        return "invalid-database-url"


def _database_cache_key(database_url: str) -> str:
    return make_url(database_url).render_as_string(hide_password=False)


def create_database_engine(database_url: str, *, shared: bool = True) -> Engine:
    cache_key = _database_cache_key(database_url)
    if not shared:
        return _build_database_engine(database_url)
    with _engines_lock:
        engine = _engines.get(cache_key)
        if engine is None:
            engine = _build_database_engine(database_url)
            _engines[cache_key] = engine
        return engine


def dispose_database_engine(database_url: str) -> None:
    """Remove one shared engine from the cache and close its connection pool."""
    cache_key = _database_cache_key(database_url)
    with _engines_lock:
        engine = _engines.pop(cache_key, None)
    if engine is not None:
        engine.dispose()


def dispose_all_database_engines() -> None:
    """Close every shared engine. Intended for process shutdown and test cleanup."""
    with _engines_lock:
        engines = tuple(_engines.values())
        _engines.clear()
    for engine in engines:
        engine.dispose()


def initialize_application_database(database_url: str) -> Engine:
    """Create and incrementally repair the current application schema."""
    engine = create_database_engine(database_url)
    with _schema_lock:
        DatabaseBase.metadata.create_all(engine)
        _apply_application_schema(engine)
    return engine


def _apply_application_schema(engine: Engine) -> None:
    """Keep additive schema changes safe for existing SQLite and PostgreSQL data."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS application_schema_meta ("
            "schema_key VARCHAR(64) PRIMARY KEY, "
            "schema_version INTEGER NOT NULL, "
            "updated_at TIMESTAMP NOT NULL)"
        ))

        if "user_sessions" in tables:
            columns = {column["name"] for column in inspector.get_columns("user_sessions")}
            if "last_seen_at" not in columns:
                column_type = "TIMESTAMP WITH TIME ZONE" if is_postgresql_url(str(engine.url)) else "TIMESTAMP"
                connection.execute(text(
                    f"ALTER TABLE user_sessions ADD COLUMN last_seen_at {column_type}"
                ))

        indexes = {
            "users": (("ix_users_created_at", "created_at"),),
            "user_sessions": (("ix_user_sessions_created_at", "created_at"),),
            "user_api_keys": (("ix_user_api_keys_created_at", "created_at"),),
            "user_wallets": (("ix_user_wallets_updated_at", "updated_at"),),
            "wallet_ledger": (("ix_wallet_ledger_user_created", "user_id, created_at"),),
            "plans": (("ix_plans_enabled_created", "enabled, created_at"),),
            "orders": (("ix_orders_user_created", "user_id, created_at"),),
            "redeem_codes": (("ix_redeem_codes_status_created", "status, created_at"),),
            "user_tasks": (("ix_user_tasks_user_created", "user_id, created_at"),),
            "usage_records": (("ix_usage_records_user_created", "user_id, created_at"),),
            "portal_audit_logs": (("ix_portal_audit_actor_created", "actor_id, created_at"),),
        }
        for table, definitions in indexes.items():
            if table not in tables:
                continue
            for index_name, columns in definitions:
                connection.execute(text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({columns})"
                ))

        connection.execute(text(
            "INSERT INTO application_schema_meta (schema_key, schema_version, updated_at) "
            "VALUES ('application', :version, CURRENT_TIMESTAMP) "
            "ON CONFLICT (schema_key) DO UPDATE SET "
            "schema_version = excluded.schema_version, updated_at = excluded.updated_at"
        ), {"version": APPLICATION_SCHEMA_VERSION})


def _positive_float(name: str, default: float) -> float:
    try:
        return max(1.0, float(os.getenv(name, str(default)) or default))
    except (TypeError, ValueError):
        return default


def _nonnegative_int(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default)) or default))
    except (TypeError, ValueError):
        return default


def _build_database_engine(database_url: str) -> Engine:
    backend = database_backend_name(database_url)
    if backend not in {"sqlite", "postgresql"}:
        raise ValueError(
            f"unsupported application database backend: {backend or 'unknown'}"
        )
    kwargs: dict[str, object] = {
        "pool_pre_ping": True,
        "pool_recycle": 3600,
    }
    if backend == "sqlite":
        timeout_seconds = _positive_float("SQLITE_BUSY_TIMEOUT_SECONDS", 30.0)
        kwargs["connect_args"] = {"timeout": timeout_seconds}
        kwargs["poolclass"] = NullPool
    else:
        kwargs.update({
            "pool_size": _nonnegative_int("DATABASE_POOL_SIZE", 10, minimum=1),
            "max_overflow": _nonnegative_int("DATABASE_MAX_OVERFLOW", 20),
            "pool_timeout": _nonnegative_int(
                "DATABASE_POOL_TIMEOUT_SECONDS",
                30,
                minimum=1,
            ),
        })

    engine = create_engine(database_url, **kwargs)
    if backend == "sqlite":
        busy_timeout_ms = int(
            _positive_float("SQLITE_BUSY_TIMEOUT_SECONDS", 30.0) * 1000
        )

        @event.listens_for(engine, "connect")
        def _configure_sqlite(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
            finally:
                cursor.close()

    return engine
