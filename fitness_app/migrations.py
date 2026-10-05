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


def _migrate_equipment_profiles(connection) -> bool:
    """Create the equipment_profiles table if it does not exist.

    Holds rich training details for equipment (muscles used, supported
    exercises, program modes). See ``models.EquipmentProfile``.

    Args:
        connection: An open SQLAlchemy connection.

    Returns:
        True if the table was created.
    """
    inspector = inspect(connection)
    if "equipment_profiles" in inspector.get_table_names():
        return False

    connection.execute(text(
        "CREATE TABLE equipment_profiles ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "equipment_id INTEGER, "
        "machine_type VARCHAR(50) NOT NULL, "
        "name VARCHAR(200), "
        "muscles_used TEXT, "
        "supported_exercises TEXT, "
        "program_modes TEXT, "
        "details TEXT, "
        "source VARCHAR(100), "
        "created_at DATETIME, "
        "updated_at DATETIME, "
        "FOREIGN KEY (equipment_id) REFERENCES equipment (id)"
        ")"
    ))
    logger.info("Created table equipment_profiles")
    return True


def _migrate_sleep_records(connection) -> bool:
    """Create the sleep_records table if it does not exist.

    Holds per-session sleep data from Health Connect CSV exports.
    See ``models.SleepRecord``.

    Args:
        connection: An open SQLAlchemy connection.

    Returns:
        True if the table was created.
    """
    inspector = inspect(connection)
    if "sleep_records" in inspector.get_table_names():
        return False

    connection.execute(text(
        "CREATE TABLE sleep_records ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "person_id INTEGER NOT NULL, "
        "started_at DATETIME NOT NULL, "
        "ended_at DATETIME, "
        "light_min INTEGER, "
        "deep_min INTEGER, "
        "rem_min INTEGER, "
        "awake_min INTEGER, "
        "source VARCHAR(50), "
        "source_id VARCHAR(200), "
        "created_at DATETIME, "
        "FOREIGN KEY (person_id) REFERENCES person (id)"
        ")"
    ))
    connection.execute(text(
        "CREATE UNIQUE INDEX ix_sleep_records_source "
        "ON sleep_records (source, source_id)"
    ))
    logger.info("Created table sleep_records")
    return True


def _migrate_exercises(connection) -> bool:
    """Add the library-enrichment columns to the exercises table.

    Holds MIT-licensed ExerciseDB metadata imported by
    ``scripts/seed_exercises.py``. See ``models.Exercise`` and
    ``THIRD-PARTY-NOTICES.md``.

    Args:
        connection: An open SQLAlchemy connection.

    Returns:
        True if anything changed.
    """
    changed = False
    changed |= _ensure_column(
        connection, "exercises", "external_id", "VARCHAR(50)"
    )
    changed |= _ensure_column(
        connection, "exercises", "body_part", "VARCHAR(100)"
    )
    changed |= _ensure_column(
        connection, "exercises", "equipment_label", "VARCHAR(100)"
    )
    changed |= _ensure_column(
        connection, "exercises", "target_muscle", "VARCHAR(100)"
    )
    changed |= _ensure_column(
        connection, "exercises", "secondary_muscles", "TEXT"
    )
    changed |= _ensure_column(
        connection, "exercises", "instructions", "TEXT"
    )
    changed |= _ensure_column(
        connection, "exercises", "source", "VARCHAR(50)"
    )
    return changed


def _migrate_person_goal(connection) -> bool:
    """Add the weight-goal column to the person table.

    Drives goal progress on the dashboard. Nullable: no goal set reads as
    "no goal", never as zero.

    Args:
        connection: An open SQLAlchemy connection.

    Returns:
        True if anything changed.
    """
    return _ensure_column(
        connection, "person", "weight_goal_kg", "FLOAT"
    )


def _migrate_workout_sets(connection) -> bool:
    """Add set-mode, effort and superset columns.

    - ``workout_exercises.mode``: how sets are logged (reps/time/cardio).
    - ``workout_exercises.superset_group``: back-to-back grouping.
    - ``sets``: duration, distance, effort in its logged scale (RIR or
      RPE — stored as-given, never converted), set type, warm-up flag.

    Args:
        connection: An open SQLAlchemy connection.

    Returns:
        True if anything changed.
    """
    changed = False
    changed |= _ensure_column(
        connection, "workout_exercises", "mode", "VARCHAR(20)"
    )
    changed |= _ensure_column(
        connection, "workout_exercises", "superset_group", "INTEGER"
    )
    changed |= _ensure_column(
        connection, "sets", "duration_seconds", "INTEGER"
    )
    changed |= _ensure_column(
        connection, "sets", "distance_m", "FLOAT"
    )
    changed |= _ensure_column(
        connection, "sets", "effort_rir", "INTEGER"
    )
    changed |= _ensure_column(
        connection, "sets", "effort_rpe", "FLOAT"
    )
    changed |= _ensure_column(
        connection, "sets", "set_type", "VARCHAR(20)"
    )
    changed |= _ensure_column(
        connection, "sets", "is_warmup", "BOOLEAN"
    )
    return changed


def _migrate_activity_steps(connection) -> bool:
    """Add the step-count column to the activities table.

    Daily aggregates from Health Connect carry steps; storing them as a
    number (rather than inside the notes text) keeps walking summable for
    charts, the weekly breakdown and the future assistant.

    Args:
        connection: An open SQLAlchemy connection.

    Returns:
        True if anything changed.
    """
    return _ensure_column(
        connection, "activities", "steps", "INTEGER"
    )


#: Migrations applied in order at start-up. Each must be idempotent.
MIGRATIONS = (
    _migrate_body_measurements,
    _migrate_equipment_profiles,
    _migrate_sleep_records,
    _migrate_exercises,
    _migrate_person_goal,
    _migrate_workout_sets,
    _migrate_activity_steps,
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