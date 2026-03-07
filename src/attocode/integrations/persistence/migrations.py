"""SQLite schema versioning and migration support."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)

# Current schema version
CURRENT_VERSION = 2

# Migration functions: version -> SQL to upgrade FROM that version
MIGRATIONS: dict[int, str] = {
    1: """
    -- Migration from v1 to v2: add usage_logs table
    CREATE TABLE IF NOT EXISTS usage_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        iteration INTEGER NOT NULL,
        provider TEXT DEFAULT '',
        model TEXT DEFAULT '',
        input_tokens INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        cache_read_tokens INTEGER DEFAULT 0,
        cache_write_tokens INTEGER DEFAULT 0,
        cost REAL DEFAULT 0.0,
        timestamp REAL NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    );
    CREATE INDEX IF NOT EXISTS idx_usage_logs_session ON usage_logs(session_id);
    """,
}


async def get_schema_version(db: aiosqlite.Connection) -> int:
    """Get the current schema version from the database."""
    try:
        query = "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        async with db.execute(query) as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row else 0
    except Exception:
        return 0


async def set_schema_version(db: aiosqlite.Connection, version: int) -> None:
    """Set the schema version."""
    await db.execute("DELETE FROM schema_version")
    await db.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
    await db.commit()


async def check_and_migrate(db: aiosqlite.Connection) -> int:
    """Check schema version and apply any needed migrations.

    Returns the final schema version.
    Raises RuntimeError if the DB is newer than we support (downgrade rejection).
    """
    current = await get_schema_version(db)

    if current > CURRENT_VERSION:
        raise RuntimeError(
            f"Database schema version {current} is newer than supported version {CURRENT_VERSION}. "
            f"Please upgrade attocode."
        )

    if current == CURRENT_VERSION:
        return current

    if current == 0:
        # Fresh database, just set version
        await set_schema_version(db, CURRENT_VERSION)
        return CURRENT_VERSION

    # Apply incremental migrations
    for version in range(current, CURRENT_VERSION):
        migration_sql = MIGRATIONS.get(version)
        if migration_sql:
            logger.info("Applying migration v%d -> v%d", version, version + 1)
            await db.executescript(migration_sql)
            await db.commit()
        else:
            logger.warning("No migration defined for v%d -> v%d", version, version + 1)

    await set_schema_version(db, CURRENT_VERSION)
    logger.info("Schema migrated to version %d", CURRENT_VERSION)
    return CURRENT_VERSION
