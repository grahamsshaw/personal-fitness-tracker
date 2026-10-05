"""Chart data API endpoints.

Provides data for Chart.js visualizations:
- Weight over time
- BMI over time
- Activity duration/calories over time
- Summary statistics
- Body measurement conflicts awaiting a decision
- Muscle training load (fatigue/strength) for the body map

All body measurement endpoints delegate to
:mod:`fitness_app.services.measurements`, which owns the rules about which
readings are current and which the user has chosen to ignore. These routes only
shape the result for JSON.
"""

from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request
from ..models import db, Activity, Person, Workout
from ..services import measurements as measurement_service
from ..services import muscles as muscle_service

charts_bp = Blueprint("charts", __name__)


def _series_payload(measurement_type: str) -> dict:
    """Build the JSON payload for one measurement type's chart.

    Args:
        measurement_type: e.g. ``"weight"`` or ``"bmi"``.

    Returns:
        Dict with ``labels``, ``values``, ``sources``, ``ids``, ``superseded``
        and ``include_superseded``.
    """
    include_superseded = request.args.get("include_superseded", "false").lower() == "true"
    points = measurement_service.series(
        measurement_type, include_superseded=include_superseded
    )

    return {
        "labels": [point["date"] for point in points],
        "values": [point["value"] for point in points],
        "sources": [point["source"] for point in points],
        # Full timestamp, not just the date: several readings can share a day.
        "times": [point["time"] for point in points],
        "ids": [point["id"] for point in points],
        "superseded": [point["superseded"] for point in points],
        "include_superseded": include_superseded,
    }


@charts_bp.route("/weight")
def weight_data():
    """Return weight measurements over time.

    Query args:
        include_superseded: ``true`` to also include readings the user has
            chosen to ignore, so they can be reviewed.

    When a weight goal is set, the payload carries it as ``goal`` so the
    chart can draw the target line.
    """
    payload = _series_payload("weight")
    person = Person.query.first()
    if person is not None and person.weight_goal_kg:
        payload["goal"] = person.weight_goal_kg
    return jsonify(payload)


@charts_bp.route("/bmi")
def bmi_data():
    """Return BMI measurements over time.

    Query args:
        include_superseded: ``true`` to also include ignored readings.
    """
    return jsonify(_series_payload("bmi"))


@charts_bp.route("/activities")
def activities_data():
    """Return activity data over time."""
    # Get query parameters
    days = request.args.get("days", 90, type=int)
    activity_type = request.args.get("type", "all")

    query = Activity.query

    if activity_type != "all":
        query = query.filter_by(activity_type=activity_type)

    # Filter by date range
    from_date = datetime.utcnow() - timedelta(days=days)
    query = query.filter(Activity.started_at >= from_date)

    activities = query.order_by(Activity.started_at).all()

    # Day summaries carry the day's steps/distance/calories but their ~24 h
    # "duration" is not training time — zero it so the duration chart stays
    # readable. The underlying rows are untouched.
    from ..services.training_context import is_daily_summary

    data = [{
        "date": a.started_at.strftime("%Y-%m-%d"),
        "type": a.activity_type,
        "duration": 0 if is_daily_summary(a) else (a.duration_seconds or 0),
        "calories": a.calories or 0,
        "distance": a.distance_m or 0,
    } for a in activities]

    return jsonify({
        "labels": [d["date"] for d in data],
        "durations": [d["duration"] for d in data],
        "calories": [d["calories"] for d in data],
        "distances": [d["distance"] for d in data],
        "types": [d["type"] for d in data],
    })


@charts_bp.route("/conflicts")
def conflicts_data():
    """Return body measurement conflicts that still need a decision.

    Nothing is ever superseded automatically, so this is the list of days where
    sources disagree and the user has not yet picked a value.
    """
    conflicts = measurement_service.find_conflicts()

    return jsonify({
        "conflicts": [
            {
                "measurement_type": conflict.measurement_type,
                "day": conflict.day.isoformat(),
                "spread": round(conflict.spread, 2),
                "sources": conflict.sources,
                "readings": [
                    {
                        "id": reading.id,
                        "value": reading.value,
                        "unit": reading.unit,
                        "source": reading.source,
                        "time": reading.measured_at.strftime("%H:%M"),
                    }
                    for reading in conflict.readings
                ],
            }
            for conflict in conflicts
        ],
        "count": len(conflicts),
    })


