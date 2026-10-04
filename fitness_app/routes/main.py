"""Main routes: dashboard, profile, pages."""

from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..models import db, Person, Activity, Workout, BodyMeasurement, Exercise, Equipment
from ..services import measurements as measurement_service

main_bp = Blueprint("main", __name__)

#: Friendly names for measurement sources, used in the conflict UI so the
#: profile page says "Wii Fit" rather than "wii_fit".
SOURCE_LABELS = {
    "manual": "Manual entry",
    "wii_fit": "Wii Fit",
    "technogym": "Technogym",
    "health_connect": "Health Connect",
}


def source_label(source: str) -> str:
    """Return a human-readable name for a measurement source.

    Args:
        source: The raw source string from the database.

    Returns:
        A display name, falling back to a tidied version of the raw value.
    """
    return SOURCE_LABELS.get(source, (source or "unknown").replace("_", " ").title())


@main_bp.route("/")
def dashboard():
    """Main dashboard."""
    person = Person.query.first()
    
    # Recent workouts
    recent_workouts = Workout.query.order_by(Workout.started_at.desc()).limit(5).all()
    
    # Recent activities
    recent_activities = Activity.query.order_by(Activity.started_at.desc()).limit(10).all()
    
    # Latest weight
    latest_weight = BodyMeasurement.query.filter_by(
        measurement_type="weight"
    ).order_by(BodyMeasurement.measured_at.desc()).first()
    
    # Last gym visit
    last_gym = Workout.query.order_by(Workout.started_at.desc()).first()
    
    # Stats
    total_workouts = Workout.query.count()
    total_exercises = Exercise.query.count()
    total_equipment = Equipment.query.count()
    
    return render_template(
        "dashboard.html",
        person=person,
        recent_workouts=recent_workouts,
        recent_activities=recent_activities,
        latest_weight=latest_weight,
        last_gym=last_gym,
        total_workouts=total_workouts,
        total_exercises=total_exercises,
        total_equipment=total_equipment,
    )


@main_bp.route("/profile", methods=["GET", "POST"])
def profile():
    """User profile page."""
    person = Person.query.first()
    
    if request.method == "POST":
        if not person:
            person = Person()
            db.session.add(person)
        
        person.first_name = request.form.get("first_name", "")
        person.last_name = request.form.get("last_name", "")
        person.gender = request.form.get("gender", "")
        person.height_cm = float(request.form.get("height_cm", 0)) if request.form.get("height_cm") else None
        
        birth_date_str = request.form.get("birth_date", "")
        if birth_date_str:
            try:
                dt = datetime.strptime(birth_date_str, "%Y-%m-%d")
                person.birth_date = int(dt.strftime("%Y%m%d"))
            except ValueError:
                pass
        
        db.session.commit()
        flash("Profile updated successfully!", "success")
        return redirect(url_for("main.profile"))
    
    # Current weight and BMI come from the service, which skips any readings
    # the user has decided to ignore.
    current = measurement_service.current_values()
    latest_weight = current.get("weight")
    latest_bmi = current.get("bmi")

    # Days where two sources disagree and the user has not chosen yet.
    conflicts = measurement_service.find_conflicts()

    return render_template(
        "profile.html",
        person=person,
        latest_weight=latest_weight,
        latest_bmi=latest_bmi,
        conflicts=conflicts,
        source_labels=SOURCE_LABELS,
        today=datetime.now().strftime("%Y-%m-%d"),
    )


@main_bp.route("/measurements/resolve", methods=["POST"])
def resolve_measurement():
    """Record the user's choice for a day where two sources disagree.

    Form fields:
        measurement_type: ``weight`` or ``bmi``
        day: ``YYYY-MM-DD``
        keep_id: id of the reading to believe

    The readings that were not chosen are marked superseded, not deleted, so the
    decision can be undone later.
    """
    measurement_type = request.form.get("measurement_type", "")
    day_str = request.form.get("day", "")
    keep_id = request.form.get("keep_id", type=int)

    if measurement_type not in measurement_service.CONFLICT_TYPES:
        flash("That measurement type cannot be resolved here.", "error")
        return redirect(url_for("main.profile"))

    try:
        day = datetime.strptime(day_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Invalid date.", "error")
        return redirect(url_for("main.profile"))

    if keep_id is None:
        flash("No reading was selected.", "error")
        return redirect(url_for("main.profile"))

    try:
        result = measurement_service.resolve_conflict(
            measurement_type, day, keep_id
        )
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("main.profile"))

    if result["undone"]:
        flash("Nothing needed changing for that day.", "info")
    else:
        hidden = len(result["superseded"])
        flash(
            f"Saved. Using your chosen {measurement_type} for {day.isoformat()}; "
            f"{hidden} other reading(s) kept in the database but hidden from "
            f"the chart and current values.",
            "success",
        )

    return redirect(url_for("main.profile"))


