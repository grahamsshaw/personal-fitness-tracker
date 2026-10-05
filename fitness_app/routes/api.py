"""REST API routes."""

from datetime import datetime
from flask import Blueprint, request, jsonify, url_for
from ..models import db, Person, Activity, Workout, WorkoutExercise, Set, Exercise, Equipment, BodyMeasurement
from ..services import measurements as measurement_service

api_bp = Blueprint("api", __name__)


@api_bp.route("/exercises")
def list_exercises():
    """List exercises, optionally filtered for the picker.

    Query args (all optional, combined with AND):
        q: case-insensitive name substring.
        body_part: exact dataset body part (e.g. ``upper legs``).
        equipment: exact dataset equipment label (e.g. ``dumbbell``).
        muscle: free-text muscle, normalised to canonical first
            (``quads`` matches quadriceps work). ``full_body`` is special:
            exercises involving 3+ distinct muscles.

    Each entry carries ``muscle_count`` (target + secondary distinct
    canonical muscles) so clients can offer the full-body tab without a
    second request.
    """
    from ..services.muscles import muscles_for_exercise

    query_text = (request.args.get("q") or "").strip()
    body_part = (request.args.get("body_part") or "").strip().lower()
    equipment = (request.args.get("equipment") or "").strip().lower()
    muscle = (request.args.get("muscle") or "").strip()

    pool = Exercise.query
    if query_text:
        pool = pool.filter(Exercise.name.ilike(f"%{query_text}%"))
    if body_part:
        pool = pool.filter(db.func.lower(Exercise.body_part) == body_part)
    if equipment:
        pool = pool.filter(db.func.lower(Exercise.equipment_label) == equipment)
    exercises = pool.order_by(Exercise.name).limit(500).all()

    entries = []
    for exercise in exercises:
        muscles = muscles_for_exercise(exercise)
        entries.append({
            "exercise": exercise,
            "muscles": muscles,
        })

    if muscle:
        from ..services.muscles import normalize_muscle
        if muscle.lower() == "full_body":
            entries = [entry for entry in entries
                       if len(entry["muscles"]) >= 3]
        else:
            canonical = normalize_muscle(muscle)
            entries = ([entry for entry in entries
                        if canonical in entry["muscles"]]
                       if canonical else [])

    return jsonify([{
        "id": entry["exercise"].id,
        "name": entry["exercise"].name,
        "category": entry["exercise"].category,
        "muscle_group": entry["exercise"].muscle_group,
        "is_cardio": entry["exercise"].is_cardio,
        "body_part": entry["exercise"].body_part,
        "equipment_label": entry["exercise"].equipment_label,
        "target_muscle": entry["exercise"].target_muscle,
        "muscle_count": len(entry["muscles"]),
    } for entry in entries])


@api_bp.route("/exercise-facets")
def exercise_facets():
    """Body-part and equipment tabs for the picker, with counts.

    Only library rows (with dataset metadata) feed the counts — the
    hand-entered Technogym program rows have no body part and would blur
    every tab.
    """
    rows = Exercise.query.filter(
        Exercise.body_part.isnot(None)).all()
    body_parts: dict[str, int] = {}
    equipment: dict[str, int] = {}
    for row in rows:
        if row.body_part:
            key = row.body_part.strip().lower()
            body_parts[key] = body_parts.get(key, 0) + 1
        if row.equipment_label:
            key = row.equipment_label.strip().lower()
            equipment[key] = equipment.get(key, 0) + 1

    return jsonify({
        "body_parts": sorted(body_parts.items()),
        "equipment": sorted(equipment.items(), key=lambda item: -item[1]),
    })


@api_bp.route("/exercises", methods=["POST"])
def create_exercise():
    """Create a new exercise."""
    data = request.get_json() or request.form
    exercise = Exercise(
        name=data.get("name"),
        category=data.get("category", "strength"),
        muscle_group=data.get("muscle_group"),
        is_cardio=data.get("is_cardio", False),
    )
    db.session.add(exercise)
    db.session.commit()
    return jsonify({"id": exercise.id, "name": exercise.name}), 201


