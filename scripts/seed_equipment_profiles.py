"""Seed EquipmentProfile rows for known Technogym machines.

Populates the richer training details (muscles used, supported exercises,
program modes) for the machines already in the ``equipment`` table, linking
each profile to its equipment row. Run once after the table exists, and again
whenever new machines are added - existing profiles are skipped, so re-running
is safe.

Usage:
    py scripts/seed_equipment_profiles.py              # create missing profiles
    py scripts/seed_equipment_profiles.py --dry-run    # show what would be created

Matching is by exact equipment name. A machine with no matching ``equipment``
row is reported and skipped, never created blind - the profile is meant to
describe a machine you actually use.

Sources for the data below: Technogym's Selection and Excite Live product
pages and support articles (routines/sessions/program modes), plus standard
exercise physiology for the strength machines. Console offerings vary by gym
configuration, so treat program modes as the platform's standard set and
correct them for your gym if anything is missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running as `py scripts/seed_equipment_profiles.py` from anywhere.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fitness_app import create_app, db  # noqa: E402
from fitness_app.models import Equipment, EquipmentProfile  # noqa: E402

#: machine_type, muscles, exercises, program modes, details per equipment name.
SEED_DATA: dict[str, dict] = {
    # --- Selection line strength machines ---
    "Abdominal Crunch Sel": {
        "machine_type": "weight",
        "name": "Technogym Selection Abdominal Crunch",
        "muscles_used": ["Rectus abdominis", "Obliques", "Core stabilisers"],
        "supported_exercises": ["Abdominal crunch"],
        "program_modes": [],
        "details": (
            "Selectorized crunch machine. Pad across the shoulders, "
            "spinal flexion against the weight stack. Primary mover is the "
            "rectus abdominis with oblique involvement for trunk control."
        ),
        "source": "technogym_website",
    },
    "Low Row Sel": {
        "machine_type": "weight",
        "name": "Technogym Selection Low Row",
        "muscles_used": [
            "Latissimus dorsi",
            "Rhomboids",
            "Biceps brachii",
            "Posterior deltoids",
        ],
        "supported_exercises": ["Seated row"],
        "program_modes": [],
        "details": (
            "Selectorized seated row. Pull handles to the torso squeezing the "
            "shoulder blades, shoulders kept low. Targets the upper-back "
            "muscles with biceps assistance."
        ),
        "source": "technogym_website",
    },
    "Shoulder Press Sel": {
        "machine_type": "weight",
        "name": "Technogym Selection Shoulder Press",
        "muscles_used": [
            "Anterior deltoids",
            "Lateral deltoids",
            "Triceps brachii",
            "Upper pectorals",
        ],
        "supported_exercises": ["Shoulder press"],
        "program_modes": [],
        "details": (
            "Selectorized overhead press. Press the handles overhead from "
            "shoulder height. Prime movers are the front and side deltoids "
            "with triceps assistance."
        ),
        "source": "technogym_website",
    },
    # --- Excite Live cardio machines (Technogym Live console) ---
    # The Live console offers the same training modes across the range:
    # Quick Start, goal-based sessions, preset profiles, constant heart
    # rate, fitness test, trainer-led Sessions, auto-adjusting Routines,
    # and Outdoor routes.
    "Run Excite Live": {
        "machine_type": "cardio",
        "name": "Technogym Excite Live Run (treadmill)",
        "muscles_used": ["Quadriceps", "Hamstrings", "Glutes", "Calves"],
        "supported_exercises": ["Running", "Walking", "Sled/HIIT intervals"],
        "program_modes": [
            "Quick Start",
            "Goals (Time, Distance, Calories)",
            "Profiles",
            "Constant Heart Rate",
            "Fitness Test",
            "Routines",
            "Sessions",
            "Outdoor",
        ],
        "details": (
            "Treadmill on the Technogym Live console. Speed and incline "
            "routines auto-adjust; Sessions are trainer-led video workouts."
        ),
        "source": "technogym_website",
    },
    "Synchro Excite Live": {
        "machine_type": "cardio",
        "name": "Technogym Excite Live Synchro (elliptical)",
        "muscles_used": ["Quadriceps", "Glutes", "Hamstrings", "Upper back", "Arms"],
        "supported_exercises": ["Elliptical striding"],
        "program_modes": [
            "Quick Start",
            "Goals (Time, Distance, Calories)",
            "Profiles",
            "Constant Heart Rate",
            "Fitness Test",
            "Routines",
            "Sessions",
            "Outdoor",
        ],
        "details": (
            "Elliptical cross trainer with moving arms. Low-impact "
            "full-body cardio on the Technogym Live console."
        ),
        "source": "technogym_website",
    },
    "Bike Excite Live": {
        "machine_type": "cardio",
        "name": "Technogym Excite Live Bike (upright cycle)",
        "muscles_used": ["Quadriceps", "Glutes", "Hamstrings", "Calves"],
        "supported_exercises": ["Cycling"],
        "program_modes": [
            "Quick Start",
            "Goals (Time, Distance, Calories)",
            "Profiles",
            "Constant Heart Rate",
            "Fitness Test",
            "Routines",
            "Sessions",
            "Outdoor",
        ],
        "details": (
            "Upright exercise bike with walk-through design on the "
            "Technogym Live console."
        ),
        "source": "technogym_website",
    },
    "Climb Excite Live": {
        "machine_type": "cardio",
        "name": "Technogym Excite Live Climb (stairmill)",
        "muscles_used": ["Quadriceps", "Glutes", "Calves"],
        "supported_exercises": ["Stair climbing", "HIIT climbing intervals"],
        "program_modes": [
            "Quick Start",
            "Goals (Time, Distance, Calories)",
            "Profiles",
            "Constant Heart Rate",
            "Fitness Test",
            "Routines (incl. HIIT)",
            "Sessions",
            "Outdoor",
        ],
        "details": (
            "Stair climber on the Technogym Live console. Climb's Routines "
            "include HIIT formats with automatic step-rate adjustment."
        ),
        "source": "technogym_website",
    },
    "Treadmill": {
        "machine_type": "cardio",
        "name": "Technogym treadmill (generic)",
        "muscles_used": ["Quadriceps", "Hamstrings", "Glutes", "Calves"],
        "supported_exercises": ["Running", "Walking"],
        "program_modes": [
            "Quick Start",
            "Goals (Time, Distance, Calories)",
            "Profiles",
            "Constant Heart Rate",
            "Fitness Test",
        ],
        "details": (
            "Generic Technogym treadmill entry. Link this profile to a "
            "specific Excite Live Run machine when known."
        ),
        "source": "manual_entry",
    },
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list. Defaults to ``sys.argv[1:]``.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(
        prog="seed_equipment_profiles.py",
        description="Seed EquipmentProfile rows for known Technogym machines.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without writing anything.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Argument list. Defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code: 0 on success.
    """
    args = parse_args(argv)
    app = create_app()

    created = 0
    skipped = 0
    missing = 0

    with app.app_context():
        for equipment_name, data in SEED_DATA.items():
            equipment = Equipment.query.filter_by(name=equipment_name).first()

            if equipment is None:
                print(f"  [?] no equipment row named {equipment_name!r} - skipped")
                missing += 1
                continue

            existing = EquipmentProfile.query.filter_by(
                equipment_id=equipment.id
            ).first()
            if existing is not None:
                print(f"  [=] {equipment_name} already has a profile - skipped")
                skipped += 1
                continue

            if args.dry_run:
                print(f"  [+] would create profile for {equipment_name}")
                created += 1
                continue

            db.session.add(EquipmentProfile(
                equipment_id=equipment.id,
                machine_type=data["machine_type"],
                name=data["name"],
                muscles_used=json.dumps(data["muscles_used"]),
                supported_exercises=json.dumps(data["supported_exercises"]),
                program_modes=json.dumps(data["program_modes"]),
                details=data["details"],
                source=data["source"],
            ))
            created += 1

        if not args.dry_run:
            db.session.commit()

    print()
    if args.dry_run:
        print(f"Would create {created}, skip {skipped}, "
              f"{missing} with no equipment row.")
    else:
        print(f"Created {created}, skipped {skipped}, "
              f"{missing} with no equipment row.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
