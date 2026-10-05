"""Importer for Health Data Export CSV files (Health Connect via phone app).

The Health Data Export app (Play Store, ``com.teqxnology.healthdataexport``)
reads Health Connect on-device and writes CSV files — one per category. This
importer reads those files and stores their contents, reusing the exact same
processing as the push endpoint (``services/health_connect.py``) so a record
imported from CSV and the same record pushed by a future phone app are handled
identically.

File layout (as exported by the app, headers verbatim):

- ``Activity.csv`` — one row per day per exercise session. Daily aggregates
  (steps, distance, calories) repeat on every row for that day, so the daily
  aggregate is imported once per date and each session separately.
- ``Sleep.csv`` — one row per sleep session (nights are often fragmented into
  several rows). Stored as-is in ``sleep_records``; merging fragmented nights
  is a presentation concern, not a storage one.
- ``Vitals.csv`` — one row per day (heart-rate min/max/avg on this device;
  the Fit3 records nothing else). Attached to the day's aggregate activity.

Missing files are not an error — the user exports only what their device
records. A missing folder or no CSV files at all *is* reported, so a broken
sync path is visible rather than silent.

Stable ``source_id`` values are synthesised from the row contents (there are
no UIDs in the files), so re-importing the same export — or an overlapping
date range — skips everything already stored.
"""

from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from .base import BaseImporter, ImportResult
from ..models import db, ImportLog, Person, SleepRecord
from ..services import health_connect as hc


