from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


MIGRATIONS_DIR = Path(__file__).with_name("migrations")


@dataclass(frozen=True, slots=True)
class Migration:
    """One SQL migration file discovered from the migrations directory."""

    version: str
    name: str
    path: Path


def migrate_db(path: str | Path, migrations_dir: str | Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending SQLite migrations and return applied versions."""
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    migration_path = Path(migrations_dir)
    applied_now: list[str] = []

    with sqlite3.connect(db_path) as conn:
        _ensure_migration_table(conn)
        applied = _applied_versions(conn)

        for migration in _discover_migrations(migration_path):
            if migration.version in applied:
                continue
            _record_equivalent_schema(conn, migration, applied)
            if migration.version in applied:
                continue
            # executescript keeps each migration readable as plain SQL.
            conn.executescript(migration.path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                (migration.version, migration.name),
            )
            applied_now.append(migration.version)

    return applied_now


def _record_equivalent_schema(
    conn: sqlite3.Connection,
    migration: Migration,
    applied: set[str],
) -> None:
    """Record migrations already represented by a pre-migration local schema."""
    if migration.version == "001" and _table_exists(conn, "talks"):
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (?, ?)",
            (migration.version, migration.name),
        )
        applied.add(migration.version)


def current_version(path: str | Path) -> str | None:
    """Return the latest applied migration version for inspection."""
    db_path = Path(path)
    if not db_path.exists():
        return None

    with sqlite3.connect(db_path) as conn:
        if not _table_exists(conn, "schema_migrations"):
            return None
        row = conn.execute("SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1").fetchone()
    return str(row[0]) if row else None


def _ensure_migration_table(conn: sqlite3.Connection) -> None:
    """Create migration bookkeeping before applying project schema."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _applied_versions(conn: sqlite3.Connection) -> set[str]:
    """Load applied versions for idempotent migration runs."""
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {str(row[0]) for row in rows}


def _discover_migrations(path: Path) -> list[Migration]:
    """Find SQL migrations sorted by their numeric filename prefix."""
    migrations: list[Migration] = []
    for file_path in sorted(path.glob("*.sql")):
        version, _, name = file_path.stem.partition("_")
        migrations.append(Migration(version=version, name=name or file_path.stem, path=file_path))
    return migrations


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Check SQLite metadata without raising on fresh databases."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None