@main_bp.route("/measurements/undo", methods=["POST"])
def undo_measurement():
    """Undo a previous choice, putting every reading for a day back in play.

    Form fields:
        measurement_type, day
    """
    measurement_type = request.form.get("measurement_type", "")
    day_str = request.form.get("day", "")

    if measurement_type not in measurement_service.CONFLICT_TYPES:
        flash("That measurement type cannot be resolved here.", "error")
        return redirect(url_for("main.profile"))

    try:
        day = datetime.strptime(day_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Invalid date.", "error")
        return redirect(url_for("main.profile"))

    restored = measurement_service.clear_superseded(measurement_type, day)

    if restored:
        flash(
            f"Reopened {day.isoformat()}: {restored} reading(s) are active again.",
            "success",
        )
    else:
        flash(f"Nothing to undo for {day.isoformat()}.", "info")

    return redirect(url_for("main.profile"))


@main_bp.route("/log-weight", methods=["POST"])
def log_weight():
    """Log a manual weight measurement."""
    person = Person.query.first()
    if not person:
        flash("Please set up your profile first.", "warning")
        return redirect(url_for("main.profile"))
    
    weight = request.form.get("weight")
    weight_date = request.form.get("weight_date")
    
    if not weight:
        flash("Weight is required.", "error")
        return redirect(url_for("main.profile"))
    
    try:
        weight_val = float(weight)
    except ValueError:
        flash("Invalid weight value.", "error")
        return redirect(url_for("main.profile"))
    
    if weight_date:
        measured_at = datetime.strptime(weight_date, "%Y-%m-%d")
    else:
        measured_at = datetime.utcnow()
    
    measurement = BodyMeasurement(
        person_id=person.id,
        measured_at=measured_at,
        measurement_type="weight",
        value=weight_val,
        unit="kg",
        source="manual",
        source_id=f"manual_weight_{measured_at.isoformat()}",
    )
    db.session.add(measurement)
    db.session.flush()

    # Derive BMI from the profile height when we can. The Wii Fit and Technogym
    # importers both supply BMI directly, but a manual weight entry would
    # otherwise leave the BMI chart with a gap.
    bmi = measurement_service.derive_bmi(weight_val, person.height_cm)

    if bmi is not None:
        db.session.add(BodyMeasurement(
            person_id=person.id,
            measured_at=measured_at,
            measurement_type="bmi",
            value=bmi,
            unit="",
            source="manual",
            source_id=f"manual_bmi_{measured_at.isoformat()}",
        ))

    db.session.commit()

    # A manual entry can disagree with a reading from another source on the same
    # day. Nothing is overwritten - the day is just flagged for review.
    conflicts = measurement_service.find_conflicts(person.id)
    todays = [
        c for c in conflicts
        if c.day == measured_at.date() and c.measurement_type == "weight"
    ]

    flash(f"Weight logged: {weight_val} kg", "success")

    if todays:
        flash(
            f"Heads up: another source recorded a different weight on "
            f"{measured_at.strftime('%Y-%m-%d')}. Choose which value to use on "
            f"the profile page - nothing has been overwritten.",
            "warning",
        )

    return redirect(url_for("main.profile"))


@main_bp.route("/history")
def history():
    """Workout history page."""
    page = request.args.get("page", 1, type=int)
    workouts = Workout.query.order_by(Workout.started_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    return render_template("history.html", workouts=workouts)


@main_bp.route("/workout/<int:workout_id>")
def workout_detail(workout_id):
    """View a single workout."""
    workout = Workout.query.get_or_404(workout_id)
    return render_template("workout_detail.html", workout=workout)


@main_bp.route("/activities")
def activities():
    """Activity charts page."""
    # Get summary stats
    total_activities = Activity.query.count()
    
    total_duration = db.session.query(
        db.func.sum(Activity.duration_seconds)
    ).scalar() or 0
    
    total_calories = db.session.query(
        db.func.sum(Activity.calories)
    ).scalar() or 0
    
    return render_template(
        "activities.html",
        total_activities=total_activities,
        total_duration=round(total_duration / 60),
        total_calories=round(total_calories),
    )
