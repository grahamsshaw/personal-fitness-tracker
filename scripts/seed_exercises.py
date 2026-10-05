"""Seed the exercise library from MIT-licensed ExerciseDB metadata.

Reads the English exercise records (name, body part, equipment, target and
secondary muscles, instructions) from the dataset file and merges them into
the ``exercises`` table: existing rows matched by case-insensitive name are
enriched in place, the rest are created. Nothing is ever deleted.

Usage:
    py scripts/seed_exercises.py              # enrich missing rows
    py scripts/seed_exercises.py --dry-run    # show what would change
    py scripts/seed_exercises.py --refresh    # re-apply metadata to all rows

The dataset lives in Resources_Archive (gitignored, never deployed), so this
script runs on the dev PC and the data travels to the Pi inside the database
via push-database.bat. When the file is absent the script explains and exits.

Provenance and licence: see THIRD-PARTY-NOTICES.md. Only the English metadata
is used. Images and animations are deliberately excluded — their ownership is
unresolved.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running as `py scripts/seed_exercises.py` from anywhere.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fitness_app import create_app, db  # noqa: E402
from fitness_app.models import Exercise  # noqa: E402

#: Dataset file (never deployed; PC only).
DATASET = (
    PROJECT_ROOT / "Resources_Archive" / "openGym-main" / "frontend" / "src"
    / "lib" / "exercises-data.js"
)

#: Value stamped on every touched row.
SOURCE_TAG = "exercisedb-mit"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list. Defaults to ``sys.argv[1:]``.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(
        prog="seed_exercises.py",
        description="Seed the exercise library from ExerciseDB metadata.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing anything.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-apply metadata to rows already seeded, not just new ones.",
    )
    return parser.parse_args(argv)


def load_dataset() -> list[dict]:
    """Parse the dataset file.

    Returns:
        List of exercise dicts.

    Raises:
        SystemExit: If the file is missing.
    """
    if not DATASET.is_file():
        print(f"Dataset not found: {DATASET}")
        print("This script runs on the dev PC, where Resources_Archive lives.")
        sys.exit(1)

    raw = DATASET.read_text(encoding="utf-8")
    prefix = "export const EXDB="
    assert raw.startswith(prefix), "unexpected dataset format"
    return json.loads(raw[len(prefix):].rstrip().rstrip(";"))


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Argument list. Defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code: 0 on success.
    """
    args = parse_args(argv)
    records = load_dataset()
    print(f"Dataset: {len(records)} exercises")

    app = create_app()
    created = 0
    enriched = 0
    skipped = 0

    with app.app_context():
        # Index existing rows by normalised name for exact matching.
        existing = {row.name.casefold().strip(): row for row in Exercise.query.all()}

        for record in records:
            name = (record.get("n") or "").strip()
            if not name:
                continue

            row = existing.get(name.casefold())
            already_seeded = row is not None and row.source == SOURCE_TAG

            if already_seeded and not args.refresh:
                skipped += 1
                continue

            metadata = {
                "external_id": record.get("id"),
                "body_part": record.get("bp"),
                "equipment_label": record.get("eq"),
                "target_muscle": record.get("tg"),
                "secondary_muscles": json.dumps(record.get("sm") or []),
                "instructions": json.dumps(record.get("st") or []),
                "source": SOURCE_TAG,
            }

            if args.dry_run:
                if row is None:
                    created += 1
                else:
                    enriched += 1
                continue

            if row is None:
                row = Exercise(name=name, category="strength")
                db.session.add(row)
                existing[name.casefold()] = row
                created += 1
            else:
                enriched += 1

            for key, value in metadata.items():
                setattr(row, key, value)

        if not args.dry_run:
            db.session.commit()

    print(f"Created {created}, enriched {enriched}, skipped {skipped} "
          f"(already seeded).")
    if args.dry_run:
        print("Dry run - nothing written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
