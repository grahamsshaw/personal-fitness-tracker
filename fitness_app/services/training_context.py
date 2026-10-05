"""Holistic training context: what the user has done, across every source.

Why this module exists
----------------------
Weight, workouts and daily activity arrive from several places — the gym
(Technogym), the phone (Health Connect), the Wii, manual entry — and each
importer only knows its own records. Anything that reasons about training as
a whole (the guided runner's suggestions today, the LLM assistant tomorrow)
needs one assembled picture: recent sessions whatever their origin, what
muscles they trained, how this week compares, what is undecided, and where
the goals stand.

This module builds that picture as plain JSON-safe dicts. The guided runner
reads it to stay aware of non-gym activity; the future
``POST /api/assistant/ask`` will consume the same snapshot as its prompt
context (see ``GET /api/training-context``, which serves exactly this).
One builder, every consumer — so the human UI and the eventual LLM can never
disagree about what has happened.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from ..models import db, Activity, BodyMeasurement, Person, Workout
from . import measurements as measurement_service
from . import muscles as muscle_service


def _week_bounds(today: date) -> tuple[datetime, datetime]:
    """Return the Monday-00:00 to now bounds of the current week.

    Args:
        today: Reference day.

    Returns:
        ``(week_start, now)`` as datetimes.
    """
    week_start = today - timedelta(days=today.weekday())
    return (
        datetime.combine(week_start, datetime.min.time()),
        datetime.combine(today, datetime.max.time()),
    )


def weekly_by_source(person_id: int, today: date | None = None) -> dict:
    """Sessions and minutes this week, broken down by source.

    Workouts and activities are both counted — a gym session and a Health
    Connect walk are both training, and the whole point of unifying sources
    is that the weekly total reflects both. Minutes come from
    ``duration_seconds`` where recorded, else from start/end spans.

    Args:
        person_id: Whose week to measure.
        today: Reference day. Defaults to today.

    Returns:
        Dict with ``sessions``, ``minutes`` and ``by_source`` mapping each
        source to its ``{"sessions": n, "minutes": m}``.
    """
    today = today or date.today()
    start, _end = _week_bounds(today)

    by_source: dict[str, dict[str, int]] = {}

    def add(source: str, minutes: int) -> None:
        entry = by_source.setdefault(source or "manual", {"sessions": 0, "minutes": 0})
        entry["sessions"] += 1
        entry["minutes"] += minutes

    def minutes_of(started, ended, duration_seconds) -> int:
        if duration_seconds:
            return int(duration_seconds // 60)
        if started and ended:
            return max(0, int((ended - started).total_seconds() // 60))
        return 0

    for workout in Workout.query.filter(
        Workout.person_id == person_id, Workout.started_at >= start
    ).all():
        add(workout.source,
            minutes_of(workout.started_at, workout.ended_at, workout.duration_seconds))

    for activity in Activity.query.filter(
        Activity.person_id == person_id, Activity.started_at >= start
    ).all():
        add(activity.source,
            minutes_of(activity.started_at, activity.ended_at, activity.duration_seconds))

    return {
        "sessions": sum(entry["sessions"] for entry in by_source.values()),
        "minutes": sum(entry["minutes"] for entry in by_source.values()),
        "by_source": by_source,
    }


def recent_sessions(person_id: int, limit: int = 10) -> list[dict]:
    """The most recent sessions from every source, newest first.

    Each entry names what it was and where it came from, so a reader —
    human or model — can see at a glance that Tuesday was a Technogym visit
    and Thursday was a Health Connect walk, rather than "3 sessions".

    Args:
        person_id: Whose sessions to list.
        limit: Maximum entries. Defaults to 10.

    Returns:
        List of ``{"date", "kind", "name", "source", "minutes", "calories"}``.
    """
    entries: list[dict] = []

    def minutes_of(started, ended, duration_seconds) -> int | None:
        if duration_seconds:
            return int(duration_seconds // 60)
        if started and ended:
            return max(0, int((ended - started).total_seconds() // 60))
        return None

    for workout in Workout.query.filter(
        Workout.person_id == person_id
    ).order_by(Workout.started_at.desc()).limit(limit).all():
        entries.append({
            "date": workout.started_at.date().isoformat(),
            "kind": "workout",
            "name": workout.workout_name or "Workout",
            "source": workout.source or "manual",
            "minutes": minutes_of(workout.started_at, workout.ended_at,
                                  workout.duration_seconds),
            "calories": None,
        })

    for activity in Activity.query.filter(
        Activity.person_id == person_id
    ).order_by(Activity.started_at.desc()).limit(limit).all():
        entries.append({
            "date": activity.started_at.date().isoformat(),
            "kind": "activity",
            "name": activity.activity_type,
            "source": activity.source or "manual",
            "minutes": minutes_of(activity.started_at, activity.ended_at,
                                  activity.duration_seconds),
            "calories": activity.calories,
        })

    entries.sort(key=lambda entry: entry["date"], reverse=True)
    return entries[:limit]


def estimate_1rm(weight_kg: float | None, reps: int | None) -> float | None:
    """Estimate one-rep max with the Epley formula.

    Standard training methodology, not anyone's proprietary logic:
    ``w × (1 + r/30)``. Refused above 12 reps, where the formula stops
    meaning anything — a guess presented as a number would be worse than
    no number.

    Args:
        weight_kg: Working weight.
        reps: Reps performed.

    Returns:
        Rounded 1RM estimate, or None when it cannot be computed honestly.
    """
    if not weight_kg or not reps or reps < 1 or reps > 12:
        return None
    if reps == 1:
        return round(weight_kg, 1)
    return round(weight_kg * (1 + reps / 30), 1)


def snapshot(person_id: int | None = None, today: date | None = None) -> dict:
    """Assemble the holistic training snapshot.

    Args:
        person_id: Whose snapshot. Defaults to the first profile.
        today: Reference day. Defaults to today.

    Returns:
        JSON-safe dict: person/goals, current weight/BMI, this week's
        cross-source totals, recent sessions, muscle load, open conflicts.
        Empty-dataset safe: every section degrades to nulls and empty
        lists rather than failing.
    """
    today = today or date.today()
    person = db.session.get(Person, person_id) if person_id else Person.query.first()
    if person is None:
        return {"person": None, "empty": True}

    current = measurement_service.current_values()
    weight = current.get("weight")
    bmi = current.get("bmi")
    load = muscle_service.muscle_load(person.id, today=today)

    hottest = sorted(
        ((muscle, values["fatigue"]) for muscle, values in load.items()),
        key=lambda item: -item[1],
    )[:5]

    return {
        "person": {
            "name": f"{person.first_name or ''} {person.last_name or ''}".strip(),
            "weight_goal_kg": person.weight_goal_kg,
            "height_cm": person.height_cm,
        },
        "current": {
            "weight": {
                "value": weight.value if weight else None,
                "date": weight.measured_at.date().isoformat() if weight else None,
                "source": weight.source if weight else None,
            },
            "bmi": {
                "value": bmi.value if bmi else None,
                "date": bmi.measured_at.date().isoformat() if bmi else None,
                "source": bmi.source if bmi else None,
            },
        },
        "this_week": weekly_by_source(person.id, today=today),
        "recent_sessions": recent_sessions(person.id),
        "muscles": {
            "hottest": [{"muscle": muscle, "fatigue": level}
                        for muscle, level in hottest if level > 0],
            "neglected": muscle_service.neglected_muscles(person.id, today=today),
        },
        "open_conflicts": len(measurement_service.find_conflicts()),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
