"""Lightweight schema migrations for the SQLite database.

Why this exists
---------------
``db.create_all()`` only creates tables that do not exist yet. It never adds
columns to a table that is already there, so introducing a new column on
:class:`~fitness_app.models.BodyMeasurement` would silently do nothing to an
existing ``fitness.db``.

Rather than pull in a migration framework for a handful of columns, this module
applies small idempotent upgrades at start-up:

- each migration asks the database what it already has,
- adds only what is missing,
- is safe to run on every boot.

For adding a future column, add a function to :data:`MIGRATIONS` and make it
call :func:`_ensure_column`. Keep each migration idempotent so re-running is
harmless.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from . import db

logger = logging.getLogger(__name__)


def _ensure_column(connection, table: str, column: str, ddl: str) -> bool:
    """Add a column to a table if it is not already present.

    Args:
        connection: An open SQLAlchemy connection.
        table: Table to alter.
        column: Column name to check for and add.
        ddl: The column definition, e.g. ``"BOOLEAN NOT NULL DEFAULT 0"``.

    Returns:
        True when the column was added, False when it already existed.
    """
    inspector = inspect(connection)
    if table not in inspector.get_table_names():
        return False

    existing = {c["name"] for c in inspector.get_columns(table)}
    if column in existing:
        return False

    # SQLite cannot add a column with a non-constant default or a UNIQUE
    # constraint, so definitions here must stay simple.
    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
    logger.info("Added column %s.%s", table, column)
    return True


def _migrate_body_measurements(connection) -> bool:
    """Add the columns used to record a user's conflict decisions.

    Introduced when body measurements from different sources started disagreeing
    about the same day. See ``services/measurements.py``.

    Args:
        connection: An open SQLAlchemy connection.

    Returns:
        True if anything changed.
    """
    changed = False
    changed |= _ensure_column(
        connection, "body_measurements", "is_superseded",
        "BOOLEAN NOT NULL DEFAULT 0",
    )
    changed |= _ensure_column(
        connection, "body_measurements", "superseded_by_id", "INTEGER"
    )
    changed |= _ensure_column(
        connection, "body_measurements", "superseded_at", "DATETIME"
    )
    return changed


#: Migrations applied in order at start-up. Each must be idempotent.
MIGRATIONS = (
    _migrate_body_measurements,
)


def apply_migrations() -> list[str]:
    """Apply every pending migration.

    Safe to call on every start-up; already-applied migrations do nothing.

    Returns:
        Names of the migrations that actually changed the schema this run.
    """
    applied: list[str] = []

    with db.engine.begin() as connection:
        for migration in MIGRATIONS:
            try:
                if migration(connection):
                    applied.append(migration.__name__)
            except Exception as error:  # noqa: BLE001 - never block start-up
                # A failed migration must not stop the app from booting. Log it
                # and carry on; the affected feature will report the problem.
                logger.error(
                    "Migration %s failed: %s", migration.__name__, error
                )

    if applied:
        logger.info("Applied migrations: %s", ", ".join(applied))

    return applied