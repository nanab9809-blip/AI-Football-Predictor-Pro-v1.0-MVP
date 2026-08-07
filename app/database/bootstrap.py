from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.database.models import Base

SCHEMA_VERSION = "7.0.0-sprint3"


def bootstrap_database(engine: Engine) -> None:
    """Create additive normalized tables and register the current schema version.

    This function is safe to run on every application start. Existing user data is
    never deleted and existing legacy tables remain compatible with Store.
    """
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL,
                description TEXT NOT NULL
            )
        """))
        conn.execute(
            text("""
                INSERT INTO schema_migrations(version, applied_at, description)
                VALUES (:version, :applied_at, :description)
                ON CONFLICT(version) DO NOTHING
            """),
            {
                "version": SCHEMA_VERSION,
                "applied_at": datetime.now(timezone.utc).isoformat(),
                "description": "License system, access control, key rotation, revocation, and history",
            },
        )

    # Backfill active licenses for existing members so upgrades do not lock them out.
    from app.security import generate_license_key
    with engine.begin() as conn:
        existing_members = conn.execute(text("""
            SELECT u.id FROM user_accounts u
            LEFT JOIN license_records l ON l.user_id=u.id
            WHERE u.role='MEMBER' AND l.id IS NULL
        """)).fetchall()
        for row in existing_members:
            conn.execute(text("""
                INSERT INTO license_records(user_id,license_key,status,activated_at,created_at,updated_at)
                VALUES (:user_id,:license_key,'ACTIVE',:now,:now,:now)
            """), {"user_id": int(row[0]), "license_key": generate_license_key(), "now": datetime.now(timezone.utc)})


def database_inventory(engine: Engine) -> dict:
    inspector = inspect(engine)
    tables = sorted(inspector.get_table_names())
    indexes = 0
    for table in tables:
        indexes += len(inspector.get_indexes(table))
    migration_rows = []
    if "schema_migrations" in tables:
        with engine.connect() as conn:
            migration_rows = [dict(row._mapping) for row in conn.execute(text(
                "SELECT version, applied_at, description FROM schema_migrations ORDER BY applied_at DESC"
            ))]
    return {
        "dialect": engine.dialect.name,
        "tables": tables,
        "table_count": len(tables),
        "index_count": indexes,
        "migrations": migration_rows,
        "schema_version": migration_rows[0]["version"] if migration_rows else None,
    }
