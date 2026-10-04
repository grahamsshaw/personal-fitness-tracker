"""Technogym manual export importer.

Parses the JSON files from the mywellness.com account data export:
- biometrics-*.json — Weight, height, BMI measurements
- indooractivities-*.json — Indoor workout sessions
- outdooractivities-*.json — Outdoor activities (rowing)
- masterdata-*.json — User profile

This importer does not require authentication — it works with the files
downloaded from https://widgets.mywellness.com/accountdataexport
"""

import json
import os
import glob
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .base import BaseImporter, ImportResult
from ..models import db, Activity, BodyMeasurement, Exercise, Equipment, ImportLog, Person
from ..services.measurements import (
    Reading,
    describe_reading,
    supersede_mismatches_within_day,
)


@dataclass
class BiometricRecord:
    """A single biometric measurement."""
    name: str
    measured_on: datetime
    value: float


@dataclass
class IndoorActivity:
    """An indoor workout session."""
    ph_id: str
    started_at: datetime
    facility: str
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass
class OutdoorActivity:
    """An outdoor activity."""
    id: str
    activity_name: str
    performed_date: datetime
    metrics: dict[str, float] = field(default_factory=dict)


class TechnogymManualImporter(BaseImporter):
    """Importer for Technogym manual export JSON files."""

    @property
    def source_name(self) -> str:
        return "technogym"

    def __init__(self, data_dir: str | None = None):
        """Initialize the importer.

        Args:
            data_dir: Path to the directory containing the exported JSON files.
                     Defaults to data/technogym_export.
        """
        if data_dir is None:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            data_dir = os.path.join(base_dir, "data", "technogym_export")
        self.data_dir = Path(data_dir)

    def _load_json_files(self, pattern: str) -> list[dict]:
        """Load all JSON files matching a pattern."""
        records = []
        for filepath in sorted(self.data_dir.glob(pattern)):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        records.extend(data)
                    else:
                        records.append(data)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load {filepath}: {e}")
        return records

    def check_already_imported(self, source_id: str, record_type: str) -> bool:
        """Check if a record has already been imported."""
        return ImportLog.query.filter_by(
            source=self.source_name,
            source_id=source_id,
            record_type=record_type,
        ).first() is not None

    def import_data(self, **kwargs) -> ImportResult:
        """Import all Technogym manual export data.

        Returns:
            ImportResult with counts of created/skipped records.
        """
        result = ImportResult(source=self.source_name)

        # Get or create person
        person = Person.query.first()
        if not person:
            person = Person(first_name="Graham", last_name="Shaw")
            db.session.add(person)
            db.session.flush()

        # Import biometrics
        self._import_biometrics(person, result)

        # Import indoor activities
        self._import_indoor_activities(person, result)

        # Import outdoor activities
        self._import_outdoor_activities(person, result)

        # Import masterdata (profile)
        self._import_masterdata(person, result)

        db.session.commit()
        return result

    def _import_biometrics(self, person: Person, result: ImportResult):
        """Import biometric measurements (weight, height, BMI)."""
        records = self._load_json_files("biometrics-*.json")

        for record in records:
            name = record.get("name", "").lower()
            measured_on_str = record.get("measuredOn", "")
            value_str = record.get("value", "")

            if not name or not measured_on_str or not value_str:
                continue

            try:
                measured_on = datetime.fromisoformat(measured_on_str.replace("Z", "+00:00"))
                value = float(value_str)
            except (ValueError, TypeError):
                continue

            # Map measurement type
            measurement_type = name  # 'weight', 'height', 'bmi'
            unit = "kg" if name == "weight" else "cm" if name == "height" else ""

            # Create unique source ID
            source_id = f"biometric_{name}_{measured_on.isoformat()}"

            if self.check_already_imported(source_id, "body_measurement"):
                result.records_skipped += 1
                continue

            measurement = BodyMeasurement(
                person_id=person.id,
                measured_at=measured_on,
                measurement_type=measurement_type,
                value=value,
                unit=unit,
                source=self.source_name,
                source_id=source_id,
            )
            db.session.add(measurement)
            db.session.flush()

            log = ImportLog(
                source=self.source_name,
                source_id=source_id,
                record_type="body_measurement",
                record_id=measurement.id,
                action="created",
            )
            db.session.add(log)
            result.records_created += 1

            # Check whether this reading contradicts another source for the same
            # day. Reports only - nothing is overwritten or hidden. Technogym
            # biometrics are hand-entered and go stale, so a disagreement with a
            # scale reading is exactly the case worth surfacing.
            for other_id in supersede_mismatches_within_day(measurement):
                result.conflicts.append(
                    describe_conflict(
                        measurement,
                        db.session.get(BodyMeasurement, other_id),
                        new_label="Technogym",
                    )
                )

    def _import_indoor_activities(self, person: Person, result: ImportResult):
        """Import indoor workout activities."""
        records = self._load_json_files("indooractivities-*.json")

        for record in records:
            ph_id = record.get("phId", "")
            on_str = record.get("on", "")
            facility = record.get("facility", "")

            if not ph_id or not on_str:
                continue

            try:
                started_at = datetime.fromisoformat(on_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue

            # Extract metrics
            metrics = {}
            performed_data = record.get("performedData", {})
            for prop in performed_data.get("pr", []):
                name = prop.get("n", "")
                value = prop.get("v")
                if name and value is not None:
                    try:
                        metrics[name] = float(value)
                    except (ValueError, TypeError):
                        pass

            # Check if already imported
            if self.check_already_imported(ph_id, "activity"):
                result.records_skipped += 1
                continue

            # Create activity
            duration = metrics.get("Duration")
            distance = metrics.get("HDistance")
            calories = metrics.get("Calories")
            avg_hr = metrics.get("AvgHr")
            max_hr = metrics.get("MaxHr")

            activity = Activity(
                person_id=person.id,
                activity_type="gym",
                started_at=started_at,
                duration_seconds=int(duration) if duration else None,
                distance_m=distance,
                calories=calories,
                avg_heart_rate=int(avg_hr) if avg_hr else None,
                max_heart_rate=int(max_hr) if max_hr else None,
                source=self.source_name,
                source_id=ph_id,
            )
            db.session.add(activity)
            db.session.flush()

            log = ImportLog(
                source=self.source_name,
                source_id=ph_id,
                record_type="activity",
                record_id=activity.id,
                action="created",
            )
            db.session.add(log)
            result.records_created += 1

    def _import_outdoor_activities(self, person: Person, result: ImportResult):
        """Import outdoor activities (rowing, etc.)."""
        records = self._load_json_files("outdooractivities-*.json")

        for record in records:
            activity_id = record.get("id", "")
            activity_name = record.get("activityName", "")
            performed_date_str = record.get("performedDate", "")

            if not activity_id or not performed_date_str:
                continue

            try:
                performed_date = datetime.fromisoformat(performed_date_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue

            # Extract metrics
            metrics = {}
            activity_data = record.get("physicalActivityData", {})
            for prop in activity_data.get("pr", []):
                name = prop.get("n", "")
                value = prop.get("v")
                if name and value is not None:
                    try:
                        metrics[name] = float(value)
                    except (ValueError, TypeError):
                        pass

            # Check if already imported
            if self.check_already_imported(activity_id, "activity"):
                result.records_skipped += 1
                continue

            # Create activity
            duration = metrics.get("Duration")
            distance = metrics.get("RowingDistance")
            calories = metrics.get("Calories")

            activity = Activity(
                person_id=person.id,
                activity_type="rowing" if "rowing" in activity_name.lower() else "outdoor",
                started_at=performed_date,
                duration_seconds=int(duration) if duration else None,
                distance_m=distance,
                calories=calories,
                source=self.source_name,
                source_id=activity_id,
            )
            db.session.add(activity)
            db.session.flush()

            log = ImportLog(
                source=self.source_name,
                source_id=activity_id,
                record_type="activity",
                record_id=activity.id,
                action="created",
            )
            db.session.add(log)
            result.records_created += 1

    def _import_masterdata(self, person: Person, result: ImportResult):
        """Import masterdata (user profile).

        This does not create a new row - it updates the existing ``Person``. So it
        is counted as an update when something actually differs, and as a skip when
        the profile is already current, which is the normal case on every run
        after the first. Counting it as "created" unconditionally made every
        import report a brand new record that never existed.
        """
        records = self._load_json_files("masterdata-*.json")

        for record in records:
            # Apply each field only when the incoming value is present and
            # actually different, so a real change is distinguishable from a no-op.
            changed = False

            for field_name, attribute in (
                ("firstName", "first_name"),
                ("lastName", "last_name"),
                ("gender", "gender"),
            ):
                new_value = record.get(field_name)
                if new_value and getattr(person, attribute) != new_value:
                    setattr(person, attribute, new_value)
                    changed = True

            if record.get("birthDate"):
                try:
                    new_birth_date = int(record["birthDate"])
                except (ValueError, TypeError):
                    # An unparseable date must not abort the whole import; the
                    # fields above have already been applied.
                    new_birth_date = None
                if new_birth_date and person.birth_date != new_birth_date:
                    person.birth_date = new_birth_date
                    changed = True

            if changed:
                result.records_updated += 1
            else:
                result.records_skipped += 1
