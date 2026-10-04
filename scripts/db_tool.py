"""Database inspection and backup tool for the fitness tracker.

Runs identically on the dev PC and on the Pi (inside the container) because it
locates the project root relative to its own file location. No hardcoded paths.

Usage:
    python scripts/db_tool.py info
    python scripts/db_tool.py backup
    python scripts/db_tool.py restore <backup-name>
    python scripts/db_tool.py export

Commands:
    info      Row counts, latest weight/BMI, last import, set-aside readings.
    backup    Create a timestamped snapshot in backups/ using SQLite's backup API.
    restore   Restore a backup (backs up the current DB first, automatically).
    export    Dump the database to a portable .sql file.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Project root is the parent of the scripts/ folder. This makes the tool
# location-independent: it works the same on the PC and on the Pi.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
BACKUP_DIR = PROJECT_ROOT / "backups"
DB_PATH = DATA_DIR / "fitness.db"


def get_connection() -> sqlite3.Connection:
    """Open a read-only connection to the database.

    Read-only so this tool can run while the app is writing to the DB without
    risking a lock conflict.

    Returns:
        A read-only SQLite connection.

    Raises:
        SystemExit: If the database file does not exist.
    """
    if not DB_PATH.exists():
        print(f"ERROR: database not found at {DB_PATH}")
        print("       Run an import first, or check that you are in the project folder.")
        sys.exit(1)
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def cmd_info() -> None:
    """Print summary information about the database."""
    conn = get_connection()
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()

        print(f"Database : {DB_PATH}")
        print(f"Size     : {DB_PATH.stat().st_size / 1024:.1f} KB")
        print()
        print("Tables:")
        for (table_name,) in tables:
            count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            print(f"  {table_name:<25} {count:>6} rows")

        print()

        # Latest body measurements
        for mtype, label in (("weight", "Weight"), ("bmi", "BMI")):
            try:
                row = conn.execute(
                    f"SELECT value, measured_at, source FROM body_measurements "
                    f"WHERE measurement_type=? ORDER BY measured_at DESC LIMIT 1",
                    (mtype,),
                ).fetchone()
                if row:
                    print(f"Latest {label:<6}: {row[0]} on {row[1][:10]} from {row[2]}")
            except sqlite3.OperationalError:
                pass  # Table does not exist yet

        # Last import
        try:
            row = conn.execute(
                "SELECT source, imported_at FROM import_log "
                "ORDER BY imported_at DESC LIMIT 1"
            ).fetchone()
            if row:
                print(f"Last import : {row[0]} at {row[1]}")
        except sqlite3.OperationalError:
            pass

        # Set-aside readings
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM body_measurements WHERE is_superseded = 1"
            ).fetchone()[0]
            print(f"Set aside    : {count} reading(s)")
        except sqlite3.OperationalError:
            pass

    finally:
        conn.close()


def cmd_backup() -> None:
    """Create a timestamped backup of the database.

    Uses SQLite's online backup API, which produces a consistent snapshot even
    if the database is being written to at the time.
    """
    if not DB_PATH.exists():
        print(f"ERROR: database not found at {DB_PATH}")
        sys.exit(1)

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = BACKUP_DIR / f"fitness-{timestamp}.db"

    source = sqlite3.connect(DB_PATH)
    dest = sqlite3.connect(backup_path)
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()

    print(f"Backup created: {backup_path}")
    print(f"Size          : {backup_path.stat().st_size / 1024:.1f} KB")


def cmd_restore(backup_name: str) -> None:
    """Restore a backup.

    Before restoring, the current database is automatically copied to
    backups/fitness-<timestamp>-pre-restore.db so the restore itself is
    reversible.

    Args:
        backup_name: Backup file name, or a unique substring of one.
    """
    if not BACKUP_DIR.exists():
        print(f"ERROR: no backups folder at {BACKUP_DIR}")
        sys.exit(1)

    backup_path = BACKUP_DIR / backup_name
    if not backup_path.exists():
        # Allow a partial match so "20261004" finds "fitness-20261004-020000.db".
        matches = sorted(BACKUP_DIR.glob(f"*{backup_name}*"))
        matches = [m for m in matches if m.is_file()]
        if not matches:
            print(f"ERROR: no backup matching {backup_name!r} in {BACKUP_DIR}")
            sys.exit(1)
        backup_path = matches[0]

    # Safety net: never restore without first preserving the current state.
    if DB_PATH.exists():
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safety = BACKUP_DIR / f"fitness-{timestamp}-pre-restore.db"
        shutil.copy2(DB_PATH, safety)
        print(f"Safety copy of current DB: {safety}")

    shutil.copy2(backup_path, DB_PATH)
    print(f"Restored: {backup_path}")
    print(f"      to: {DB_PATH}")


def cmd_export() -> None:
    """Export the database to a portable SQL file.

    The output can be opened with any SQLite client, or piped into
    ``sqlite3 fitness.db < fitness-export.sql`` to rebuild the database from
    scratch on another machine.
    """
    if not DB_PATH.exists():
        print(f"ERROR: database not found at {DB_PATH}")
        sys.exit(1)

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    export_path = BACKUP_DIR / f"fitness-{timestamp}.sql"

    conn = get_connection()
    try:
        with open(export_path, "w", encoding="utf-8") as fh:
            for line in conn.iterdump():
                fh.write(f"{line}\n")
    finally:
        conn.close()

    print(f"Exported: {export_path}")


def main() -> None:
    """Parse arguments and dispatch to the requested command."""
    parser = argparse.ArgumentParser(
        description="Fitness tracker database tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="Show database summary")
    sub.add_parser("backup", help="Create a backup")

    restore = sub.add_parser("restore", help="Restore a backup")
    restore.add_argument("name", help="Backup name or unique substring")

    sub.add_parser("export", help="Export to a portable SQL file")

    args = parser.parse_args()

    {
        "info": cmd_info,
        "backup": cmd_backup,
        "restore": lambda: cmd_restore(args.name),
        "export": cmd_export,
    }[args.command]()


if __name__ == "__main__":
    main()
