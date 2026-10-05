"""Link Technogym records into guided sessions.

Why this module exists
----------------------
A gym visit is often recorded twice: weights logged by hand in a guided
session, cardio captured by Technogym's machines (whose programs — varying
speed, incline, level — are too granular to replicate by hand). The two
halves belong to one visit and should read as one session, but merging the
rows would destroy information. So activities link *to* workouts instead:

- ``Workout.activity_id`` covers the importer's own paired activity.
- Anything else links through ``Activity.enrichment_data`` as
  ``{"correlated_workout_id": <id>}`` — the same mechanism Health Connect
  enrichment uses, so every cross-source link looks the same.
- A visible note is stamped on the workout. The link must be discoverable
  on the session page, not just in JSON.

Linking is conservative. A Technogym activity links to a manual session only
when it overlaps that session (±30 minutes for clock drift) on the same
day, the session was logged by hand (source ``manual`` — gym records never
absorb each other), and the activity is not already linked to any workout
(the live importer's paired activities belong to their own workout rows;
reassigning them would rewrite history). Anything failing these checks
stays a standalone activity, which is always the safe direction.
"""

from __future__ import annotations

import json

from ..models import Activity, Workout, db

#: How far apart two records may be while still counting as one visit.
LINK_TOLERANCE_SECONDS = 30 * 60

#: Sources whose activities may link into a manual session. Both Technogym
#: importers share the ``technogym`` source key.
LINKABLE_SOURCES = ("technogym",)

#: Workout sources that accept linked records. Only hand-logged sessions —
#: gym records never absorb each other.
LINKABLE_WORKOUT_SOURCES = ("manual",)


def _window(workout: Workout) -> tuple[float, float] | None:
    """Return a workout's (start, end) as timestamps.

    Args:
        workout: The workout.

    Returns:
        ``(start, end)`` timestamps, or None when the workout has no usable
        times. Open sessions (no end yet) count as ongoing.
    """
    from datetime import datetime

    if workout.started_at is None:
        return None
    end = workout.ended_at or datetime.now()
    return (workout.started_at.timestamp(), end.timestamp())


def linked_activities(workout: Workout) -> list[Activity]:
    """Every activity belonging to a workout, however linked.

    Args:
        workout: The workout.

    Returns:
        The importer's own paired activity (if any) plus activities linked
        through ``enrichment_data``, ordered by start time.
    """
    linked: list[Activity] = []

    if workout.activity_id:
        paired = db.session.get(Activity, workout.activity_id)
        if paired is not None:
            linked.append(paired)

    for activity in Activity.query.filter(
        Activity.person_id == workout.person_id,
        Activity.source.in_(LINKABLE_SOURCES),
    ).all():
        try:
            data = json.loads(activity.enrichment_data or "{}")
        except (ValueError, TypeError):
            continue
        if data.get("correlated_workout_id") == workout.id and activity not in linked:
            linked.append(activity)

    linked.sort(key=lambda activity: activity.started_at)
    return linked


def _is_linked(activity: Activity) -> bool:
    """Check whether an activity already belongs to any workout.

    Args:
        activity: The activity.

    Returns:
        True when paired via any ``Workout.activity_id`` or carrying a
        ``correlated_workout_id``.
    """
    if Workout.query.filter_by(activity_id=activity.id).first() is not None:
        return True
    try:
        data = json.loads(activity.enrichment_data or "{}")
    except (ValueError, TypeError):
        return False
    return data.get("correlated_workout_id") is not None


def link_candidates(workout: Workout) -> list[Activity]:
    """Technogym activities that could belong to a manual session.

    Args:
        workout: A hand-logged session.

    Returns:
        Unlinked Technogym activities overlapping the session window on the
        same calendar day. Empty for non-manual sessions.
    """
    if workout.source not in LINKABLE_WORKOUT_SOURCES:
        return []

    window = _window(workout)
    if window is None:
        return []

    start, end = window
    day = workout.started_at.date()
    candidates = []

    for activity in Activity.query.filter(
        Activity.person_id == workout.person_id,
        Activity.source.in_(LINKABLE_SOURCES),
    ).all():
        if activity.started_at is None or activity.started_at.date() != day:
            continue
        activity_end = activity.ended_at or activity.started_at
        if not (
            activity.started_at.timestamp()
            <= end + LINK_TOLERANCE_SECONDS
            and activity_end.timestamp()
            >= start - LINK_TOLERANCE_SECONDS
        ):
            continue
        if _is_linked(activity):
            continue
        candidates.append(activity)

    candidates.sort(key=lambda activity: activity.started_at)
    return candidates


def link_activity_to_workout(activity: Activity, workout: Workout) -> bool:
    """Link one Technogym activity into a manual session.

    Idempotent: already-linked activities are skipped, so imports and the
    manual button can both run freely.

    Args:
        activity: The Technogym activity.
        workout: The manual session.

    Returns:
        True when a new link was created, False when already linked.
    """
    try:
        data = json.loads(activity.enrichment_data or "{}")
    except (ValueError, TypeError):
        data = {}
    if data.get("correlated_workout_id") == workout.id:
        return False

    data["correlated_workout_id"] = workout.id
    activity.enrichment_data = json.dumps(data)

    stamp = (
        f"Technogym recorded {activity.activity_type} "
        f"{activity.started_at:%Y-%m-%d %H:%M}"
    )
    if activity.duration_seconds:
        stamp += f", {int(activity.duration_seconds // 60)} min"
    if activity.distance_m:
        stamp += f", {activity.distance_m:g} m"
    if activity.calories:
        stamp += f", {activity.calories:g} kcal"
    stamp += " as part of this session."
    workout.notes = f"{workout.notes}\n{stamp}" if workout.notes else stamp

    return True
