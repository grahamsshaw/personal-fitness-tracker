"""Workout routes: create, view, manage workouts."""

import json
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..models import db, Workout, WorkoutExercise, Set, Exercise, Equipment, EquipmentExercise, Person

workouts_bp = Blueprint("workouts", __name__)


def autocomplete_options(rows) -> list[dict]:
    """Flatten Exercise/Equipment rows into JSON-safe dicts.

    ``workout_form.html`` pipes these straight into Jinja's ``tojson`` filter to
    build an autocomplete ``<datalist>``. SQLAlchemy model instances are not JSON
    serialisable, so handing them over directly raises
    ``TypeError: Object of type Exercise is not JSON serializable`` and the page
    fails with a 500.

    Only the fields the page needs are included: ``name`` populates the datalist,
    and ``id`` is the counterpart to the ``exercise_id`` / ``equipment_id`` hidden
    inputs the form already carries.

    Args:
        rows: Model instances, already ordered as the caller wants them.

    Returns:
        List of ``{"id": ..., "name": ...}`` dicts, safe to pass to ``tojson``.
    """
    return [{"id": row.id, "name": row.name} for row in rows]


@workouts_bp.route("/")
def list_workouts():
    """List all workouts."""
    page = request.args.get("page", 1, type=int)
    workouts = Workout.query.order_by(Workout.started_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    return render_template("workout_list.html", workouts=workouts)


@workouts_bp.route("/new", methods=["GET", "POST"])
def new_workout():
    """Create a new workout."""
    exercises = Exercise.query.order_by(Exercise.name).all()
    equipment = Equipment.query.order_by(Equipment.name).all()
    
    if request.method == "POST":
        # Create workout
        started_at_str = request.form.get("started_at")
        started_at = datetime.fromisoformat(started_at_str) if started_at_str else datetime.utcnow()
        
        ended_at_str = request.form.get("ended_at")
        ended_at = datetime.fromisoformat(ended_at_str) if ended_at_str else None
        
        workout = Workout(
            person_id=1,  # Default person
            workout_name=request.form.get("workout_name", "Workout"),
            started_at=started_at,
            ended_at=ended_at,
            notes=request.form.get("notes"),
        )
        db.session.add(workout)
        db.session.flush()
        
        # Get exercises from form
        exercise_ids = request.form.getlist("exercise_id")
        exercise_names = request.form.getlist("exercise_name")
        equipment_ids = request.form.getlist("equipment_id")
        equipment_names = request.form.getlist("equipment_name")
        
        for i in range(len(exercise_names)):
            if not exercise_names[i]:
                continue
            
            we = WorkoutExercise(
                workout_id=workout.id,
                exercise_id=int(exercise_ids[i]) if exercise_ids[i] else None,
                equipment_id=int(equipment_ids[i]) if equipment_ids[i] else None,
                exercise_name=exercise_names[i],
                equipment_name=equipment_names[i] if i < len(equipment_names) else None,
                exercise_order=i,
            )
            db.session.add(we)
            db.session.flush()
            
            # Get sets for this exercise
            set_numbers = request.form.getlist(f"set_{i}_number")
            set_reps = request.form.getlist(f"set_{i}_reps")
            set_weights = request.form.getlist(f"set_{i}_weight")
            
            for j in range(len(set_reps)):
                if not set_reps[j]:
                    continue
                s = Set(
                    workout_exercise_id=we.id,
                    set_number=j + 1,
                    reps_actual=int(set_reps[j]) if set_reps[j] else None,
                    weight_kg_actual=float(set_weights[j]) if set_weights[j] else None,
                )
                db.session.add(s)
        
        db.session.commit()
        flash("Workout created successfully!", "success")
        return redirect(url_for("main.workout_detail", workout_id=workout.id))
    
    return render_template(
        "workout_form.html",
        exercises=autocomplete_options(exercises),
        equipment=autocomplete_options(equipment),
        today=datetime.now().strftime("%Y-%m-%dT%H:%M"),
    )


@workouts_bp.route("/<int:workout_id>")
def view_workout(workout_id):
    """View a single workout."""
    from ..services import sessions as session_service

    workout = Workout.query.get_or_404(workout_id)
    return render_template(
        "workout_detail.html",
        workout=workout,
        linked_activities=session_service.linked_activities(workout),
        link_candidates=session_service.link_candidates(workout),
    )


@workouts_bp.route("/<int:workout_id>/edit", methods=["GET", "POST"])
def edit_workout(workout_id):
    """Edit a workout."""
    workout = Workout.query.get_or_404(workout_id)
    exercises = Exercise.query.order_by(Exercise.name).all()
    equipment = Equipment.query.order_by(Equipment.name).all()
    
    if request.method == "POST":
        workout.workout_name = request.form.get("workout_name", workout.workout_name)
        workout.notes = request.form.get("notes", workout.notes)
        
        started_at_str = request.form.get("started_at")
        if started_at_str:
            workout.started_at = datetime.fromisoformat(started_at_str)
        
        ended_at_str = request.form.get("ended_at")
        if ended_at_str:
            workout.ended_at = datetime.fromisoformat(ended_at_str)
        
        db.session.commit()
        flash("Workout updated successfully!", "success")
        return redirect(url_for("main.workout_detail", workout_id=workout.id))
    
    return render_template("workout_edit.html", workout=workout, exercises=exercises, equipment=equipment)


@workouts_bp.route("/<int:workout_id>/delete", methods=["POST"])
def delete_workout(workout_id):
    """Delete a workout."""
    workout = Workout.query.get_or_404(workout_id)
    
    # Delete related sets and exercises
    for we in workout.exercises:
        Set.query.filter_by(workout_exercise_id=we.id).delete()
        db.session.delete(we)
    
    db.session.delete(workout)
    db.session.commit()
    flash("Workout deleted successfully!", "success")
    return redirect(url_for("main.history"))


@workouts_bp.route("/<int:workout_id>/save-as-routine", methods=["POST"])
def save_as_routine(workout_id):
    """Save a logged workout's exercises as a new routine.

    Slot targets seed from each exercise's best logged set (weight and
    reps); cardio slots seed from duration. The routine starts unscheduled
    so it can be placed deliberately, and progression starts at linear.
    History is untouched — this reads the workout, never moves it.
    """
    from ..models import Routine, RoutineExercise

    workout = Workout.query.get_or_404(workout_id)
    person = Person.query.first()
    if person is None:
        flash("Set up your profile first.", "warning")
        return redirect(url_for("main.profile"))

    base_name = workout.workout_name or "Workout"
    name = base_name
    taken = {routine.name for routine in Routine.query.all()}
    suffix = 2
    while name in taken:
        name = f"{base_name} ({suffix})"
        suffix += 1

    routine = Routine(
        person_id=person.id, name=name, days="[]",
        progression_policy="linear", increment_kg=2.5,
        notes=f"Saved from session on {workout.started_at.date().isoformat()}.",
    )
    db.session.add(routine)
    db.session.flush()

    for order, workout_exercise in enumerate(
        sorted(workout.exercises, key=lambda we: we.exercise_order)
    ):
        best_weight = None
        best_reps = None
        best_duration = None
        for logged_set in workout_exercise.sets:
            if logged_set.is_warmup:
                continue
            if (logged_set.weight_kg_actual is not None and
                    (best_weight is None or logged_set.weight_kg_actual > best_weight)):
                best_weight = logged_set.weight_kg_actual
                best_reps = logged_set.reps_actual
            if logged_set.duration_seconds and (
                    best_duration is None or logged_set.duration_seconds > best_duration):
                best_duration = logged_set.duration_seconds
        db.session.add(RoutineExercise(
            routine_id=routine.id,
            exercise_id=workout_exercise.exercise_id,
            equipment_id=workout_exercise.equipment_id,
            exercise_name=workout_exercise.exercise_name or "Exercise",
            target_sets=max(1, len([s for s in workout_exercise.sets
                                    if not s.is_warmup]) or 3),
            target_reps=best_reps,
            target_weight_kg=best_weight,
            target_duration_seconds=best_duration,
            mode=workout_exercise.mode or "reps",
            exercise_order=order,
        ))

    db.session.commit()
    flash(f"Saved as routine '{name}' — place it on the plan.", "success")
    return redirect(url_for("plan.view_routine", routine_id=routine.id))


@workouts_bp.route("/<int:workout_id>/link-technogym", methods=["POST"])
def link_technogym(workout_id):
    """Attach overlapping Technogym records to a hand-logged session.

    For the gym-plus-app workflow: weights logged here, cardio captured by
    Technogym's machines. Runs the same conservative rule the importer uses,
    on demand — for records that arrived before the session was logged, or
    were skipped for any reason. Idempotent: already-linked records are
    skipped, so pressing it twice changes nothing.
    """
    from ..services import sessions as session_service

    workout = Workout.query.get_or_404(workout_id)
    candidates = session_service.link_candidates(workout)
    linked = sum(
        session_service.link_activity_to_workout(activity, workout)
        for activity in candidates
    )
    db.session.commit()

    if linked:
        flash(f"Attached {linked} Technogym record(s) to this session.",
              "success")
    else:
        flash("No unlinked Technogym records overlap this session.", "info")
    return redirect(url_for("main.workout_detail", workout_id=workout.id))


# ===================================================================
# Guided workout runner
# ===================================================================

def _last_performance(exercise_id: int | None) -> dict:
    """Most recent logged values for an exercise, for pre-filling.

    Args:
        exercise_id: Library exercise id, if the row is linked to one.

    Returns:
        Dict with weight/reps/duration/distance from the newest prior set,
        plus the best Epley 1RM on record. All None when never logged.
    """
    from ..services.training_context import estimate_1rm

    if not exercise_id:
        return {"weight": None, "reps": None, "duration": None,
                "distance": None, "best_1rm": None}

    # Newest non-warm-up set first: pre-logged warm-ups (from routine
    # warm-up generation) must never masquerade as last performance.
    last = (
        Set.query.join(WorkoutExercise)
        .filter(WorkoutExercise.exercise_id == exercise_id,
                Set.is_warmup.isnot(True))
        .order_by(Set.id.desc())
        .first()
    )
    if last is None:
        last = (
            Set.query.join(WorkoutExercise)
            .filter(WorkoutExercise.exercise_id == exercise_id)
            .order_by(Set.id.desc())
            .first()
        )
    best = None
    for row in (
        Set.query.join(WorkoutExercise)
        .filter(WorkoutExercise.exercise_id == exercise_id,
                Set.is_warmup.isnot(True))
        .all()
    ):
        candidate = estimate_1rm(row.weight_kg_actual, row.reps_actual)
        if candidate is not None and (best is None or candidate > best):
            best = candidate

    return {
        "weight": last.weight_kg_actual if last else None,
        "reps": last.reps_actual if last else None,
        "duration": last.duration_seconds if last else None,
        "distance": last.distance_m if last else None,
        "best_1rm": best,
    }


@workouts_bp.route("/run", methods=["GET", "POST"])
def run_setup():
    """Pick exercises and start a guided session.

    The setup page leads with cross-source awareness — this week's totals by
    source, recent sessions, hottest muscles — so the session is planned
    against everything already done, not just gym history.
    """
    from ..services import training_context

    person = Person.query.first()
    snapshot = training_context.snapshot(person.id if person else None)

    if request.method == "POST":
        if person is None:
            flash("Set up your profile first.", "warning")
            return redirect(url_for("main.profile"))

        workout = Workout(
            person_id=person.id,
            workout_name=request.form.get("workout_name", "Workout").strip()
            or "Workout",
            started_at=datetime.now(),
            source="manual",
        )
        db.session.add(workout)
        db.session.flush()

        order = 0
        for key in request.form.getlist("exercise_id"):
            if not key or not key.isdigit():
                continue
            exercise = db.session.get(Exercise, int(key))
            mode = request.form.get(f"mode_{key}", "reps")
            if mode not in ("reps", "time", "cardio"):
                mode = "reps"
            db.session.add(WorkoutExercise(
                workout_id=workout.id,
                exercise_id=exercise.id if exercise else None,
                exercise_name=exercise.name if exercise else key,
                mode=mode,
                exercise_order=order,
                source="manual",
            ))
            order += 1

        if order == 0:
            db.session.rollback()
            flash("Pick at least one exercise to start.", "warning")
            return redirect(url_for("workouts.run_setup"))

        db.session.commit()
        return redirect(url_for("workouts.run_session", workout_id=workout.id))

    query = (request.args.get("q") or "").strip()
    equipment_id = request.args.get("equipment_id", type=int)
    pool = Exercise.query
    if query:
        pool = pool.filter(Exercise.name.ilike(f"%{query}%"))
    if equipment_id:
        pool = pool.join(
            EquipmentExercise,
            EquipmentExercise.exercise_id == Exercise.id,
        ).filter(EquipmentExercise.equipment_id == equipment_id)
    exercises = pool.order_by(Exercise.name).limit(100).all()
    equipment = Equipment.query.order_by(Equipment.name).all()

    return render_template(
        "run_setup.html",
        exercises=exercises,
        equipment=equipment,
        query=query,
        equipment_id=equipment_id,
        snapshot=snapshot,
    )


@workouts_bp.route("/run/<int:workout_id>")
def run_session(workout_id):
    """The guided session page: log sets exercise by exercise."""
    workout = Workout.query.get_or_404(workout_id)
    if workout.ended_at is not None:
        flash("That session is already finished.", "info")
        return redirect(url_for("main.workout_detail", workout_id=workout.id))

    performed = {
        we.exercise_id: _last_performance(we.exercise_id)
        for we in workout.exercises
    }
    plans = {we.id: _intensifier_plan(we) for we in workout.exercises}
    return render_template(
        "run_session.html", workout=workout, performed=performed, plans=plans
    )


def _intensifier_plan(we) -> dict | None:
    """Parse an exercise's intensifier plan with suggested weights.

    Args:
        we: The session exercise.

    Returns:
        Dict with type/count/pct (drops) or total_reps/rest_sec (bursts)
        plus suggested drop weights chained off the target or last weight.
        None when no intensifier is planned.
    """
    if not we.intensifier:
        return None
    try:
        plan = json.loads(we.intensifier)
    except (ValueError, TypeError):
        return None
    if not isinstance(plan, dict) or plan.get("type") not in ("dropset", "restpause"):
        return None

    if plan["type"] == "dropset":
        base = we.target_weight_kg
        if base is None:
            last = _last_performance(we.exercise_id)
            base = last.get("weight")
        plan = dict(plan)
        plan["suggested_drops"] = []
        if base:
            weight = float(base)
            pct = float(plan.get("pct") or 20.0)
            for _ in range(int(plan.get("count") or 1)):
                weight = round(weight * (1 - pct / 100) * 2) / 2
                plan["suggested_drops"].append(weight)
    return plan


@workouts_bp.route("/run/<int:workout_id>/sets", methods=["POST"])
def run_add_set(workout_id):
    """Log one set inside a guided session, checking for a PR."""
    from ..services.training_context import estimate_1rm

    workout = Workout.query.get_or_404(workout_id)
    we = db.session.get(WorkoutExercise, request.form.get("we_id", type=int))
    if we is None or we.workout_id != workout.id:
        flash("Exercise not part of this session.", "error")
        return redirect(url_for("workouts.run_session", workout_id=workout.id))

    def number(raw, kind=float):
        try:
            return kind(raw) if raw not in (None, "") else None
        except (TypeError, ValueError):
            return None

    effort_scale = request.form.get("effort_scale", "rir")
    effort_value = number(request.form.get("effort"), int)

    # Drop/burst sub-rows ride inside the set as JSON extras. Drops are
    # extra work on top of the main set; burst reps sum to the row's own
    # total (plus any main reps typed, which seed the running total).
    drops = []
    index = 0
    while True:
        drop_weight = number(request.form.get(f"drop_weight_{index}"))
        drop_reps = number(request.form.get(f"drop_reps_{index}"), int)
        if drop_weight is None and drop_reps is None:
            break
        drops.append({"weight_kg": drop_weight, "reps": drop_reps})
        index += 1
    bursts = []
    index = 0
    while True:
        burst_reps = number(request.form.get(f"burst_reps_{index}"), int)
        if burst_reps is None:
            break
        bursts.append({"reps": burst_reps, "rest_sec": 15})
        index += 1

    reps = number(request.form.get("reps"), int)
    set_type = request.form.get("set_type", "straight")
    if set_type not in ("straight", "dropset", "restpause"):
        set_type = "straight"
    if drops:
        set_type = "dropset"
    extras = None
    if drops:
        extras = json.dumps({"drops": drops})
    elif bursts:
        total = (reps or 0) + sum(burst["reps"] for burst in bursts)
        extras = json.dumps({"clusters": bursts})
        reps = total
        set_type = "restpause"

    new_set = Set(
        workout_exercise_id=we.id,
        set_number=len(we.sets) + 1,
        reps_actual=reps,
        weight_kg_actual=number(request.form.get("weight")),
        duration_seconds=number(request.form.get("duration"), int),
        distance_m=number(request.form.get("distance")),
        effort_rir=effort_value if effort_scale == "rir" else None,
        effort_rpe=float(effort_value) if effort_scale == "rpe"
        and effort_value is not None else None,
        set_type=set_type,
        extras=extras,
        is_warmup=bool(request.form.get("is_warmup")),
        source="manual",
    )
    db.session.add(new_set)
    db.session.flush()

    # Personal record: exceeds the best Epley 1RM on record for this
    # exercise, warm-ups excluded. Only meaningful for weighted reps sets.
    is_pr = False
    if (we.exercise_id and not new_set.is_warmup
            and new_set.weight_kg_actual and new_set.reps_actual):
        current = estimate_1rm(new_set.weight_kg_actual, new_set.reps_actual)
        previous_best = None
        for row in (
            Set.query.join(WorkoutExercise)
            .filter(WorkoutExercise.exercise_id == we.exercise_id,
                    Set.id != new_set.id,
                    Set.is_warmup.isnot(True))
            .all()
        ):
            candidate = estimate_1rm(row.weight_kg_actual, row.reps_actual)
            if candidate is not None and (
                    previous_best is None or candidate > previous_best):
                previous_best = candidate
        is_pr = (current is not None
                 and (previous_best is None or current > previous_best))

    db.session.commit()
    if is_pr:
        flash(f"PR! New best for {we.exercise_name}.", "success")
    return redirect(url_for("workouts.run_session", workout_id=workout.id))


@workouts_bp.route("/run/<int:workout_id>/superset", methods=["POST"])
def run_link_superset(workout_id):
    """Link an exercise with the previous one as a superset pair.

    Consecutive exercises sharing a group run back-to-back with rest only
    after the group. Linking twice extends the group; there is no unlink —
    delete and re-add the exercise to undo, which keeps the rule obvious.
    """
    workout = Workout.query.get_or_404(workout_id)
    ordered = sorted(workout.exercises, key=lambda we: we.exercise_order)
    target_id = request.form.get("we_id", type=int)
    target = next((we for we in ordered if we.id == target_id), None)
    if target is None or target == ordered[0]:
        flash("Supersets need an exercise with a predecessor.", "warning")
        return redirect(url_for("workouts.run_session", workout_id=workout.id))

    previous = ordered[ordered.index(target) - 1]
    group = previous.superset_group
    if group is None:
        group = max(
            [we.superset_group or 0 for we in ordered]
        ) + 1
        previous.superset_group = group
    target.superset_group = group
    db.session.commit()
    flash(f"Superset: {previous.exercise_name} + {target.exercise_name}. "
          f"Rest after the pair.", "success")
    return redirect(url_for("workouts.run_session", workout_id=workout.id))


@workouts_bp.route("/run/<int:workout_id>/finish", methods=["POST"])
def run_finish(workout_id):
    """Finish a guided session, stamping duration from its start."""
    workout = Workout.query.get_or_404(workout_id)
    if workout.ended_at is None:
        workout.ended_at = datetime.now()
        workout.duration_seconds = int(
            (workout.ended_at - workout.started_at).total_seconds()
        )
        db.session.commit()
        flash("Session finished — nice work.", "success")
    return redirect(url_for("main.workout_detail", workout_id=workout.id))
