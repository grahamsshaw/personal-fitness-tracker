"""Plan routes: weekly routines, progression, plan sharing.

Routines are structure only — exercises, targets, days, progression rule.
Starting one copies its slots into a guided session with computed weights;
logged history always flows the other way, never back into the plan.
"""

import json
from datetime import datetime

from flask import (
    Blueprint, Response, flash, redirect, render_template, request, url_for,
)
from ..models import (
    db, Equipment, Exercise, Person, Routine, RoutineExercise, Set,
    Workout, WorkoutExercise,
)
from ..services import progression as progression_service

plan_bp = Blueprint("plan", __name__)

#: Weekday names, Monday first, matching the 0-6 day numbering.
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _routine_days(routine: Routine) -> list[int]:
    """Parse a routine's weekday list, ignoring junk.

    Args:
        routine: The routine.

    Returns:
        Sorted list of 0-6 weekday numbers.
    """
    try:
        days = json.loads(routine.days or "[]")
    except (ValueError, TypeError):
        return []
    return sorted(day for day in days if isinstance(day, int) and 0 <= day <= 6)


def _exercise_history(exercise_id: int | None, limit: int = 6) -> list[dict]:
    """Recent session summaries for progression input.

    Args:
        exercise_id: Library exercise id. None when unlinked.
        limit: How many past sessions to include.

    Returns:
        Newest-last list of ``{"weight", "reps", "target_reps"}``.
    """
    if not exercise_id:
        return []

    # Newest sets first, then regroup by workout so each past session is one
    # entry with its working weight and per-set reps.
    sets = (
        Set.query.join(WorkoutExercise)
        .join(Workout, WorkoutExercise.workout_id == Workout.id)
        .filter(WorkoutExercise.exercise_id == exercise_id,
                Set.is_warmup.isnot(True),
                Set.reps_actual.isnot(None))
        .order_by(Workout.started_at.desc(), Set.set_number)
        .limit(limit * 10)
        .all()
    )
    by_workout: dict[int, dict] = {}
    for row in sets:
        entry = by_workout.setdefault(row.workout_exercise_id, {
            "weight": row.weight_kg_actual,
            "reps": [],
            "target_reps": None,
        })
        entry["reps"].append(row.reps_actual)
        if row.weight_kg_actual:
            entry["weight"] = row.weight_kg_actual

    return list(by_workout.values())[-limit:]


@plan_bp.route("/")
def week():
    """Weekly plan grid: routine per weekday, today highlighted."""
    person = Person.query.first()
    routines = Routine.query.order_by(Routine.name).all() if person else []

    grid: dict[int, list[Routine]] = {day: [] for day in range(7)}
    for routine in routines:
        for day in _routine_days(routine):
            grid[day].append(routine)

    today = datetime.now().weekday()
    return render_template(
        "plan.html", routines=routines, grid=grid, weekdays=WEEKDAYS,
        today=today, policies=progression_service.POLICIES,
    )


@plan_bp.route("/routines/new", methods=["GET", "POST"])
def new_routine():
    """Create a routine."""
    person = Person.query.first()
    if person is None:
        flash("Set up your profile first.", "warning")
        return redirect(url_for("main.profile"))

    if request.method == "POST":
        days = [int(day) for day in request.form.getlist("days") if day.isdigit()]
        policy = request.form.get("progression_policy", "linear")
        if policy not in progression_service.POLICIES:
            policy = "linear"
        routine = Routine(
            person_id=person.id,
            name=request.form.get("name", "Routine").strip() or "Routine",
            days=json.dumps(sorted(set(day for day in days if 0 <= day <= 6))),
            progression_policy=policy,
            increment_kg=float(request.form.get("increment_kg") or 2.5),
            notes=request.form.get("notes"),
        )
        db.session.add(routine)
        db.session.commit()
        flash(f"Routine '{routine.name}' created — add its exercises next.",
              "success")
        return redirect(url_for("plan.view_routine", routine_id=routine.id))

    return render_template("routine_form.html", routine=None,
                           policies=progression_service.POLICIES)