@api_bp.route("/equipment")
def list_equipment():
    """List all equipment."""
    equipment = Equipment.query.order_by(Equipment.name).all()
    return jsonify([{
        "id": e.id,
        "name": e.name,
        "manufacturer": e.manufacturer,
        "model": e.model,
        "category": e.category,
        "muscle_group": e.muscle_group,
    } for e in equipment])


@api_bp.route("/equipment", methods=["POST"])
def create_equipment():
    """Create new equipment."""
    data = request.get_json() or request.form
    equipment = Equipment(
        name=data.get("name"),
        manufacturer=data.get("manufacturer"),
        model=data.get("model"),
        category=data.get("category"),
        muscle_group=data.get("muscle_group"),
        gym_location=data.get("gym_location"),
        qr_code=data.get("qr_code"),
        qr_url=data.get("qr_url"),
        notes=data.get("notes"),
    )
    db.session.add(equipment)
    db.session.commit()
    return jsonify({"id": equipment.id, "name": equipment.name}), 201


@api_bp.route("/workouts")
def list_workouts():
    """List workouts."""
    workouts = Workout.query.order_by(Workout.started_at.desc()).all()
    return jsonify([{
        "id": w.id,
        "workout_name": w.workout_name,
        "started_at": w.started_at.isoformat() if w.started_at else None,
        "ended_at": w.ended_at.isoformat() if w.ended_at else None,
        "duration_seconds": w.duration_seconds,
        "total_moves": w.total_moves,
        "exercise_count": len(w.exercises),
    } for w in workouts])


@api_bp.route("/workouts/<int:workout_id>")
def get_workout(workout_id):
    """Get a single workout with exercises and sets."""
    workout = Workout.query.get_or_404(workout_id)
    exercises = []
    for we in workout.exercises:
        exercises.append({
            "id": we.id,
            "exercise_name": we.exercise_name,
            "equipment_name": we.equipment_name,
            "machine": we.machine,
            "resistance_type": we.resistance_type,
            "duration_seconds": we.duration_seconds,
            "calories": we.calories,
            "moves": we.moves,
            "compliance": we.compliance,
            "total_weight_kg": we.total_weight_kg,
            "sets": [{
                "set_number": s.set_number,
                "reps_target": s.reps_target,
                "reps_actual": s.reps_actual,
                "weight_kg_target": s.weight_kg_target,
                "weight_kg_actual": s.weight_kg_actual,
            } for s in we.sets],
        })
    return jsonify({
        "id": workout.id,
        "workout_name": workout.workout_name,
        "started_at": workout.started_at.isoformat() if workout.started_at else None,
        "ended_at": workout.ended_at.isoformat() if workout.ended_at else None,
        "duration_seconds": workout.duration_seconds,
        "total_moves": workout.total_moves,
        "notes": workout.notes,
        "exercises": exercises,
    })


