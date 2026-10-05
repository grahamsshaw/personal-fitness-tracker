"""Importer for workout CSV exports (Strong, Hevy, FitNotes style).

Reads one-row-per-set CSV files as exported by popular gym loggers and
stores them as workouts with exercises and sets. Written from scratch
against the apps' documented export formats — no third-party code.

Dialects are detected from the headers, which are normalised
(case-insensitive, punctuation stripped) before matching so minor export
variations do not break the import:

- Hevy: ``Exercise Title``, ``Set Index``, ``Weight (kg)``, ``Reps``,
  ``Start/End time``, ``Title``, ``RPE``, ``Distance (km)``,
  ``Duration (seconds)``.
- Strong: ``Exercise Name``, ``Set Order``, ``Weight``, ``Reps``,
  ``Date``, ``Workout Name``, ``RPE``, ``Distance``, ``Seconds``.
- Generic: ``exercise`` + ``date`` + something measured (weight/reps,
  time, distance).

Exercise names match the library case-insensitively; anything unrecognised
becomes a custom exercise (source ``gym_csv``) so nothing in the file is
dropped. Days that already hold the same workout are skipped: each workout's
``source_id`` is a content hash, so re-importing the same file imports
nothing new.

Because no real export file has been available for testing, this importer is
verified against synthetic files in both dialects. Verify against a real
export before trusting it blindly — see ``documentation/IMPORTING.md``.
"""

from __future__ import annotations

import csv
import hashlib
import os
import re
from datetime import datetime
from pathlib import Path

from .base import BaseImporter, ImportResult
from ..models import (
    db, Exercise, ImportLog, Person, Set, Workout, WorkoutExercise,
)


def _normalize_header(raw: str | None) -> str:
    """Normalise a CSV header for matching.

    Lowercased with all punctuation stripped, so ``"Weight (kg)"``,
    ``"weight kg"`` and ``"WEIGHT_KG"`` all become ``"weightkg"``.

    Args:
        raw: Raw header text.

    Returns:
        Normalised header.
    """
    return re.sub(r"[^a-z0-9]", "", (raw or "").lower())


def _first(row: dict, *candidates: str) -> str | None:
    """Return the first non-blank cell among candidate headers.

    Args:
        row: CSV row keyed by raw header.
        candidates: Normalised header names to try in order.

    Returns:
        Cell text, or None.
    """
    lookup = {_normalize_header(key): value for key, value in row.items()}
    for candidate in candidates:
        value = lookup.get(candidate)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _number(raw: str | None) -> float | None:
    """Parse a number, None for blanks and junk."""
    if raw is None or not str(raw).strip():
        return None
    try:
        return float(str(raw).strip().replace(",", ""))
    except ValueError:
        return None


def _parse_moment(raw: str | None) -> datetime | None:
    """Parse the several timestamp shapes these exports use."""
    if not raw or not str(raw).strip():
        return None
    text = str(raw).strip()
    for pattern in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%m/%d/%Y %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
    ):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