@charts_bp.route("/summary")
def summary_data():
    """Return summary statistics for dashboard."""
    # Total workouts
    total_workouts = Workout.query.count()

    # Total activities
    total_activities = Activity.query.count()

    # Total duration (minutes)
    total_duration = db.session.query(
        db.func.sum(Activity.duration_seconds)
    ).scalar() or 0

    # Total calories
    total_calories = db.session.query(
        db.func.sum(Activity.calories)
    ).scalar() or 0

    # Current weight and BMI, honouring any decisions the user has made.
    current = measurement_service.current_values()
    latest_weight = current.get("weight")
    latest_bmi = current.get("bmi")

    # Activities by type
    activity_types = db.session.query(
        Activity.activity_type,
        db.func.count(Activity.id)
    ).group_by(Activity.activity_type).all()

    # Open conflicts the user has not settled yet.
    open_conflicts = measurement_service.find_conflicts()

    return jsonify({
        "total_workouts": total_workouts,
        "total_activities": total_activities,
        "total_duration_minutes": round(total_duration / 60),
        "total_calories": round(total_calories),
        "latest_weight": latest_weight.value if latest_weight else None,
        "latest_weight_date": latest_weight.measured_at.strftime("%Y-%m-%d") if latest_weight else None,
        "latest_weight_source": latest_weight.source if latest_weight else None,
        "latest_bmi": latest_bmi.value if latest_bmi else None,
        "latest_bmi_date": latest_bmi.measured_at.strftime("%Y-%m-%d") if latest_bmi else None,
        "latest_bmi_source": latest_bmi.source if latest_bmi else None,
        "activity_types": {t: c for t, c in activity_types},
        "open_conflicts": len(open_conflicts),
    })


@charts_bp.route("/muscles/<muscle>")
def muscle_detail(muscle):
    """Return recent training for one canonical muscle.

    Used when a muscle is clicked on the body map: what trained it, when it
    was last trained, and how many sessions in the strength window.

    Returns:
        404 when ``muscle`` is not a known canonical name.
    """
    if muscle not in muscle_service.MUSCLES:
        return jsonify({"error": f"unknown muscle {muscle!r}"}), 404

    person = Person.query.first()
    if person is None:
        return jsonify({"muscle": muscle, "sessions": 0, "exercises": []})

    load = muscle_service.muscle_load(person.id)
    detail = muscle_service.muscle_history(person.id, muscle)

    return jsonify({
        "muscle": muscle,
        "fatigue": load[muscle]["fatigue"],
        "strength": load[muscle]["strength"],
        "last_trained": detail["last_trained"],
        "sessions": detail["sessions"],
        "exercises": detail["exercises"],
    })


@charts_bp.route("/muscles")
def muscle_data():
    """Return per-muscle training load for the body map.

    Query args:
        mode: ``"fatigue"`` (default) or ``"strength"`` — which view to lead
            with. Both are always included; the mode only sets ``levels``.

    Levels are 0-4 per muscle, ready to shade the map. ``neglected`` lists
    muscles with no training in the strength window, head to toe.
    """
    person = Person.query.first()
    if person is None:
        return jsonify({"levels": {}, "neglected": [], "mode": "fatigue"})

    mode = request.args.get("mode", "fatigue")
    if mode not in ("fatigue", "strength"):
        mode = "fatigue"

    load = muscle_service.muscle_load(person.id)

    return jsonify({
        "mode": mode,
        "levels": {muscle: values[mode] for muscle, values in load.items()},
        "fatigue": {muscle: values["fatigue"] for muscle, values in load.items()},
        "strength": {muscle: values["strength"] for muscle, values in load.items()},
        "neglected": muscle_service.neglected_muscles(person.id),
    })


@charts_bp.route("/exercise/<int:exercise_id>/onerm")
def exercise_onerm(exercise_id):
    """Best Epley 1RM per session for one exercise, oldest first.

    Computed from logged non-warm-up sets (reps 1-12); sessions with no
    eligible set are skipped, not zero-filled. Empty until the runner logs
    real sets — the chart draws nothing rather than a flat line.
    """
    from ..models import Exercise, Set, Workout, WorkoutExercise
    from ..services.training_context import estimate_1rm

    if db.session.get(Exercise, exercise_id) is None:
        return jsonify({"error": "unknown exercise"}), 404

    best_by_day: dict[str, float] = {}
    rows = (
        db.session.query(Set, Workout)
        .join(WorkoutExercise, Set.workout_exercise_id == WorkoutExercise.id)
        .join(Workout, WorkoutExercise.workout_id == Workout.id)
        .filter(WorkoutExercise.exercise_id == exercise_id,
                Set.is_warmup.isnot(True))
        .order_by(Workout.started_at)
        .all()
    )
    for row, workout in rows:
        estimate = estimate_1rm(row.weight_kg_actual, row.reps_actual)
        if estimate is None:
            continue
        day = workout.started_at.date().isoformat()
        best_by_day[day] = max(estimate, best_by_day.get(day, 0))

    days = sorted(best_by_day)
    return jsonify({"labels": days, "values": [best_by_day[day] for day in days]})