class HealthConnectCsvImporter(BaseImporter):
    """Import Health Data Export CSV files."""

    #: Folder holding the exported CSV files.
    DEFAULT_DIR_NAME = "health_data_export"

    @property
    def source_name(self) -> str:
        return hc.CSV_SOURCE

    def __init__(self, data_dir: str | None = None):
        """Locate the folder holding the CSV files.

        Args:
            data_dir: Explicit folder. Defaults to
                ``<project>/data/health_data_export``.
        """
        if data_dir is None:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            data_dir = os.path.join(base_dir, "data", self.DEFAULT_DIR_NAME)
        self.data_dir = Path(data_dir)

    def is_available(self) -> bool:
        """Return True when the folder exists and holds at least one CSV."""
        return bool(self.find_csv_files())

    def find_csv_files(self) -> list[str]:
        """Return the CSV files present in the source folder.

        Returns:
            Sorted file names. Empty when the folder is missing or holds none.
        """
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

    # -- parsing helpers -------------------------------------------------

    @staticmethod
    def _number(raw: str | None) -> float | None:
        """Parse a CSV number, returning None for blanks and junk.

        Args:
            raw: Raw cell text.

        Returns:
            The float value, or None.
        """
        if raw is None:
            return None
        text = raw.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def _integer(raw: str | None) -> int | None:
        """Parse a CSV integer, returning None for blanks and junk.

        Args:
            raw: Raw cell text.

        Returns:
            The int value, or None.
        """
        value = HealthConnectCsvImporter._number(raw)
        return None if value is None else int(value)

    @staticmethod
    def _moment(raw: str | None) -> datetime | None:
        """Parse a ``YYYY-MM-DD HH:MM:SS`` timestamp, naive local.

        Args:
            raw: Raw cell text.

        Returns:
            Naive datetime, or None when blank or unparseable. Unparseable
            timestamps are skipped, not fatal — one bad row must not abort
            a month of data.
        """
        if not raw or not raw.strip():
            return None
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw.strip(), pattern)
            except ValueError:
                continue
        return None

    @staticmethod
    def _strip_code(label: str | None) -> str:
        """Remove the numeric Health Connect type code from an exercise name.

        The app writes names like ``"79 - Walking"``. The leading code is a
        Health Connect exercise-type id, meaningless to anyone reading the
        app — but kept in the source_id so the label stays human-readable
        while the id stays unique.

        Args:
            label: Raw exercise name.

        Returns:
            The label without a leading ``"<digits> - "`` prefix.
        """
        return re.sub(r"^\d+\s*-\s*", "", (label or "").strip())

    def _read_csv(self, filename: str) -> tuple[list[str], list[dict]]:
        """Read one CSV file with a tolerant encoding.

        Args:
            filename: File name within the source folder.

        Returns:
            ``(field names, rows)``. Both empty when the file is missing.
        """
        path = self.data_dir / filename
        if not path.is_file():
            return [], []

        # utf-8-sig swallows a BOM when the app writes one. errors="replace"
        # keeps a single bad byte from aborting the whole file.
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
            reader = csv.DictReader(fh)
            return reader.fieldnames or [], list(reader)

    # -- import ----------------------------------------------------------

    def import_data(self, **kwargs) -> ImportResult:
        """Import all Health Data Export CSV files in the folder."""
        result = ImportResult(source=self.source_name)

        person = Person.query.first()
        if person is None:
            result.errors.append("no profile exists to attach records to")
            return result

        activity_rows = self._import_activity(person, result)
        self._import_sleep(person, result)

        # Vitals attach to the day's aggregate activity, so they need the
        # activity rows created above.
        self._import_vitals(activity_rows, result)

        db.session.commit()
        return result

    def _import_activity(self, person: Person, result: ImportResult) -> dict[str, int]:
        """Import Activity.csv: one daily aggregate plus each session.

        Args:
            person: Whose activities these are.
            result: ImportResult to update.

        Returns:
            Mapping of date string to the aggregate activity's id, for the
            vitals pass.
        """
        _, rows = self._read_csv("Activity.csv")
        if not rows:
            result.notes.append("no Activity.csv found - skipping activity import")
            return {}

        aggregate_ids: dict[str, int] = {}
        records: list[dict] = []
        seen_days: set[str] = set()

        for row in rows:
            day = (row.get("Date") or "").strip()
            if not day:
                continue

            result.records_found += 1

            # The daily aggregate repeats on every row for the day: queue it
            # once, the first time the day is seen.
            if day not in seen_days:
                seen_days.add(day)
                steps = self._integer(row.get("Steps"))
                distance = self._number(row.get("Distance (m)"))
                calories = self._number(row.get("Total Calories (kcal)"))
                if steps is not None or distance is not None or calories is not None:
                    records.append({
                        "type": "steps",
                        "source_id": f"hcday:{day}",
                        "start": f"{day}T00:00:00",
                        "end": f"{day}T23:59:00",
                        "steps": steps,
                        "distance_m": distance,
                        "calories": calories,
                    })

            # Each row with a session becomes its own record.
            name = (row.get("Exercise Name") or "").strip()
            start = self._moment(row.get("Start Date/Time"))
            if name and start:
                minutes = self._number(row.get("Duration (min)"))
                records.append({
                    "type": "exercise",
                    "source_id": (
                        f"hcsess:{row.get('Start Date/Time', '').strip()}"
                        f":{name}:{row.get('Duration (min)', '').strip()}"
                    ),
                    "start": start.isoformat(),
                    "end": (start + timedelta(minutes=minutes)).isoformat()
                    if minutes else None,
                    "exercise_type": self._strip_code(name),
                    "duration_seconds": int(minutes * 60) if minutes else None,
                    "calories": self._number(row.get("Exercise Calories (kcal)")),
                    "distance_m": self._number(row.get("Exercise Distance (m)")),
                })

        outcome = hc.process_records(records, person_id=person.id, source=self.source_name)
        self._fold_outcome(result, outcome)

        # Recover the aggregate ids for the vitals pass.
        from ..models import Activity
        for day in seen_days:
            activity = Activity.query.filter_by(
                source=self.source_name, source_id=f"hcday:{day}"
            ).first()
            if activity is not None:
                aggregate_ids[day] = activity.id

        return aggregate_ids

    def _import_sleep(self, person: Person, result: ImportResult) -> None:
        """Import Sleep.csv into sleep_records.

        Args:
            person: Whose sleep this is.
            result: ImportResult to update.
        """
        _, rows = self._read_csv("Sleep.csv")
        if not rows:
            result.notes.append("no Sleep.csv found - skipping sleep import")
            return

        for row in rows:
            start = self._moment(row.get("Start Time"))
            end = self._moment(row.get("End Time"))
            if start is None:
                continue

            result.records_found += 1
            source_id = (
                f"hcsleep:{(row.get('Start Time') or '').strip()}"
                f":{(row.get('End Time') or '').strip()}"
            )

            if self.check_already_imported(source_id, "sleep"):
                result.records_skipped += 1
                continue

            record = SleepRecord(
                person_id=person.id,
                started_at=start,
                ended_at=end,
                light_min=self._integer(row.get("Light Sleep (min)")),
                deep_min=self._integer(row.get("Deep Sleep (min)")),
                rem_min=self._integer(row.get("REM Sleep (min)")),
                awake_min=self._integer(row.get("Awake (min)")),
                source=self.source_name,
                source_id=source_id,
            )
            db.session.add(record)
            db.session.flush()

            db.session.add(ImportLog(
                source=self.source_name,
                source_id=source_id,
                record_type="sleep",
                record_id=record.id,
                action="created",
            ))
            result.records_created += 1

        db.session.commit()

    def _import_vitals(
        self, aggregate_ids: dict[str, int], result: ImportResult
    ) -> None:
        """Attach Vitals.csv heart-rate data to each day's aggregate activity.

        Daily heart-rate summaries belong with the day, not as standalone
        rows: a bare "avg HR 93" record with no session context would be
        noise in every listing. The day's aggregate activity carries them in
        ``enrichment_data`` where the charts and a future LLM can find them.

        Args:
            aggregate_ids: Date string to aggregate activity id.
            result: ImportResult to update.
        """
        from ..models import Activity

        _, rows = self._read_csv("Vitals.csv")
        if not rows:
            result.notes.append("no Vitals.csv found - skipping vitals import")
            return

        for row in rows:
            day = (row.get("Date") or "").strip()
            if not day or day not in aggregate_ids:
                continue

            vitals = {
                "hr_min": self._number(row.get("Heart rate min (bpm)")),
                "hr_max": self._number(row.get("Heart rate max (bpm)")),
                "hr_avg": self._number(row.get("Heart rate avg (bpm)")),
                "hrv_min": self._number(row.get("Heart rate variability min (ms)")),
                "hrv_max": self._number(row.get("Heart rate variability max (ms)")),
                "hrv_avg": self._number(row.get("Heart rate variability avg (ms)")),
                "resting_hr": self._number(row.get("Resting heart rate avg (bpm)"))
                or self._number(row.get("Resting heart rate min (bpm)")),
            }
            vitals = {key: value for key, value in vitals.items() if value is not None}
            if not vitals:
                continue

            activity = db.session.get(Activity, aggregate_ids[day])
            if activity is None:
                continue

            existing = (
                json.loads(activity.enrichment_data)
                if activity.enrichment_data else {}
            )
            # Only touch the row when something actually differs. Without this
            # guard every scheduled run would "update" every day and report
            # work it did not do.
            if existing.get("vitals") == vitals:
                continue
            existing["vitals"] = vitals
            activity.enrichment_data = json.dumps(existing)
            result.records_updated += 1

        db.session.commit()

    @staticmethod
    def _fold_outcome(result: ImportResult, outcome: dict) -> None:
        """Fold a process_records outcome into an ImportResult.

        Args:
            result: ImportResult to update.
            outcome: Dict from :func:`health_connect.process_records`.
        """
        # process_records commits its own work; counts here are for reporting.
        # Created vs skipped is derived from the outcome totals.
        result.records_created += outcome["imported"]
        result.records_skipped += outcome["skipped"]
        result.conflicts.extend(outcome["conflicts"])
        result.errors.extend(outcome["errors"])
        if outcome["enriched"]:
            result.notes.append(
                f"{outcome['enriched']} activit"
                f"{'ies' if outcome['enriched'] != 1 else 'y'} matched "
                f"an existing gym workout and enriched it."
            )