@plan_bp.route("/routines/<int:routine_id>")
def view_routine(routine_id):
    """Routine detail: slots, computed next targets, weekday assignment."""
    routine = Routine.query.get_or_404(routine_id)
    exercises = Exercise.query.order_by(Exercise.name).limit(500).all()

    targets = {}
    for slot in routine.exercises:
        history = _exercise_history(slot.exercise_id)
        targets[slot.id] = progression_service.next_target(
            routine.progression_policy, history,
            increment_kg=routine.increment_kg or 2.5,
            default_weight=slot.target_weight_kg or 20.0,
            rep_min=slot.rep_min or 8,
            rep_max=slot.rep_max or 12,
        )

    return render_template(
        "routine_detail.html", routine=routine, exercises=exercises,
        targets=targets, days=_routine_days(routine), weekdays=WEEKDAYS,
    )


@plan_bp.route("/routines/<int:routine_id>/exercises", methods=["POST"])
def add_slot(routine_id):
    """Add an exercise slot to a routine."""
    routine = Routine.query.get_or_404(routine_id)
    exercise_id = request.form.get("exercise_id", type=int)
    exercise = db.session.get(Exercise, exercise_id) if exercise_id else None

    order = max([slot.exercise_order for slot in routine.exercises] + [-1]) + 1
    db.session.add(RoutineExercise(
        routine_id=routine.id,
        exercise_id=exercise.id if exercise else None,
        exercise_name=exercise.name if exercise
        else request.form.get("exercise_name", "Exercise"),
        target_sets=request.form.get("target_sets", type=int) or 3,
        target_reps=request.form.get("target_reps", type=int),
        rep_min=request.form.get("rep_min", type=int),
        rep_max=request.form.get("rep_max", type=int),
        target_weight_kg=request.form.get("target_weight_kg", type=float),
        mode=request.form.get("mode", "reps")
        if request.form.get("mode") in ("reps", "time", "cardio") else "reps",
        exercise_order=order,
    ))
    db.session.commit()
    flash("Exercise added to the routine.", "success")
    return redirect(url_for("plan.view_routine", routine_id=routine.id))


@plan_bp.route("/routines/<int:routine_id>/exercises/<int:slot_id>/delete",
               methods=["POST"])
def delete_slot(routine_id, slot_id):
    """Remove an exercise slot from a routine."""
    slot = RoutineExercise.query.filter_by(
        id=slot_id, routine_id=routine_id).first_or_404()
    db.session.delete(slot)
    db.session.commit()
    flash("Exercise removed.", "success")
    return redirect(url_for("plan.view_routine", routine_id=routine.id))


@plan_bp.route("/routines/<int:routine_id>/move", methods=["POST"])
def move_routine(routine_id):
    """Change which weekdays a routine runs on.

    Rescheduling never touches the slots — moving a session to another day
    is not editing the plan.
    """
    routine = Routine.query.get_or_404(routine_id)
    days = [int(day) for day in request.form.getlist("days") if day.isdigit()]
    routine.days = json.dumps(sorted(set(day for day in days if 0 <= day <= 6)))
    db.session.commit()
    flash("Schedule updated — the routine itself is untouched.", "success")
    return redirect(url_for("plan.view_routine", routine_id=routine.id))


@plan_bp.route("/routines/<int:routine_id>/delete", methods=["POST"])
def delete_routine(routine_id):
    """Delete a routine and its slots. Logged history is unaffected."""
    routine = Routine.query.get_or_404(routine_id)
    db.session.delete(routine)
    db.session.commit()
    flash("Routine deleted. Logged workouts are unaffected.", "success")
    return redirect(url_for("plan.week"))


@plan_bp.route("/routines/<int:routine_id>/start", methods=["POST"])
def start_routine(routine_id):
    """Start a guided session from a routine, with computed targets.

    Each slot becomes a session exercise carrying the progression engine's
    weight and reps as targets. The runner shows them as placeholders; what
    gets logged is what happened, and the plan never changes.
    """
    routine = Routine.query.get_or_404(routine_id)
    person = Person.query.first()
    if person is None:
        flash("Set up your profile first.", "warning")
        return redirect(url_for("main.profile"))

    if not routine.exercises:
        flash("Add exercises to the routine first.", "warning")
        return redirect(url_for("plan.view_routine", routine_id=routine.id))

    workout = Workout(
        person_id=person.id,
        workout_name=routine.name,
        started_at=datetime.now(),
        source="manual",
        notes=f"From routine '{routine.name}' ({routine.progression_policy}).",
    )
    db.session.add(workout)
    db.session.flush()

    for slot in sorted(routine.exercises, key=lambda s: s.exercise_order):
        history = _exercise_history(slot.exercise_id)
        target = progression_service.next_target(
            routine.progression_policy, history,
            increment_kg=routine.increment_kg or 2.5,
            default_weight=slot.target_weight_kg or 20.0,
            rep_min=slot.rep_min or 8,
            rep_max=slot.rep_max or 12,
        )
        db.session.add(WorkoutExercise(
            workout_id=workout.id,
            exercise_id=slot.exercise_id,
            equipment_id=slot.equipment_id,
            exercise_name=slot.exercise_name,
            mode=slot.mode or "reps",
            exercise_order=slot.exercise_order,
            target_weight_kg=target["weight"],
            target_reps=target["reps"],
            source="manual",
        ))

    db.session.commit()
    flash(f"Session started from '{routine.name}'. Targets are computed — "
          f"log what you actually do.", "success")
    return redirect(url_for("workouts.run_session", workout_id=workout.id))