@charts_bp.route("/stats/overview")
def stats_overview():
    """Training stats over a window: muscle sets, balance, effort, weeks.

    Query args:
        days: window length (default 90).

    - ``muscle_sets``: finished (non-warm-up) sets per canonical muscle.
    - ``structural``: agonist/antagonist set pairs (push/pull, quads/hams,
      biceps/triceps) for the "which lift holds back the rest" view.
    - ``effort``: average RIR, share at RIR 3 or harder, rated fraction and
      the RIR 0/1/2/3/4+ distribution. RPE converts at RPE 8 == RIR 2;
      unrated sets are excluded, never zero.
    - ``weekly``: sessions and minutes per week, oldest first.
    Empty windows return zeros and empty lists, not errors — a new
    programme simply has no stats yet.
    """
    from ..models import Exercise, Person, Set, Workout, WorkoutExercise
    from ..services.muscles import muscles_for_workout_exercise

    days = request.args.get("days", 90, type=int)
    person = Person.query.first()
    if person is None:
        return jsonify({"muscle_sets": {}, "structural": [], "effort": {},
                        "weekly": []})

    start = datetime.now() - timedelta(days=days)
    sets = (
        db.session.query(Set, WorkoutExercise, Workout)
        .join(WorkoutExercise, Set.workout_exercise_id == WorkoutExercise.id)
        .join(Workout, WorkoutExercise.workout_id == Workout.id)
        .filter(Workout.person_id == person.id,
                Workout.started_at >= start,
                Set.is_warmup.isnot(True))
        .order_by(Workout.started_at)
        .all()
    )

    muscle_sets: dict[str, int] = {}
    rirs: list[float] = []
    rated = 0
    finished = 0
    weekly: dict[str, dict[str, int]] = {}
    for row, workout_exercise, workout in sets:
        if row.reps_actual:
            finished += 1
        for muscle in muscles_for_workout_exercise(workout_exercise):
            muscle_sets[muscle] = muscle_sets.get(muscle, 0) + 1
        rir = None
        if row.effort_rir is not None:
            rated += 1
            rir = float(row.effort_rir)
        elif row.effort_rpe is not None:
            rated += 1
            rir = 10.0 - float(row.effort_rpe)
        if rir is not None:
            rirs.append(rir)
        monday = (workout.started_at.date()
                  - timedelta(days=workout.started_at.weekday())).isoformat()
        week = weekly.setdefault(monday, {"sessions": set(), "minutes": 0})
        week["sessions"].add(workout.id)

    distribution = {"0": 0, "1": 0, "2": 0, "3": 0, "4+": 0}
    for rir in rirs:
        if rir <= 0.5:
            distribution["0"] += 1
        elif rir <= 1.5:
            distribution["1"] += 1
        elif rir <= 2.5:
            distribution["2"] += 1
        elif rir <= 3.5:
            distribution["3"] += 1
        else:
            distribution["4+"] += 1

    pairs = [("chest", "upper-back"), ("quadriceps", "hamstring"),
             ("biceps", "triceps")]
    structural = [{
        "pair": f"{first} vs {second}",
        "first": first,
        "second": second,
        "first_sets": muscle_sets.get(first, 0),
        "second_sets": muscle_sets.get(second, 0),
    } for first, second in pairs]

    return jsonify({
        "muscle_sets": muscle_sets,
        "structural": structural,
        "effort": {
            "avg_rir": round(sum(rirs) / len(rirs), 1) if rirs else None,
            "pct_hard": round(
                sum(1 for rir in rirs if rir <= 3.5) / len(rirs) * 100)
            if rirs else None,
            "rated": rated,
            "finished": finished,
            "distribution": distribution,
        },
        "weekly": [
            {"week": week, "sessions": len(info["sessions"])}
            for week, info in sorted(weekly.items())
        ],
    })


