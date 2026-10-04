"""Workout routes: create, view, manage workouts."""

from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..models import db, Workout, WorkoutExercise, Set, Exercise, Equipment, Person

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
    )


@workouts_bp.route("/<int:workout_id>")
def view_workout(workout_id):
    """View a single workout."""
    workout = Workout.query.get_or_404(workout_id)
    return render_template("workout_detail.html", workout=workout)


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