@api_bp.route("/workouts", methods=["POST"])
def create_workout():
    """Create a new workout."""
    data = request.get_json() or request.form
    
    # Parse dates
    started_at = datetime.fromisoformat(data.get("started_at")) if data.get("started_at") else datetime.utcnow()
    ended_at = datetime.fromisoformat(data.get("ended_at")) if data.get("ended_at") else None
    
    workout = Workout(
        person_id=data.get("person_id", 1),
        workout_name=data.get("workout_name", "Workout"),
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=data.get("duration_seconds"),
        total_moves=data.get("total_moves"),
        notes=data.get("notes"),
        source=data.get("source", "manual"),
        source_id=data.get("source_id"),
    )
    db.session.add(workout)
    db.session.commit()
    
    # Add exercises if provided
    exercises_data = data.get("exercises", [])
    for i, ex_data in enumerate(exercises_data):
        we = WorkoutExercise(
            workout_id=workout.id,
            exercise_id=ex_data.get("exercise_id"),
            equipment_id=ex_data.get("equipment_id"),
            exercise_name=ex_data.get("exercise_name"),
            equipment_name=ex_data.get("equipment_name"),
            machine=ex_data.get("machine"),
            resistance_type=ex_data.get("resistance_type"),
            duration_seconds=ex_data.get("duration_seconds"),
            calories=ex_data.get("calories"),
            moves=ex_data.get("moves"),
            compliance=ex_data.get("compliance"),
            total_weight_kg=ex_data.get("total_weight_kg"),
            exercise_order=i,
            source=data.get("source", "manual"),
            source_id=ex_data.get("source_id"),
        )
        db.session.add(we)
        db.session.flush()  # Get the ID
        
        # Add sets
        sets_data = ex_data.get("sets", [])
        for s_data in sets_data:
            s = Set(
                workout_exercise_id=we.id,
                set_number=s_data.get("set_number", 1),
                reps_target=s_data.get("reps_target"),
                reps_actual=s_data.get("reps_actual"),
                weight_kg_target=s_data.get("weight_kg_target"),
                weight_kg_actual=s_data.get("weight_kg_actual"),
                compliance_target=s_data.get("compliance_target"),
                compliance_actual=s_data.get("compliance_actual"),
                source=data.get("source", "manual"),
                source_id=s_data.get("source_id"),
            )
            db.session.add(s)
    
    db.session.commit()
    return jsonify({"id": workout.id, "workout_name": workout.workout_name}), 201


@api_bp.route("/body-measurements")
def list_body_measurements():
    """List body measurements.

    Every reading is returned by default, including any the user has chosen to
    set aside - this is a raw data endpoint, so hiding rows would be surprising.
    Each entry carries ``is_superseded`` / ``superseded_by_id`` / ``superseded_at``
    so a consumer can tell which values are in use. Pass
    ``?include_superseded=false`` to get only the active readings, which is what
    the charts plot.

    For "what is my current weight", use ``/api/charts/summary`` instead.
    """
    measurements = BodyMeasurement.query.order_by(
        BodyMeasurement.measured_at.desc()
    ).all()

    include_superseded = request.args.get(
        "include_superseded", "true"
    ).lower() != "false"

    return jsonify([
        _serialise_measurement(m)
        for m in measurements
        if include_superseded or not m.is_superseded
    ])


def _serialise_measurement(measurement: BodyMeasurement) -> dict:
    """Render one BodyMeasurement row as a JSON-friendly dict.

    Shared by the list and create endpoints so the two cannot drift apart. Which
    readings the user rejected in favour of another for the same day is included
    here - see ``documentation/BODY-MEASUREMENTS.md``.

    Args:
        measurement: The row to serialise.

    Returns:
        A dict safe to hand to ``jsonify``.
    """
    return {
        "id": measurement.id,
        "measured_at": measurement.measured_at.isoformat() if measurement.measured_at else None,
        "measurement_type": measurement.measurement_type,
        "value": measurement.value,
        "unit": measurement.unit,
        "source": measurement.source,
        "source_id": measurement.source_id,
        "is_superseded": bool(measurement.is_superseded),
        "superseded_by_id": measurement.superseded_by_id,
        "superseded_at": measurement.superseded_at.isoformat() if measurement.superseded_at else None,
    }


