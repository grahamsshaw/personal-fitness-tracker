"""Process records pushed from Health Connect via the phone app.

Why this module exists
----------------------
Health Connect has no server-side API — the data lives on the Android device
and only an app on that device can read it. So the phone app POSTs records to
the Pi, and this module decides what each record becomes. It is the Health
Connect equivalent of an importer, sharing the same rules:

- **Idempotent** — every record carries the Health Connect UID as ``source_id``,
  checked against ``import_log`` before anything is written. Re-pushes are
  skipped, never duplicated.
- **Workouts enrich, never duplicate** — a gym workout *causes* some of the
  activity Health Connect sees. When a pushed record is *compatible* with an
  overlapping gym workout (strength-like, or locomotion matching the
  workout's machines), the workout is enriched (heart rate, calories, a note
  naming the source) instead of creating a second record of the same
  session. Anything else — a walk to the gym, a station commute, a day-long
  steps summary — stands alone and counts toward the week's activity as
  itself. Overlap alone never merges.
- **Conflicts are reported, not resolved** — a pushed weight that disagrees
  with another source for the same day goes through the same
  ``services/measurements.py`` check as every other source.

Record shape (from the phone app)::

    {
        "type": "weight" | "exercise" | "steps",
        "source_id": "<health-connect-uid>",   # required, stable per record
        "start": "2026-10-05T07:30:00",        # ISO timestamp
        "end": "2026-10-05T08:15:00",          # exercise/steps; optional
        # weight:
        "weight_kg": 99.5,
        # exercise:
        "exercise_type": "strength training",  # free text from Health Connect
        "duration_seconds": 2700,
        "calories": 250.0,
        "avg_heart_rate": 110,
        "max_heart_rate": 145,
        # steps:
        "steps": 8432,
        "distance_m": 6100.0,
    }
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ..models import db, Activity, BodyMeasurement, ImportLog, Person, Workout
from .measurements import derive_bmi, supersede_mismatches_within_day, describe_conflict

#: Source key used in ``import_log`` and on every created row by the push
#: endpoint. The CSV importer passes its own source instead — see
#: :func:`process_records`.
SOURCE = "health_connect"

#: Source key for rows created from Health Data Export CSV files. Kept
#: distinct from the push endpoint's key because the acquisition path matters
#: when debugging: a suspicious row should answer "which file, or which push".
CSV_SOURCE = "health_connect_csv"

#: Record types this module accepts.
RECORD_TYPES = ("weight", "exercise", "steps")

#: Health Connect exercise text (lowercased, substring match) -> our activity type.
#: Anything unrecognised becomes a generic 'gym'-style activity rather than
#: being rejected — the record still happened, even if we cannot classify it.
EXERCISE_TYPE_MAP = {
    "strength": "gym",
    "weight": "gym",
    "run": "running",
    "walk": "walking",
    "cycl": "cycling",
    "bik": "cycling",
    "swim": "swimming",
    "row": "rowing",
    "ellipt": "elliptical",
    "yoga": "yoga",
    "pilat": "pilates",
}

#: Maximum gap (seconds) between a gym workout and a Health Connect activity
#: for the two to count as the same session. Gym start times come from kiosk
#: check-ins and phone clocks drift, so exact alignment is not required.
OVERLAP_TOLERANCE_SECONDS = 30 * 60


def parse_time(raw: str | None) -> datetime | None:
    """Parse an ISO timestamp from the phone app.

    Accepts a trailing ``Z`` (UTC) as well as naive local times. Timezone
    information is normalised away: the rest of the database stores naive
    datetimes, so a pushed timestamp becomes naive UTC when marked, or naive
    local when unmarked. Phone and Pi clocks are both local-time devices on
    the same LAN, so in practice this is the wall-clock time of the event.

    Args:
        raw: ISO timestamp string, or None.

    Returns:
        Naive datetime, or None when ``raw`` is empty.
    """
    if not raw:
        return None

    text = str(raw).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)

    return parsed


def already_imported(source: str, source_id: str, record_type: str) -> bool:
    """Check whether a Health Connect record was already stored.

    Args:
        source: Source key (push endpoint or CSV importer).
        source_id: The stable UID for the record.
        record_type: One of ``weight``, ``activity``.

    Returns:
        True when an ``import_log`` row exists for this key.
    """
    return ImportLog.query.filter_by(
        source=source,
        source_id=source_id,
        record_type=record_type,
    ).first() is not None


def _log(source: str, source_id: str, record_type: str, record_id: int, action: str) -> None:
    """Write one ``import_log`` row.

    Args:
        source: Source key.
        source_id: The stable UID.
        record_type: ``weight`` or ``activity``.
        record_id: Primary key of the created row.
        action: ``created``, ``skipped`` or ``enriched``.
    """
    db.session.add(ImportLog(
        source=source,
        source_id=source_id,
        record_type=record_type,
        record_id=record_id,
        action=action,
    ))


def _source_label(source: str) -> str:
    """Human name for a source key in conflict messages.

    Args:
        source: ``health_connect`` or ``health_connect_csv``.

    Returns:
        e.g. ``"Health Connect (CSV)"``.
    """
    return "Health Connect (CSV)" if source == CSV_SOURCE else "Health Connect"


def classify_exercise(exercise_type: str | None) -> str:
    """Map Health Connect free-text exercise type to our activity type.

    Args:
        exercise_type: e.g. ``"Strength training"``.

    Returns:
        An ``activities.activity_type`` value. Unrecognised input becomes
        ``"gym"`` — a session that happened but defies classification is
        still worth storing.
    """
    lowered = (exercise_type or "").lower()
    for fragment, activity_type in EXERCISE_TYPE_MAP.items():
        if fragment in lowered:
            return activity_type
    return "gym"


#: Health Connect activity type -> machine-name fragments identifying the gym
#: equipment that would produce it. Used to decide whether an overlapping
#: phone record is the *same session* as a gym workout or a *separate*
#: activity that merely happened nearby in time (walking to the gym, for
#: example). Matching is deliberately conservative: a commute must never be
#: folded into a workout.
#:
#: - Strength-like records (``gym``) match any overlapping workout — the
#:   phone saw the session's physiology.
#: - Locomotion records match only when the workout used a machine for that
#:   modality (a treadmill run recorded by both sides is one session; a walk
#:   to the gym during a weights session is two).
#: - ``swimming`` has no gym counterpart and never matches.
#: - Daily step aggregates (``steps``) span the whole day and never match —
#:   a day-long window overlapping a workout is meaningless.
CARDIO_MACHINE_KEYWORDS = {
    "running": ("run", "treadmill"),
    "walking": ("treadmill",),
    "cycling": ("bike", "cycle"),
    "rowing": ("row",),
    "elliptical": ("ellipt", "synchro"),
    "swimming": (),
}


def _workout_machine_names(workout: Workout) -> list[str]:
    """Lowercased machine/equipment names used in a workout.

    Args:
        workout: The workout to inspect.

    Returns:
        Distinct non-empty names, lowercased.
    """
    names = set()
    for exercise in workout.exercises:
        for raw in (exercise.machine, exercise.equipment_name):
            if raw and raw.strip():
                names.add(raw.strip().lower())
    return sorted(names)


def find_overlapping_workout(
    person_id: int,
    started_at: datetime,
    ended_at: datetime | None,
    activity_type: str = "gym",
    is_aggregate: bool = False,
) -> Workout | None:
    """Find the gym workout a pushed activity belongs to, if any.

    Overlap alone is not enough: a walk to the gym overlaps the gym visit
    without being part of it. The activity must also be *compatible* — a
    strength-like record, or a locomotion record whose modality appears
    among the workout's machines.

    Args:
        person_id: Whose workouts to search.
        started_at: Start of the pushed activity.
        ended_at: End of the pushed activity, if known.
        activity_type: Classified activity type (``gym``, ``walking`` …).
        is_aggregate: True for day-spanning summaries (daily steps), which
            never match anything.

    Returns:
        The compatible overlapping workout, or None when the activity
        stands on its own.
    """
    if is_aggregate:
        return None

    window_end = ended_at or started_at

    candidates = Workout.query.filter(
        Workout.person_id == person_id,
        Workout.started_at <= window_end,
    ).all()

    for workout in candidates:
        workout_end = workout.ended_at or workout.started_at
        if workout_end is None:
            continue
        # Windows overlap when each starts before the other ends, widened by
        # the tolerance in both directions for clock drift.
        overlaps = (
            workout.started_at.timestamp() <= window_end.timestamp() + OVERLAP_TOLERANCE_SECONDS
            and workout_end.timestamp() >= started_at.timestamp() - OVERLAP_TOLERANCE_SECONDS
        )
        if not overlaps:
            continue

        if activity_type == "gym":
            return workout

        keywords = CARDIO_MACHINE_KEYWORDS.get(activity_type)
        if not keywords:
            # Unknown-or-impossible modality (e.g. swimming): separate.
            continue
        machines = _workout_machine_names(workout)
        if any(keyword in machine for machine in machines for keyword in keywords):
            return workout

    return None


def _process_weight(
    record: dict[str, Any], person: Person, source: str, result: dict
) -> None:
    """Store a pushed weight, plus derived BMI when height is known.

    Args:
        record: The pushed record.
        person: Whose weight this is.
        source: Source key for created rows and the import log.
        result: Running totals to update in place.
    """
    try:
        weight_kg = float(record["weight_kg"])
    except (KeyError, TypeError, ValueError):
        result["errors"].append(
            f"weight record {record.get('source_id')!r} has no usable weight_kg"
        )
        return

    measured_at = parse_time(record.get("start")) or datetime.utcnow()

    measurement = BodyMeasurement(
        person_id=person.id,
        measured_at=measured_at,
        measurement_type="weight",
        value=weight_kg,
        unit="kg",
        source=source,
        source_id=record["source_id"],
    )
    db.session.add(measurement)
    db.session.flush()

    # A scale reading without a BMI beside it leaves a gap in the BMI chart,
    # so derive one from the recorded height exactly as manual entry does.
    bmi = derive_bmi(weight_kg, person.height_cm)
    if bmi is not None:
        db.session.add(BodyMeasurement(
            person_id=person.id,
            measured_at=measured_at,
            measurement_type="bmi",
            value=bmi,
            unit="",
            source=source,
            source_id=record["source_id"],
        ))

    _log(source, record["source_id"], "weight", measurement.id, "created")
    result["imported"] += 1

    # Same rule as every other source: report disagreement, resolve nothing.
    for other_id in supersede_mismatches_within_day(measurement):
        other = db.session.get(BodyMeasurement, other_id)
        result["conflicts"].append(describe_conflict(
            measurement, other, new_label=_source_label(source),
        ))


def _process_activity(
    record: dict[str, Any], person: Person, source: str, result: dict
) -> None:
    """Store a pushed exercise or steps record, enriching on overlap.

    When the pushed record is compatible with an overlapping gym workout
    (see :func:`find_overlapping_workout`), the workout is enriched (heart
    rate, calories, a note) and the pushed record is still stored as an
    activity linked to it. Commutes, station walks and daily summaries never
    match: they are stored plain and count as their own activity.

    Args:
        record: The pushed record.
        person: Whose activity this is.
        source: Source key for created rows and the import log.
        result: Running totals to update in place.
    """
    record_kind = record["type"]
    started_at = parse_time(record.get("start")) or datetime.utcnow()
    ended_at = parse_time(record.get("end"))

    if record_kind == "steps":
        activity_type = "walking"
        notes = None
        if record.get("steps") is not None:
            try:
                notes = f"{int(record['steps'])} steps"
            except (TypeError, ValueError):
                pass
    else:
        activity_type = classify_exercise(record.get("exercise_type"))
        notes = record.get("exercise_type")

    duration = record.get("duration_seconds")
    if duration is None and ended_at is not None:
        duration = int((ended_at - started_at).total_seconds())

    try:
        duration_seconds = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_seconds = None

    def _number(value: Any) -> float | int | None:
        try:
            return value if value is None else float(value)
        except (TypeError, ValueError):
            return None

    def _integer(value: Any) -> int | None:
        number = _number(value)
        return None if number is None else int(number)

    activity = Activity(
        person_id=person.id,
        activity_type=activity_type,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=duration_seconds,
        distance_m=_number(record.get("distance_m")),
        calories=_number(record.get("calories")),
        steps=_integer(record.get("steps")),
        avg_heart_rate=record.get("avg_heart_rate"),
        max_heart_rate=record.get("max_heart_rate"),
        notes=notes,
        source=source,
        source_id=record["source_id"],
    )
    db.session.add(activity)
    db.session.flush()

    # A compatible gym workout overlapping this window is the same session:
    # enrich it rather than leaving two unconnected records. Anything else —
    # a commute, a station walk, a day-long steps summary — stands on its own
    # and counts toward the week's activity as itself.
    workout = find_overlapping_workout(
        person.id, started_at, ended_at,
        activity_type=activity_type,
        is_aggregate=(record_kind == "steps"),
    )
    if workout is not None:
        enrichment = {
            "health_connect_activity_id": activity.id,
            "health_connect_source_id": record["source_id"],
        }
        if activity.avg_heart_rate:
            enrichment["avg_heart_rate"] = activity.avg_heart_rate
        if activity.max_heart_rate:
            enrichment["max_heart_rate"] = activity.max_heart_rate
        if activity.calories:
            enrichment["calories"] = activity.calories

        activity.enrichment_data = json.dumps({
            **(json.loads(activity.enrichment_data) if activity.enrichment_data else {}),
            "correlated_workout_id": workout.id,
        })

        stamp = (
            f"{_source_label(source)} recorded {activity_type} "
            f"{started_at:%Y-%m-%d %H:%M}"
        )
        if activity.avg_heart_rate:
            stamp += f", avg HR {activity.avg_heart_rate}"
        if activity.calories:
            stamp += f", {activity.calories:g} kcal"
        stamp += "."
        workout.notes = f"{workout.notes}\n{stamp}" if workout.notes else stamp

        _log(source, record["source_id"], "activity", activity.id, "enriched")
        result["enriched"] += 1
    else:
        _log(source, record["source_id"], "activity", activity.id, "created")

    result["imported"] += 1


def process_records(
    records: list[dict[str, Any]],
    person_id: int | None = None,
    source: str = SOURCE,
) -> dict[str, Any]:
    """Store Health Connect records from either acquisition path.

    Idempotent: records already in ``import_log`` are skipped, so the same
    window can be pushed or re-imported repeatedly without duplicates.

    Args:
        records: Record dicts (see module docstring for shape).
        person_id: Whose data this is. Defaults to the first Person row.
        source: Source key for created rows. The push endpoint uses
            ``health_connect``; the CSV importer uses ``health_connect_csv``.

    Returns:
        Dict with ``imported``, ``skipped``, ``enriched``, ``conflicts``
        (list of messages) and ``errors`` (list of messages).
    """
    result: dict[str, Any] = {
        "imported": 0,
        "skipped": 0,
        "enriched": 0,
        "conflicts": [],
        "errors": [],
    }

    person = db.session.get(Person, person_id) if person_id else Person.query.first()
    if person is None:
        result["errors"].append("no profile exists to attach records to")
        return result

    for record in records:
        if not isinstance(record, dict):
            result["errors"].append(f"ignoring non-object record: {record!r:.80}")
            continue

        record_type = record.get("type")
        source_id = record.get("source_id")

        if record_type not in RECORD_TYPES:
            result["errors"].append(
                f"unknown record type {record_type!r} (source_id={source_id!r})"
            )
            continue

        if not source_id:
            result["errors"].append(
                f"{record_type} record has no source_id and cannot be deduplicated"
            )
            continue

        log_type = "weight" if record_type == "weight" else "activity"
        if already_imported(source, source_id, log_type):
            result["skipped"] += 1
            continue

        if record_type == "weight":
            _process_weight(record, person, source, result)
        else:
            _process_activity(record, person, source, result)

    db.session.commit()
    return result