@charts_bp.route("/stats/exercise/<int:exercise_id>")
def stats_exercise(exercise_id):
    """Per-session best sets for one exercise, newest first (max 12).

    Each session lists its sets as weight×reps (RIR) with the session best
    flagged — the "152.5×12 (RIR 3)" view. A fuller dot means less left in
    the tank: the same weight at a lower RIR is progress the line hides.
    """
    from ..models import Exercise, Set, Workout, WorkoutExercise
    from ..services.training_context import estimate_1rm

    if db.session.get(Exercise, exercise_id) is None:
        return jsonify({"error": "unknown exercise"}), 404

    by_workout: dict[int, dict] = {}
    rows = (
        db.session.query(Set, WorkoutExercise, Workout)
        .join(WorkoutExercise, Set.workout_exercise_id == WorkoutExercise.id)
        .join(Workout, WorkoutExercise.workout_id == Workout.id)
        .filter(WorkoutExercise.exercise_id == exercise_id,
                Set.is_warmup.isnot(True))
        .order_by(Workout.started_at.desc())
        .limit(200)
        .all()
    )
    for row, workout_exercise, workout in rows:
        entry = by_workout.setdefault(workout.id, {
            "date": workout.started_at.date().isoformat(),
            "workout": workout.workout_name,
            "sets": [],
        })
        rir = None
        if row.effort_rir is not None:
            rir = float(row.effort_rir)
        elif row.effort_rpe is not None:
            rir = 10.0 - float(row.effort_rpe)
        entry["sets"].append({
            "weight": row.weight_kg_actual,
            "reps": row.reps_actual,
            "rir": rir,
            "onerm": estimate_1rm(row.weight_kg_actual, row.reps_actual),
        })

    sessions = list(by_workout.values())[:12]
    best = None
    for session in sessions:
        for entry in session["sets"]:
            if entry["onerm"] is not None and (best is None or entry["onerm"] > best):
                best = entry["onerm"]

    return jsonify({"sessions": sessions, "best": best})


@charts_bp.route("/exercise/<int:exercise_id>/effort")
def exercise_effort(exercise_id):
    """Average RIR per week for one exercise, oldest first.

    RPE sets convert at RPE 8 == RIR 2; unrated sets are excluded, never
    treated as zero effort. Empty until rated sets exist.
    """
    from datetime import date as date_cls
    from ..models import Exercise, Set, Workout, WorkoutExercise

    if db.session.get(Exercise, exercise_id) is None:
        return jsonify({"error": "unknown exercise"}), 404

    by_week: dict[str, list[float]] = {}
    rows = (
        db.session.query(Set, Workout)
        .join(WorkoutExercise, Set.workout_exercise_id == WorkoutExercise.id)
        .join(Workout, WorkoutExercise.workout_id == Workout.id)
        .filter(WorkoutExercise.exercise_id == exercise_id)
        .order_by(Workout.started_at)
        .all()
    )
    for row, workout in rows:
        rir = None
        if row.effort_rir is not None:
            rir = float(row.effort_rir)
        elif row.effort_rpe is not None:
            rir = 10.0 - float(row.effort_rpe)
        if rir is None:
            continue
        monday = workout.started_at.date() - timedelta(
            days=workout.started_at.weekday())
        by_week.setdefault(monday.isoformat(), []).append(rir)

    weeks = sorted(by_week)
    return jsonify({
        "labels": weeks,
        "values": [round(sum(values) / len(values), 1) for values in
                   (by_week[week] for week in weeks)],
    })


@charts_bp.route("/heatmap")
def activity_heatmap():
    """Training minutes per day for the last 365 days.

    Workouts and standalone activities both count (linked activities are
    not double-counted — their session is already represented by the
    workout; day summaries never count — a 1439-minute "walk" is background
    life, not training). Rendered as a GitHub-style year grid client-side.
    """
    from ..models import Activity, Workout
    from ..services.training_context import active_minutes

    person = Person.query.first()
    if person is None:
        return jsonify({"days": {}})

    start = datetime.now() - timedelta(days=365)
    minutes: dict[str, int] = {}

    linked_ids = {
        workout.activity_id
        for workout in Workout.query.filter(
            Workout.person_id == person.id, Workout.started_at >= start).all()
        if workout.activity_id
    }
    for workout in Workout.query.filter(
        Workout.person_id == person.id, Workout.started_at >= start
    ).all():
        day = workout.started_at.date().isoformat()
        minutes[day] = minutes.get(day, 0) + active_minutes(
            workout.started_at, workout.ended_at, workout.duration_seconds)

    for activity in Activity.query.filter(
        Activity.person_id == person.id, Activity.started_at >= start
    ).all():
        if activity.id in linked_ids:
            continue
        day = activity.started_at.date().isoformat()
        minutes[day] = minutes.get(day, 0) + active_minutes(
            activity.started_at, activity.ended_at, activity.duration_seconds,
            activity.source_id)

    return jsonify({"days": {day: total for day, total in minutes.items() if total > 0}})


@charts_bp.route("/measurement/<measurement_type>")
def measurement_series(measurement_type):
    """Generic body-measurement series for any type (waist, arms, …).

    Weight and BMI keep their dedicated endpoints; everything else comes
    through here so new measurement types never need a new route.
    """
    allowed = {"weight", "bmi", "body_fat", "waist", "chest", "arms",
               "hips", "thigh", "shoulders", "height"}
    if measurement_type not in allowed:
        return jsonify({"error": f"unknown measurement type {measurement_type!r}"}), 404
    return jsonify(_series_payload(measurement_type))