@api_bp.route("/body-measurements", methods=["POST"])
def create_body_measurement():
    """Create a body measurement.

    If the new reading contradicts another source for the same day, the response
    reports the clash in ``conflicts`` and points at the profile page in
    ``resolve_url``. Nothing is overwritten - both readings are stored.

    A weight posted without an explicit BMI gets one derived from the profile
    height, so a caller that only knows the weight still fills the BMI chart. That
    only happens when ``Person.height_cm`` is set; see
    :func:`services.measurements.derive_bmi` for why an unknown height yields no
    BMI rather than a guess.

    Request body (JSON or form)::

        person_id         optional, defaults to the first profile
        measurement_type  optional, defaults to "weight"
        value             required, numeric
        measured_at       optional ISO timestamp, defaults to now
        unit              optional, defaults to "kg"
        source            optional, defaults to "manual"

    Returns:
        ``201`` with the created measurement(s), any conflicts, and a
        ``resolve_url`` to settle them. ``400`` when ``value`` is missing or not
        a number.
    """
    data = request.get_json(silent=True) or request.form

    # Validate before touching the database. float() on bad input raises, and an
    # unhandled ValueError here would surface as a 500 for what is really a
    # client mistake.
    raw_value = data.get("value")
    if raw_value is None or raw_value == "":
        return jsonify({"error": "value is required"}), 400

    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return jsonify({"error": f"value must be a number, got {raw_value!r}"}), 400

    raw_measured_at = data.get("measured_at")
    if raw_measured_at:
        try:
            measured_at = datetime.fromisoformat(str(raw_measured_at))
        except ValueError:
            return jsonify({
                "error": f"measured_at must be an ISO timestamp, got {raw_measured_at!r}"
            }), 400
    else:
        measured_at = datetime.utcnow()

    person_id = data.get("person_id", 1)
    measurement_type = data.get("measurement_type", "weight")
    unit = data.get("unit", "kg")
    source = data.get("source", "manual")

    person = db.session.get(Person, person_id)
    if person is None:
        return jsonify({"error": f"no person with id {person_id}"}), 400

    measurement = BodyMeasurement(
        person_id=person_id,
        measured_at=measured_at,
        measurement_type=measurement_type,
        value=value,
        unit=unit,
        source=source,
        source_id=data.get("source_id"),
    )
    db.session.add(measurement)
    db.session.flush()

    # Derive BMI from the recorded height when we can. The Wii Fit and Technogym
    # importers supply BMI directly, but a weight posted by a caller would
    # otherwise leave a gap in the BMI chart.
    derived_bmi = None
    if measurement_type == "weight":
        derived_bmi = measurement_service.derive_bmi(value, person.height_cm)

        if derived_bmi is not None:
            db.session.add(BodyMeasurement(
                person_id=person_id,
                measured_at=measured_at,
                measurement_type="bmi",
                value=derived_bmi,
                unit="",
                source=source,
                source_id=data.get("source_id"),
            ))

    db.session.commit()

    # Report, do not resolve: the user picks the value.
    mismatch_ids = measurement_service.supersede_mismatches_within_day(measurement)

    conflicts = [
        {
            "measurement_id": measurement.id,
            "measurement_type": measurement.measurement_type,
            "day": measurement.measured_at.date().isoformat(),
            "value": measurement.value,
            "source": measurement.source,
            "conflicts_with_id": other_id,
            "message": measurement_service.describe_conflict(
                measurement,
                db.session.get(BodyMeasurement, other_id),
                new_label="manual entry" if measurement.source == "manual" else None,
            ),
        }
        for other_id in mismatch_ids
    ]

    return jsonify({
        "id": measurement.id,
        "measurement": _serialise_measurement(measurement),
        # The derived BMI, if one was calculated, so the caller can see it without
        # a second request.
        "derived_bmi": derived_bmi,
        "conflicts": conflicts,
        "resolve_url": url_for("main.profile") if conflicts else None,
    }), 201


@api_bp.route("/training-context")
def training_context():
    """Return the holistic training snapshot.

    The same dict the guided runner plans against and the future assistant
    will consume as prompt context: person/goals, current weight/BMI, this
    week's cross-source totals, recent sessions from every source, muscle
    load, open conflicts. One builder, every consumer — the human UI and
    the eventual LLM can never disagree about what has happened.
    """
    from ..services import training_context as training_context_service

    person = db.session.query(Person.id).order_by(Person.id).first()
    return jsonify(training_context_service.snapshot(
        person[0] if person else None
    ))