@plan_bp.route("/export")
def export_plan():
    """Download routines as a merge-safe JSON file (no workouts, no weigh-ins)."""
    routines = Routine.query.order_by(Routine.name).all()
    payload = {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "routines": [
            {
                "name": routine.name,
                "days": _routine_days(routine),
                "progression_policy": routine.progression_policy,
                "increment_kg": routine.increment_kg,
                "notes": routine.notes,
                "exercises": [
                    {
                        "exercise_name": slot.exercise_name,
                        "target_sets": slot.target_sets,
                        "target_reps": slot.target_reps,
                        "rep_min": slot.rep_min,
                        "rep_max": slot.rep_max,
                        "target_weight_kg": slot.target_weight_kg,
                        "mode": slot.mode,
                        "exercise_order": slot.exercise_order,
                    }
                    for slot in sorted(routine.exercises,
                                       key=lambda s: s.exercise_order)
                ],
            }
            for routine in routines
        ],
    }
    return Response(
        json.dumps(payload, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=plan.json"},
    )


@plan_bp.route("/import", methods=["POST"])
def import_plan():
    """Import a plan file, merging by routine name.

    Routines whose names already exist are skipped, never overwritten;
    exercises are matched to the library by name where possible. Nothing in
    the existing plan is modified by an import.
    """
    person = Person.query.first()
    if person is None:
        flash("Set up your profile first.", "warning")
        return redirect(url_for("main.profile"))

    file = request.files.get("plan_file")
    if not file:
        flash("No file uploaded.", "warning")
        return redirect(url_for("plan.week"))

    try:
        payload = json.load(file.stream)
    except (ValueError, TypeError):
        flash("That file is not valid JSON.", "error")
        return redirect(url_for("plan.week"))

    existing_names = {routine.name for routine in Routine.query.all()}
    imported, skipped = 0, 0

    for item in payload.get("routines", []):
        name = (item.get("name") or "").strip()
        if not name or name in existing_names:
            skipped += 1
            continue
        routine = Routine(
            person_id=person.id,
            name=name,
            days=json.dumps([day for day in item.get("days", [])
                             if isinstance(day, int) and 0 <= day <= 6]),
            progression_policy=item.get("progression_policy", "linear")
            if item.get("progression_policy") in progression_service.POLICIES
            else "linear",
            increment_kg=item.get("increment_kg") or 2.5,
            notes=item.get("notes"),
        )
        db.session.add(routine)
        db.session.flush()

        for slot in item.get("exercises", []):
            exercise = Exercise.query.filter(
                db.func.lower(Exercise.name) == (slot.get("exercise_name") or "").lower()
            ).first()
            db.session.add(RoutineExercise(
                routine_id=routine.id,
                exercise_id=exercise.id if exercise else None,
                exercise_name=slot.get("exercise_name") or "Exercise",
                target_sets=slot.get("target_sets") or 3,
                target_reps=slot.get("target_reps"),
                rep_min=slot.get("rep_min"),
                rep_max=slot.get("rep_max"),
                target_weight_kg=slot.get("target_weight_kg"),
                mode=slot.get("mode", "reps")
                if slot.get("mode") in ("reps", "time", "cardio") else "reps",
                exercise_order=slot.get("exercise_order") or 0,
            ))
        existing_names.add(name)
        imported += 1

    db.session.commit()
    flash(f"Imported {imported} routine(s), skipped {skipped} "
          f"(already present). Nothing existing was changed.", "success")
    return redirect(url_for("plan.week"))
