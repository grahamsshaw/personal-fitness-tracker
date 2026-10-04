"""Body measurement reconciliation: conflicts, current values, and chart series.

Why this module exists
----------------------
Weight and BMI arrive from several places at once - the Wii Fit scale, Technogym's
own records, Health Connect, and manual entry. These sources disagree. The
Wii Fit scale and Technogym can both claim a weight for the same day, with
different numbers, and neither is obviously wrong.

The rule this module implements is deliberately conservative:

    **Nothing is ever discarded automatically.**

An importer never overwrites, deletes, or hides an existing reading. Instead it
records what arrived, and any disagreement with other readings for the same day
is reported as a *conflict*. The user then decides, on the profile page, which
value they believe. Only that decision - stored as ``is_superseded`` on the
rejected rows - changes what the app treats as current.

Keeping every reading matters for a fitness tracker: a 105 kg Technogym entry
that disagrees with a 99.5 kg scale reading is not noise, it is the record of a
period of gain. Auto-resolving it would quietly rewrite history.

Conflict definition
-------------------
Two readings conflict when they are:

1. the same measurement type (weight vs weight, bmi vs bmi),
2. attributed to the **same calendar day**, and
3. recorded by **different sources**, and
4. **materially different values** (differing by more than
   ``VALUE_TOLERANCE`` for that type).

Those four conditions together deliberately exclude several cases that look
like conflicts but are not:

- The **same source** twice in a day (stepping on the Wii Fit scale at 07:00 and
  again at 21:00) is normal behaviour, not a conflict.
- **Tiny rounding differences** between sources are not worth bothering anyone
  about, hence the tolerance.
- Readings on **different days** are history, not disagreement - a weight last
  month is expected to differ from today.

Only weight and BMI participate by default. ``CONFLICT_TYPES`` can be extended,
but height is deliberately excluded: it is a fixed physical property rather than
a fluctuating measurement, so two different heights on the same day means one
source is simply wrong about who you are.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterable, Sequence

from ..models import BodyMeasurement, Person

# Measurement types that are expected to fluctuate and so can conflict.
# Height is intentionally excluded - see the module docstring.
CONFLICT_TYPES = ("weight", "bmi")

# Minimum meaningful difference between two readings of the same type before
# they are worth calling a conflict. Values closer than this are treated as the
# same number measured slightly differently.
#
#   weight: 0.05 kg - catches 99.5 vs 99.53, ignores float noise
#   bmi:   0.01     - BMI is quoted to two decimal places
VALUE_TOLERANCE = {
    "weight": 0.05,
    "bmi": 0.01,
}

# Default tolerance when a type is not listed above.
DEFAULT_TOLERANCE = 0.01


def tolerance_for(measurement_type: str) -> float:
    """Return the smallest value difference worth reporting for a type.

    Args:
        measurement_type: e.g. ``"weight"`` or ``"bmi"``.

    Returns:
        The tolerance; readings closer together than this are not a conflict.
    """
    return VALUE_TOLERANCE.get(measurement_type, DEFAULT_TOLERANCE)


def derive_bmi(weight_kg: float, height_cm: float | None) -> float | None:
    """Calculate BMI from a weight and a height.

    Lives here so that every entry point derives BMI the same way. It used to be
    inline in the manual-entry route only, which meant an API caller posting a
    weight got a weight row with no BMI beside it and a gap in the BMI chart.

    Args:
        weight_kg: Weight in kilograms.
        height_cm: Height in centimetres. ``None`` or non-positive when unknown.

    Returns:
        BMI rounded to two decimal places, or ``None`` when there is no usable
        height. ``None`` rather than a guess: a BMI computed from an assumed
        height would be indistinguishable from a measured one, which is exactly
        the kind of invisible invention this project avoids.
    """
    if not height_cm or height_cm <= 0:
        return None

    height_m = height_cm / 100.0
    return round(weight_kg / (height_m * height_m), 2)


def describe_conflict(
    new_reading: BodyMeasurement | Reading,
    other: BodyMeasurement | Reading,
    new_label: str | None = None,
) -> str:
    """Describe a disagreement between two readings of the same day and type.

    One place for this wording, because it is shown in four contexts - importer
    output, the import log, the manual-entry flash, and the API response - and
    four slightly different phrasings of "these disagree, you choose" is worse
    than useless when you are trying to work out which reading a message refers to.

    Args:
        new_reading: The reading that just arrived.
        other: An existing reading it disagrees with.
        new_label: How to name the new reading's source. Defaults to its own
            source, which is what you want unless the importer knows better
            (e.g. "Wii Fit" reads better than "wii_fit").

    Returns:
        A message naming both values, both sources, the day, and what to do.
    """
    new = Reading.from_model(new_reading) if isinstance(new_reading, BodyMeasurement) else new_reading
    old = Reading.from_model(other) if isinstance(other, BodyMeasurement) else other

    label = new_label or new.source
    unit_sep = " " if new.unit else ""

    return (
        f"{new.day.isoformat()}: {label} recorded "
        f"{new.value:g}{unit_sep}{new.unit}, but "
        f"{describe_reading(old)}. Both are stored - choose which to use on "
        f"the profile page."
    )


@dataclass
class Reading:
    """One measurement, shaped for the UI and the conflict API."""

    id: int
    measured_at: datetime
    day: date
    value: float
    unit: str
    source: str
    source_id: str | None
    is_superseded: bool

    @classmethod
    def from_model(cls, row: BodyMeasurement) -> "Reading":
        """Build a Reading from a BodyMeasurement row.

        Args:
            row: The stored measurement.

        Returns:
            The equivalent Reading.
        """
        return cls(
            id=row.id,
            measured_at=row.measured_at,
            day=row.measured_at.date(),
            value=row.value,
            unit=row.unit,
            source=row.source or "manual",
            source_id=row.source_id,
            is_superseded=bool(row.is_superseded),
        )


@dataclass
class Conflict:
    """A day on which two or more sources disagree about the same measurement.

    Attributes:
        measurement_type: ``"weight"`` or ``"bmi"``.
        day: The calendar day the disagreement is about.
        readings: Every non-superseded reading for that type and day, ordered by
            time. All of them are still valid records; the user simply has to
            say which one to believe.
    """

    measurement_type: str
    day: date
    readings: list[Reading] = field(default_factory=list)

    @property
    def values(self) -> list[float]:
        """The distinct values in dispute, lowest first."""
        return sorted({reading.value for reading in self.readings})

    @property
    def spread(self) -> float:
        """Difference between the highest and lowest disputed values."""
        values = self.values
        return values[-1] - values[0] if len(values) > 1 else 0.0

    @property
    def sources(self) -> list[str]:
        """The distinct sources involved, for display."""
        return sorted({reading.source for reading in self.readings})


def _readings_for(person_id: int, measurement_type: str) -> list[Reading]:
    """Load the active readings of one type for one person, oldest first.

    Superseded readings are excluded: once the user has settled a day, it is no
    longer an open question.

    Args:
        person_id: Whose measurements to load.
        measurement_type: Type to filter on.

    Returns:
        List of Readings ordered by measurement time.
    """
    rows = (
        BodyMeasurement.query.filter_by(
            person_id=person_id,
            measurement_type=measurement_type,
        )
        .order_by(BodyMeasurement.measured_at)
        .all()
    )
    return [Reading.from_model(row) for row in rows if not row.is_superseded]


def find_conflicts(
    person_id: int | None = None,
    measurement_types: Sequence[str] = CONFLICT_TYPES,
) -> list[Conflict]:
    """Find every day on which sources disagree, without changing anything.

    This is the read-only check an importer calls after it has stored new data.
    It is deliberately side-effect free: it reports, the user decides.

    Args:
        person_id: Whose data to check. Defaults to the first Person row.
        measurement_types: Which types to examine.

    Returns:
        Conflicts sorted by day (oldest first), then by type.

    Raises:
        ValueError: If there are no people to check.
    """
    if person_id is None:
        person = Person.query.first()
        if not person:
            return []
        person_id = person.id

    conflicts: list[Conflict] = []

    for measurement_type in measurement_types:
        readings = _readings_for(person_id, measurement_type)

        # Bucket by calendar day.
        by_day: dict[date, list[Reading]] = defaultdict(list)
        for reading in readings:
            by_day[reading.day].append(reading)

        for day, day_readings in by_day.items():
            # Two readings from the same source are not a conflict - weighing
            # yourself twice in a day is normal.
            if len({r.source for r in day_readings}) < 2:
                continue

            # Nor is a difference small enough to be rounding.
            tolerance = tolerance_for(measurement_type)
            values = [r.value for r in day_readings]
            if max(values) - min(values) <= tolerance:
                continue

            conflicts.append(
                Conflict(
                    measurement_type=measurement_type,
                    day=day,
                    readings=sorted(day_readings, key=lambda r: r.measured_at),
                )
            )

    conflicts.sort(key=lambda c: (c.day, c.measurement_type))
    return conflicts


def current_measurement(
    measurement_type: str,
    person_id: int | None = None,
) -> BodyMeasurement | None:
    """Return the reading to show as the current value for a type.

    Ignores superseded readings and, where a day has a conflict, takes the most
    recent reading on the most recent day. When two sources disagree on that
    same day the choice is genuinely arbitrary - which is precisely why the
    conflict is surfaced on the profile page for the user to settle.

    Args:
        measurement_type: e.g. ``"weight"``.
        person_id: Whose data to read. Defaults to the first Person row.

    Returns:
        The BodyMeasurement to treat as current, or None if there is none.
    """
    if person_id is None:
        person = Person.query.first()
        if not person:
            return None
        person_id = person.id

    return (
        BodyMeasurement.query.filter_by(
            person_id=person_id,
            measurement_type=measurement_type,
            is_superseded=False,
        )
        .order_by(BodyMeasurement.measured_at.desc())
        .first()
    )


def current_values(person_id: int | None = None) -> dict[str, BodyMeasurement | None]:
    """Return the current reading for each conflict-prone type.

    Args:
        person_id: Whose data to read. Defaults to the first Person row.

    Returns:
        Mapping of measurement type to its current BodyMeasurement (or None).
    """
    return {
        measurement_type: current_measurement(measurement_type, person_id)
        for measurement_type in CONFLICT_TYPES
    }


def series(
    measurement_type: str,
    include_superseded: bool = False,
    person_id: int | None = None,
) -> list[dict]:
    """Build a chart-ready series for one measurement type.

    Args:
        measurement_type: Type to plot.
        include_superseded: Include readings the user has rejected. Off by
            default so the chart shows the values they actually stand behind.
        person_id: Whose data to read. Defaults to the first Person row.

    Returns:
        List of point dicts, oldest first, each with ``date``, ``value``,
        ``source`` and ``superseded``.
    """
    if person_id is None:
        person = Person.query.first()
        if not person:
            return []
        person_id = person.id

    query = BodyMeasurement.query.filter_by(
        person_id=person_id,
        measurement_type=measurement_type,
    )
    if not include_superseded:
        query = query.filter_by(is_superseded=False)

    rows = query.order_by(BodyMeasurement.measured_at).all()

    return [
        {
            "date": row.measured_at.strftime("%Y-%m-%d"),
            "time": row.measured_at.strftime("%H:%M"),
            "value": row.value,
            "unit": row.unit,
            "source": row.source or "manual",
            "superseded": bool(row.is_superseded),
            "id": row.id,
        }
        for row in rows
    ]


def resolve_conflict(
    measurement_type: str,
    day: date,
    keep_id: int,
    person_id: int | None = None,
) -> dict:
    """Record the user's decision about a disputed day.

    The chosen reading is kept and every other reading for that type and day is
    marked superseded and linked to it. Nothing is deleted, and the decision can
    be undone by calling :func:`clear_superseded` with the same type and day.

    Args:
        measurement_type: Type the decision applies to.
        day: The calendar day being decided.
        keep_id: ``id`` of the BodyMeasurement the user chose.
        person_id: Whose data this is. Defaults to the first Person row.

    Returns:
        Dict with ``kept`` (the id kept), ``superseded`` (ids now hidden) and
        ``undone`` (True when nothing needed changing).

    Raises:
        ValueError: If ``keep_id`` is not a reading of this type on this day.
    """
    from .. import db

    if person_id is None:
        person = Person.query.first()
        if not person:
            return {"kept": None, "superseded": [], "undone": True}
        person_id = person.id

    keeper = db.session.get(BodyMeasurement, keep_id)
    if (
        keeper is None
        or keeper.person_id != person_id
        or keeper.measurement_type != measurement_type
        or keeper.measured_at.date() != day
    ):
        raise ValueError(
            f"Measurement {keep_id} is not a {measurement_type} reading on {day}."
        )

    start_of_day = datetime.combine(day, datetime.min.time())
    end_of_day = datetime.combine(day, datetime.max.time())

    others = (
        BodyMeasurement.query.filter(
            BodyMeasurement.person_id == person_id,
            BodyMeasurement.measurement_type == measurement_type,
            BodyMeasurement.measured_at >= start_of_day,
            BodyMeasurement.measured_at <= end_of_day,
            BodyMeasurement.id != keep_id,
        )
        .all()
    )

    now = datetime.utcnow()
    superseded_ids: list[int] = []

    for other in others:
        if not other.is_superseded:
            other.is_superseded = True
            other.superseded_by_id = keeper.id
            other.superseded_at = now
            superseded_ids.append(other.id)

    # The keeper must never itself be marked superseded.
    keeper.is_superseded = False
    keeper.superseded_by_id = None
    keeper.superseded_at = None

    db.session.commit()

    return {
        "kept": keeper.id,
        "superseded": superseded_ids,
        "undone": not superseded_ids,
    }


def clear_superseded(
    measurement_type: str,
    day: date,
    person_id: int | None = None,
) -> int:
    """Undo a previous decision, putting every reading for a day back in play.

    Args:
        measurement_type: Type the decision applied to.
        day: The day to reopen.
        person_id: Whose data this is. Defaults to the first Person row.

    Returns:
        How many readings were restored.
    """
    from .. import db

    if person_id is None:
        person = Person.query.first()
        if not person:
            return 0
        person_id = person.id

    start_of_day = datetime.combine(day, datetime.min.time())
    end_of_day = datetime.combine(day, datetime.max.time())

    rows = (
        BodyMeasurement.query.filter(
            BodyMeasurement.person_id == person_id,
            BodyMeasurement.measurement_type == measurement_type,
            BodyMeasurement.measured_at >= start_of_day,
            BodyMeasurement.measured_at <= end_of_day,
            BodyMeasurement.is_superseded.is_(True),
        )
        .all()
    )

    for row in rows:
        row.is_superseded = False
        row.superseded_by_id = None
        row.superseded_at = None

    db.session.commit()
    return len(rows)


def supersede_mismatches_within_day(
    new_reading: BodyMeasurement,
    person_id: int | None = None,
) -> list[int]:
    """Find existing readings the new one disagrees with on the same day.

    Called by importers after storing a measurement. This is a **check, not an
    edit**: it reports what the new data appears to contradict and changes
    nothing, leaving the decision to the user.

    Args:
        new_reading: The measurement that was just stored.
        person_id: Whose data this is. Defaults to the first Person row.

    Returns:
        Ids of same-type readings from *other* sources on the same calendar day
        whose value differs by more than the tolerance. Empty when there is
        nothing to reconcile.
    """
    if new_reading.measurement_type not in CONFLICT_TYPES:
        return []

    if person_id is None:
        person_id = new_reading.person_id

    day = new_reading.measured_at.date()
    start_of_day = datetime.combine(day, datetime.min.time())
    end_of_day = datetime.combine(day, datetime.max.time())

    tolerance = tolerance_for(new_reading.measurement_type)

    others = (
        BodyMeasurement.query.filter(
            BodyMeasurement.person_id == person_id,
            BodyMeasurement.measurement_type == new_reading.measurement_type,
            BodyMeasurement.measured_at >= start_of_day,
            BodyMeasurement.measured_at <= end_of_day,
            BodyMeasurement.id != new_reading.id,
            BodyMeasurement.source != new_reading.source,
        )
        .all()
    )

    return [
        other.id
        for other in others
        if abs(other.value - new_reading.value) > tolerance
    ]


def describe_reading(reading: Reading) -> str:
    """Format a reading as a short human-readable label.

    Args:
        reading: The reading to describe.

    Returns:
        e.g. ``"99.5 kg from wii_fit on 2026-10-02"``.
    """
    unit = reading.unit or ""
    separator = " " if unit else ""
    return f"{reading.value:g}{separator}{unit} from {reading.source} on {reading.day.isoformat()}"