class GymCsvImporter(BaseImporter):
    """Import workout CSV files from gym logger apps."""

    #: Folder holding the CSV files.
    DEFAULT_DIR_NAME = "workout_csv"

    @property
    def source_name(self) -> str:
        return "gym_csv"

    def __init__(self, data_dir: str | None = None):
        """Locate the folder holding the CSV files.

        Args:
            data_dir: Explicit folder. Defaults to
                ``<project>/data/workout_csv``.
        """
        if data_dir is None:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            data_dir = os.path.join(base_dir, "data", self.DEFAULT_DIR_NAME)
        self.data_dir = Path(data_dir)

    def is_available(self) -> bool:
        """Return True when the folder holds at least one CSV."""
        return bool(self.find_csv_files())

    def find_csv_files(self) -> list[str]:
        """Return the CSV files present in the source folder."""
        if not self.data_dir.is_dir():
            return []
        try:
            return sorted(
                entry.name
                for entry in self.data_dir.iterdir()
                if entry.is_file() and entry.suffix.lower() == ".csv"
            )
        except OSError:
            return []

    def check_already_imported(self, source_id: str, record_type: str) -> bool:
        """Check if a record has already been imported."""
        return ImportLog.query.filter_by(
            source=self.source_name,
            source_id=source_id,
            record_type=record_type,
        ).first() is not None

    def import_data(self, **kwargs) -> ImportResult:
        """Import every workout CSV in the folder."""
        result = ImportResult(source=self.source_name)

        person = Person.query.first()
        if person is None:
            result.errors.append("no profile exists to attach records to")
            return result

        files = self.find_csv_files()
        if not files:
            result.notes.append("no workout CSV files found")
            return result

        for filename in files:
            try:
                self._import_file(person, filename, result)
            except Exception as error:  # noqa: BLE001 - one file must not stop the rest
                result.errors.append(f"Error importing {filename}: {error}")

        db.session.commit()
        return result

    def _read_rows(self, filename: str) -> list[dict]:
        """Read a CSV file, tolerating BOMs and bad bytes."""
        path = self.data_dir / filename
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames:
                return []
            return [row for row in reader if any(
                (value or "").strip() for value in row.values()
            )]

    def _import_file(
        self, person: Person, filename: str, result: ImportResult
    ) -> None:
        """Import one file: group rows into workouts, then store them."""
        rows = self._read_rows(filename)
        if not rows:
            result.notes.append(f"{filename} holds no data rows")
            return

        groups: dict[str, list[dict]] = {}
        for row in rows:
            key = self._workout_key(row)
            groups.setdefault(key, []).append(row)

        for key, group in groups.items():
            self._import_workout(person, filename, key, group, result)

    @staticmethod
    def _workout_key(row: dict) -> str:
        """Group key: workout title + date, falling back to the row date."""
        title = _first(row, "title", "workoutname", "workout") or "Workout"
        started = _first(
            row, "starttime", "startdate", "date", "workoutdate") or ""
        return f"{title}|{started}"

    def _import_workout(
        self, person: Person, filename: str, key: str,
        rows: list[dict], result: ImportResult,
    ) -> None:
        """Store one workout and its sets."""
        # Content hash: stable across re-exports, unique per workout even
        # when two share a title and date. repr() tolerates ragged rows
        # (csv gives extras as a list under a None key).
        digest = hashlib.sha1()
        for row in rows:
            digest.update(repr(sorted(
                (key or "", value) for key, value in row.items()
            )).encode("utf-8", "replace"))
        source_id = f"gymcsv:{digest.hexdigest()[:16]}"

        result.records_found += len(rows)
        if self.check_already_imported(source_id, "workout"):
            result.records_skipped += len(rows)
            return

        title = _first(rows[0], "title", "workoutname", "workout") or "Workout"
        started_at = None
        ended_at = None
        for row in rows:
            moment = _parse_moment(_first(
                row, "starttime", "startdate", "date", "workoutdate"))
            if moment and (started_at is None or moment < started_at):
                started_at = moment
            moment = _parse_moment(_first(row, "endtime", "enddate"))
            if moment and (ended_at is None or moment > ended_at):
                ended_at = moment
        if started_at is None:
            result.errors.append(
                f"{filename}: workout {title!r} has no usable date - skipped")
            return

        workout = Workout(
            person_id=person.id,
            workout_name=title,
            started_at=started_at,
            ended_at=ended_at,
            source=self.source_name,
            source_id=source_id,
        )
        db.session.add(workout)
        db.session.flush()

        # Group rows by exercise, preserving file order.
        exercises: dict[str, list[dict]] = {}
        for row in rows:
            name = _first(row, "exercisetitle", "exercisename",
                          "exercise") or "Unknown"
            exercises.setdefault(name, []).append(row)

        for order, (name, set_rows) in enumerate(exercises.items()):
            exercise = Exercise.query.filter(
                db.func.lower(Exercise.name) == name.lower()).first()
            if exercise is None:
                exercise = Exercise(name=name, category="strength",
                                    source=self.source_name)
                db.session.add(exercise)
                db.session.flush()

            workout_exercise = WorkoutExercise(
                workout_id=workout.id,
                exercise_id=exercise.id,
                exercise_name=name,
                exercise_order=order,
                source=self.source_name,
                source_id=f"{source_id}:{order}",
            )
            db.session.add(workout_exercise)
            db.session.flush()

            for index, row in enumerate(set_rows, start=1):
                self._import_set(workout_exercise, row, index, result)

        db.session.add(ImportLog(
            source=self.source_name,
            source_id=source_id,
            record_type="workout",
            record_id=workout.id,
            action="created",
        ))
        result.records_created += 1

    def _import_set(
        self, workout_exercise: WorkoutExercise, row: dict, index: int,
        result: ImportResult,
    ) -> None:
        """Store one set row."""
        weight = _number(_first(row, "weightkg", "weight", "weightlbs", "weightlb"))
        if _first(row, "weightunit", "unit"):
            unit = _first(row, "weightunit", "unit").lower()
            if "lb" in unit and weight is not None:
                weight = round(weight * 0.453592, 2)
        reps = _number(_first(row, "reps", "repetitions"))
        rpe = _number(_first(row, "rpe", "rperating"))
        rir = _number(_first(row, "rir", "repsinreserve"))
        duration = _number(_first(
            row, "durationseconds", "setdurationsec", "seconds", "time",
            "duration"))
        # Both dialects export distance in kilometres.
        distance = _number(_first(row, "distancekm", "distance"))
        distance_m = round(distance * 1000, 1) if distance is not None else None
        set_type_raw = (_first(row, "settype") or "normal").lower()
        is_warmup = "warm" in set_type_raw

        db.session.add(Set(
            workout_exercise_id=workout_exercise.id,
            set_number=int(_number(_first(row, "setindex", "setorder")) or index),
            reps_actual=int(reps) if reps is not None else None,
            weight_kg_actual=weight,
            duration_seconds=int(duration) if duration is not None else None,
            distance_m=distance_m,
            effort_rpe=rpe,
            effort_rir=int(rir) if rir is not None else None,
            set_type="dropset" if "drop" in set_type_raw else "straight",
            is_warmup=is_warmup,
            source=self.source_name,
            source_id=f"{workout_exercise.source_id}:{index}",
        ))
        result.records_created += 1
