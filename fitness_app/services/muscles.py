"""Muscle groups: canonical names, spelling normalisation, training load.

Why this module exists
----------------------
Exercise data names muscles in free text and is not consistent about it:
"shoulders", "deltoids" and "delts" are the same thing, as are "quads" and
"quadriceps", "core" and "abs". The body map can only draw a fixed set of
muscles, so every spelling has to collapse onto one canonical name before
anything is counted or shaded.

The canonical set (18 drawable muscles) follows standard anatomy naming.
The alias table below was built from the actual spellings occurring in the
imported exercise library — it maps what the data says, not what a reference
implementation maps. Anything genuinely undrawable (hands, "cardiovascular
system") maps to None and is dropped rather than guessed at.

Training load
-------------
Two views over the same logged work, computed from workout history:

- **fatigue**: how recently each muscle was trained. High means rest — a
  muscle trained yesterday reads hotter than one trained six days ago.
- **strength**: retained training over a longer window. A muscle trained
  consistently for weeks reads high; one untouched for months fades.

Both are honest heuristics, not physiology: the app knows what was logged,
not what recovered. They answer "what have I been training" and "what am I
neglecting", which is what the map is for.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from ..models import db, Exercise, Workout, WorkoutExercise

#: Muscles the body map can shade, head to toe. Also the order of any list
#: built from them, so "what am I neglecting" reads top-down like a body.
MUSCLES = [
    "trapezius",
    "deltoids",
    "chest",
    "upper-back",
    "serratus",
    "biceps",
    "triceps",
    "forearm",
    "abs",
    "obliques",
    "lower-back",
    "gluteal",
    "quadriceps",
    "hamstring",
    "adductors",
    "hip-flexors",
    "calves",
    "tibialis",
]

#: Free-text spelling -> canonical muscle(s), or None when undrawable. Built
#: from the spellings occurring in the exercise library's target/secondary
#: fields and the equipment profiles' muscles-used lists. Most spellings name
#: one muscle; a few genuinely mean two ("arms" worked by a cross-trainer are
#: biceps and triceps together), so values may be a list. Regional groupings
#: are deliberate and documented in the module docstring.
ALIAS: dict[str, str | list[str] | None] = {
    "trapezius": "trapezius",
    "traps": "trapezius",
    "levator scapulae": "trapezius",
    "deltoids": "deltoids",
    "delts": "deltoids",
    "shoulders": "deltoids",
    "anterior deltoids": "deltoids",
    "lateral deltoids": "deltoids",
    "rear deltoids": "deltoids",
    "rotator cuff": "deltoids",
    "chest": "chest",
    "pectorals": "chest",
    "upper chest": "chest",
    "upper back": "upper-back",
    "upper-back": "upper-back",
    "lats": "upper-back",
    "latissimus dorsi": "upper-back",
    "rhomboids": "upper-back",
    "back": "upper-back",
    "serratus": "serratus",
    "serratus anterior": "serratus",
    "biceps": "biceps",
    "biceps brachii": "biceps",
    "brachialis": "biceps",
    "triceps": "triceps",
    "triceps brachii": "triceps",
    "upper pectorals": "chest",
    "forearm": "forearm",
    "forearms": "forearm",
    "arms": ["biceps", "triceps"],
    "wrists": "forearm",
    "wrist flexors": "forearm",
    "wrist extensors": "forearm",
    "grip muscles": "forearm",
    "abs": "abs",
    "abdominals": "abs",
    "rectus abdominis": "abs",
    "core": "abs",
    "core stabilisers": "abs",
    "lower abs": "abs",
    "obliques": "obliques",
    "lower back": "lower-back",
    "lower-back": "lower-back",
    "spine": "lower-back",
    "gluteal": "gluteal",
    "glutes": "gluteal",
    "quadriceps": "quadriceps",
    "quads": "quadriceps",
    "hamstring": "hamstring",
    "hamstrings": "hamstring",
    "adductors": "adductors",
    "abductors": "adductors",
    "groin": "adductors",
    "inner thighs": "adductors",
    "hip flexors": "hip-flexors",
    "hip-flexors": "hip-flexors",
    "calves": "calves",
    "soleus": "calves",
    "tibialis": "tibialis",
    "shins": "tibialis",
    # Undrawable: dropped, never guessed at.
    "cardiovascular system": None,
    "hands": None,
    "feet": None,
    "ankles": None,
    "ankle stabilizers": None,
    "sternocleidomastoid": None,
}

#: Days defining the fatigue window: work in the last week shades hot.
FATIGUE_DAYS = 7

#: Days defining the strength window: consistent work over three months reads high.
STRENGTH_DAYS = 90


def normalize_muscle(raw: str | None) -> str | None:
    """Collapse a free-text muscle spelling onto its canonical name.

    Args:
        raw: e.g. ``"Delts"``.

    Returns:
        Canonical name, or None when undrawable or unknown. Unknown spellings
        return None rather than a guess — an unmapped muscle simply does not
        shade, and the spelling shows up in testing as a gap to close. When a
        spelling genuinely means two muscles (``"arms"``), the first is
        returned; use :func:`normalize_many` for all of them.
    """
    many = normalize_many(raw)
    return many[0] if many else None


def normalize_many(raw: str | None) -> list[str]:
    """Collapse a free-text muscle spelling onto canonical names.

    Args:
        raw: e.g. ``"Arms"``.

    Returns:
        List of canonical names (usually one, sometimes two, empty when
        undrawable or unknown).
    """
    if not raw:
        return []
    mapped = ALIAS.get(raw.strip().lower())
    if mapped is None:
        return []
    return [mapped] if isinstance(mapped, str) else list(mapped)


def muscles_for_exercise(exercise: Exercise) -> list[str]:
    """Canonical muscles an exercise trains: target first, then secondary.

    Args:
        exercise: An Exercise row (ideally library-enriched).

    Returns:
        Ordered, deduplicated canonical names.
    """
    import json as json_module

    ordered: list[str] = []

    def add(raw: str | None) -> None:
        for canonical in normalize_many(raw):
            if canonical not in ordered:
                ordered.append(canonical)

    add(exercise.target_muscle)
    try:
        secondary = json_module.loads(exercise.secondary_muscles or "[]")
    except (ValueError, TypeError):
        secondary = []
    for raw in secondary or []:
        add(raw)

    # Fall back to the legacy single muscle_group column for hand-entered
    # exercises the library import has never touched.
    if not ordered and exercise.muscle_group:
        add(exercise.muscle_group)

    return ordered


def muscles_for_workout_exercise(workout_exercise) -> list[str]:
    """Canonical muscles one logged workout exercise trained.

    Resolution order, first hit wins per muscle:

    1. The linked ``Exercise`` row, when it carries library metadata.
    2. The machine name (``machine`` or ``equipment_name``) matched against
       the ``Equipment`` table: the machine's profile lists what it works,
       so a Technogym program row like ``"Low Row Sel: Pull"`` resolves
       through its machine's profile without any name guessing.
    3. Nothing — an unresolvable row trains nothing as far as the map is
       concerned, rather than something invented.

    Args:
        workout_exercise: A WorkoutExercise row.

    Returns:
        Ordered, deduplicated canonical names.
    """
    import json as json_module

    from ..models import Equipment, EquipmentProfile

    ordered: list[str] = []

    def add_many(raw_list) -> None:
        for raw in raw_list or []:
            for canonical in normalize_many(raw):
                if canonical not in ordered:
                    ordered.append(canonical)

    exercise = None
    if workout_exercise.exercise_id:
        exercise = db.session.get(Exercise, workout_exercise.exercise_id)
    if exercise is not None:
        for muscle in muscles_for_exercise(exercise):
            if muscle not in ordered:
                ordered.append(muscle)
        if ordered:
            return ordered

    # Technogym program rows link to program stubs, not library exercises.
    # Their machine names match Equipment rows whose profiles name muscles.
    machine = (
        workout_exercise.machine or workout_exercise.equipment_name or ""
    ).strip()
    if machine:
        equipment = Equipment.query.filter(
            db.func.lower(Equipment.name) == machine.lower()
        ).first()
        profile = equipment.profile if equipment is not None else None
        if profile is not None and profile.muscles_used:
            try:
                add_many(json_module.loads(profile.muscles_used))
            except (ValueError, TypeError):
                pass

    return ordered


def _sessions_by_muscle(person_id: int, since: date) -> dict[str, set[date]]:
    """Map each muscle to the days it was trained since a date.

    A muscle counts as trained on a day when any of that day's workout
    exercises targets it. Volume within the day does not multiply: showing up
    is what the map reports, not tonnage.

    Args:
        person_id: Whose history to read.
        since: Earliest training day to include.

    Returns:
        Mapping of canonical muscle to the set of days trained.
    """
    trained: dict[str, set[date]] = defaultdict(set)

    rows = (
        db.session.query(WorkoutExercise, Workout)
        .join(Workout, WorkoutExercise.workout_id == Workout.id)
        .filter(
            Workout.person_id == person_id,
            Workout.started_at >= since,
        )
        .all()
    )

    for workout_exercise, workout in rows:
        day = workout.started_at.date()
        for muscle in muscles_for_workout_exercise(workout_exercise):
            trained[muscle].add(day)

    return trained


def muscle_load(person_id: int, today: date | None = None) -> dict[str, dict[str, int]]:
    """Compute fatigue and strength levels per muscle, 0-4 for shading.

    - fatigue: 4 when trained yesterday-or-today, fading to 0 past a week.
      High means rest.
    - strength: trained-days in the last 90 days bucketed 0-4. Train again
      to reset what fades.

    Args:
        person_id: Whose history to read.
        today: Reference day. Defaults to today.

    Returns:
        Mapping of canonical muscle to ``{"fatigue": n, "strength": n}``.
        Muscles never trained read 0/0.
    """
    today = today or date.today()

    recent = _sessions_by_muscle(person_id, today - timedelta(days=STRENGTH_DAYS))

    load: dict[str, dict[str, int]] = {}
    for muscle in MUSCLES:
        days = recent.get(muscle, set())

        # Fatigue: recency of the latest session, 4 (trained today/
        # yesterday) down to 0 (nothing in the window).
        latest = max(days) if days else None
        if latest is None:
            fatigue = 0
        else:
            age = (today - latest).days
            fatigue = max(0, 4 - (age * 4 // (FATIGUE_DAYS + 1)))

        # Strength: trained-days in the window, bucketed so any training at
        # all registers: 1-2 days reads 1, 3-5 reads 2, 6-9 reads 3, 10+
        # (roughly weekly across the window) reads full. A coarser bucket
        # would zero out a single recent session, which reads as "never
        # trained" — exactly the wrong message the day after a workout.
        trained_days = len(days)
        strength = min(4, (trained_days + 2) // 3) if trained_days else 0

        load[muscle] = {"fatigue": fatigue, "strength": strength}

    return load


def neglected_muscles(person_id: int, today: date | None = None) -> list[str]:
    """Muscles with no training in the strength window, head to toe.

    Args:
        person_id: Whose history to read.
        today: Reference day. Defaults to today.

    Returns:
        Canonical names, in map order.
    """
    load = muscle_load(person_id, today=today)
    return [muscle for muscle in MUSCLES if load[muscle]["strength"] == 0]


def muscle_history(
    person_id: int, muscle: str, today: date | None = None
) -> dict:
    """Recent training for one muscle, for the map's click panel.

    Args:
        person_id: Whose history to read.
        muscle: Canonical muscle name.
        today: Reference day. Defaults to today.

    Returns:
        Dict with ``last_trained`` (ISO date or None), ``sessions`` (trained
        days in the strength window) and ``exercises`` (up to 10 names with
        session counts, most frequent first).
    """
    today = today or date.today()
    trained = _sessions_by_muscle(person_id, today - timedelta(days=STRENGTH_DAYS))
    days = trained.get(muscle, set())

    counts: dict[str, int] = defaultdict(int)
    rows = (
        db.session.query(WorkoutExercise, Workout)
        .join(Workout, WorkoutExercise.workout_id == Workout.id)
        .filter(
            Workout.person_id == person_id,
            Workout.started_at >= today - timedelta(days=STRENGTH_DAYS),
        )
        .all()
    )
    for workout_exercise, _workout in rows:
        if muscle not in muscles_for_workout_exercise(workout_exercise):
            continue
        # The denormalized name is the honest label: for Technogym program
        # rows it names the actual program ("Low Row Sel: Pull"), which is
        # more useful here than a library name it was never linked to.
        label = (
            workout_exercise.exercise_name
            or (db.session.get(Exercise, workout_exercise.exercise_id).name
                if workout_exercise.exercise_id else None)
            or workout_exercise.machine
            or "Unknown exercise"
        )
        counts[label] += 1

    exercises = [
        {"name": name, "sessions": count}
        for name, count in sorted(counts.items(), key=lambda item: -item[1])[:10]
    ]

    return {
        "last_trained": max(days).isoformat() if days else None,
        "sessions": len(days),
        "exercises": exercises,
    }
