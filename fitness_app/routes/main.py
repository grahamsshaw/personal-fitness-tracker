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

    # This week's sessions (Monday to now).
    today = datetime.now().date()
    week_start = today - timedelta(days=today.weekday())
    week_workouts = Workout.query.filter(
        Workout.started_at >= datetime.combine(week_start, datetime.min.time())
    ).count()

    # Goal progress. The baseline is the highest weight in the last 180
    # days — the honest "started from" proxy, captioned as such below.
    # At or past the goal reads full; with no goal there is no bar.
    goal_progress = None
    if person is not None and person.weight_goal_kg and latest_weight:
        heaviest = db.session.query(
            db.func.max(BodyMeasurement.value)
        ).filter(
            BodyMeasurement.measurement_type == "weight",
            BodyMeasurement.measured_at >= datetime.now() - timedelta(days=180),
        ).scalar()
        goal = person.weight_goal_kg
        current = latest_weight.value
        if current <= goal:
            goal_progress = 100
        elif heaviest and heaviest > goal:
            goal_progress = round(
                max(0, (heaviest - current) / (heaviest - goal)) * 100
            )

    # Muscles with no training in the last 90 days (top 3 + link).
    from ..services import muscles as muscle_service
    neglected = (
        muscle_service.neglected_muscles(person.id)[:3] if person else []
    )

    # This week's sessions broken down by source: gym, phone, Wii, manual —
    # the measurable whole, not just gym history.
    from ..services import training_context
    week_breakdown = (
        training_context.weekly_by_source(person.id) if person else None
    )

    # Today's planned routines, if any.
    todays_routines = []
    if person:
        import json as json_module
        from ..models import Routine
        weekday = today.weekday()
        for routine in Routine.query.filter_by(person_id=person.id).all():
            try:
                days = json_module.loads(routine.days or "[]")
            except (ValueError, TypeError):
                days = []
            if weekday in days:
                todays_routines.append(routine)

    # Week calendar (cyclable): per-day routines, overrides and sessions.
    week_offset = request.args.get("week_offset", 0, type=int)
    week_start_shifted = week_start + timedelta(weeks=week_offset)
    week_label = "This week" if week_offset == 0 else week_start_shifted.strftime("w/c %d %b")
    week_days = _week_days(person, week_start_shifted) if person else []

    # Last three weights for the home weight block.
    recent_weights = BodyMeasurement.query.filter_by(
        measurement_type="weight"
    ).order_by(BodyMeasurement.measured_at.desc()).limit(3).all()

    # Streak: consecutive weeks (back from this week) with a session.
    streak_weeks = _training_streak_weeks(person) if person else 0

    return render_template(
        "dashboard.html",
        person=person,
        recent_workouts=recent_workouts,
        recent_activities=recent_activities,
        latest_weight=latest_weight,
        recent_weights=recent_weights,
        last_gym=last_gym,
        total_workouts=total_workouts,
        total_exercises=total_exercises,
        total_equipment=total_equipment,
        week_workouts=week_workouts,
        goal_progress=goal_progress,
        neglected=neglected,
        week_breakdown=week_breakdown,
        todays_routines=todays_routines,
        week_offset=week_offset,
        week_label=week_label,
        week_days=week_days,
        streak_weeks=streak_weeks,
    )


def _week_days(person, week_start):
    """Build one week of calendar cells: routines, overrides, sessions.

    Args:
        person: Whose calendar this is.
        week_start: Monday date of the week to render.

    Returns:
        List of dicts with iso/label/is_today/routines/override/session names.
    """
    import json as json_module
    from ..models import CalendarOverride, Routine

    today = datetime.now().date()
    cells = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        override = CalendarOverride.query.filter_by(
            person_id=person.id, day=day.isoformat()).first()
        routines = []
        override_routine = None
        override_rest = False
        if override is not None:
            if override.is_rest:
                override_rest = True
            elif override.routine_id:
                override_routine = db.session.get(Routine, override.routine_id)
        else:
            for routine in Routine.query.filter_by(person_id=person.id).all():
                try:
                    days = json_module.loads(routine.days or "[]")
                except (ValueError, TypeError):
                    days = []
                if day.weekday() in days:
                    routines.append(routine)
        sessions = [
            workout.workout_name or "Workout"
            for workout in Workout.query.filter(
                Workout.person_id == person.id,
                Workout.started_at >= datetime.combine(day, datetime.min.time()),
                Workout.started_at < datetime.combine(
                    day + timedelta(days=1), datetime.min.time()),
            ).all()
        ]
        cells.append({
            "iso": day.isoformat(),
            "label": day.strftime("%a %d %b") + (" (today)" if day == today else ""),
            "is_today": day == today,
            "routines": routines,
            "override_routine": override_routine,
            "override_rest": override_rest,
            "sessions": sessions,
        })
    return cells


def _training_streak_weeks(person) -> int:
    """Consecutive weeks with at least one session, counting back.

    This week counts when it already holds a session, otherwise the streak
    is measured back from last week — starting a week does not break it,
    only an empty one does.

    Args:
        person: Whose streak to measure.

    Returns:
        Number of consecutive active weeks.
    """
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())

    def active(week_monday) -> bool:
        return Workout.query.filter(
            Workout.person_id == person.id,
            Workout.started_at >= datetime.combine(week_monday, datetime.min.time()),
            Workout.started_at < datetime.combine(
                week_monday + timedelta(days=7), datetime.min.time()),
        ).first() is not None

    streak = 0
    cursor = monday
    if not active(cursor):
        cursor -= timedelta(weeks=1)
    while active(cursor):
        streak += 1
        cursor -= timedelta(weeks=1)
    return streak


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
        person.weight_goal_kg = float(request.form.get("weight_goal_kg", 0)) if request.form.get("weight_goal_kg") else None
        
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

    # Latest reading per non-weight/BMI type (waist, arms, …) for the
    # measurements panel.
    other_measurements = []
    seen_types = set()
    for measurement in BodyMeasurement.query.order_by(
        BodyMeasurement.measured_at.desc()
    ).all():
        if measurement.measurement_type in ("weight", "bmi"):
            continue
        if measurement.measurement_type in seen_types:
            continue
        seen_types.add(measurement.measurement_type)
        other_measurements.append(measurement)

    return render_template(
        "profile.html",
        person=person,
        latest_weight=latest_weight,
        latest_bmi=latest_bmi,
        conflicts=conflicts,
        source_labels=SOURCE_LABELS,
        today=datetime.now().strftime("%Y-%m-%d"),
        measurement_types=MANUAL_MEASUREMENT_TYPES,
        other_measurements=other_measurements,
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


#: Measurement types the manual form offers, with their units. Weight and
#: BMI keep their dedicated form and conflict handling; everything else is a
#: plain reading. The model accepts any type string — this list is just the
#: form's suggestions.
MANUAL_MEASUREMENT_TYPES = [
    ("weight", "kg"),
    ("body_fat", "%"),
    ("waist", "cm"),
    ("chest", "cm"),
    ("arms", "cm"),
    ("hips", "cm"),
    ("thigh", "cm"),
    ("shoulders", "cm"),
]


@main_bp.route("/log-measurement", methods=["POST"])
def log_measurement():
    """Log a manual body measurement of any type (waist, arms, …).

    Weight posted here behaves exactly like the weight form (BMI derived,
    same-day conflicts flagged); every other type stores a plain reading.
    """
    person = Person.query.first()
    if not person:
        flash("Please set up your profile first.", "warning")
        return redirect(url_for("main.profile"))

    measurement_type = (request.form.get("measurement_type") or "").strip()
    raw_value = request.form.get("value")
    if not measurement_type or raw_value in (None, ""):
        flash("Measurement type and value are required.", "error")
        return redirect(url_for("main.profile"))

    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        flash("Invalid measurement value.", "error")
        return redirect(url_for("main.profile"))

    unit = dict(MANUAL_MEASUREMENT_TYPES).get(measurement_type, "")
    date_str = request.form.get("measured_date")
    if date_str:
        try:
            measured_at = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            flash("Invalid date.", "error")
            return redirect(url_for("main.profile"))
    else:
        measured_at = datetime.utcnow()

    measurement = BodyMeasurement(
        person_id=person.id,
        measured_at=measured_at,
        measurement_type=measurement_type,
        value=value,
        unit=unit,
        source="manual",
        source_id=f"manual_{measurement_type}_{measured_at.isoformat()}",
    )
    db.session.add(measurement)
    db.session.flush()

    if measurement_type == "weight":
        bmi = measurement_service.derive_bmi(value, person.height_cm)
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

    if measurement_type in ("weight", "bmi"):
        conflicts = measurement_service.find_conflicts(person.id)
        todays = [c for c in conflicts
                  if c.day == measured_at.date()
                  and c.measurement_type == measurement_type]
        if todays:
            flash(
                f"Heads up: another source recorded a different "
                f"{measurement_type} on {measured_at.strftime('%Y-%m-%d')}. "
                f"Choose which value to use on the profile page - nothing "
                f"has been overwritten.",
                "warning",
            )

    flash(f"Logged {measurement_type}: {value:g} {unit}".strip(), "success")
    return redirect(url_for("main.profile"))


@main_bp.route("/muscles")
def muscles():
    """Muscle training map: fatigue and strength per muscle group.

    The map itself is drawn client-side from ``body-paths.json`` geometry
    and ``/api/charts/muscles`` levels. Clicking a muscle shows what trained
    it recently; ``neglected`` names what the last 90 days never touched.
    """
    return render_template("muscles.html")


#: Standard plates, heaviest first, for the plate calculator.
PLATE_SIZES = [25.0, 20.0, 15.0, 10.0, 5.0, 2.5, 1.25]

#: Default Olympic bar weight.
BAR_WEIGHT_KG = 20.0


@main_bp.route("/stats")
def stats():
    """Training stats page: muscle balance, effort, weekly, progress."""
    exercises = Exercise.query.order_by(Exercise.name).all()
    return render_template("stats.html", exercises=exercises)


@main_bp.route("/plate-calculator")
def plate_calculator():
    """Plate calculator: plates per side for a target bar weight.

    Pure arithmetic page — no database reads, no writes. Greedy from the
    heaviest plate down, which is how anyone loads a bar in practice.
    """
    target = request.args.get("target", type=float)
    bar = request.args.get("bar", type=float) or BAR_WEIGHT_KG

    result = None
    if target is not None and target > bar:
        remaining = round((target - bar) / 2, 2)
        plates = []
        for size in PLATE_SIZES:
            while remaining >= size - 1e-9:
                plates.append(size)
                remaining = round(remaining - size, 2)
        result = {
            "target": target,
            "bar": bar,
            "plates": plates,
            "loaded": round(bar + sum(plates) * 2, 2),
            "remainder": round(remaining, 2),
        }

    return render_template(
        "plate_calculator.html", result=result, target=target, bar=bar,
        plates=PLATE_SIZES, default_bar=BAR_WEIGHT_KG,
    )


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
    from ..services import sessions as session_service

    workout = Workout.query.get_or_404(workout_id)
    return render_template(
        "workout_detail.html",
        workout=workout,
        linked_activities=session_service.linked_activities(workout),
        link_candidates=session_service.link_candidates(workout),
    )


@main_bp.route("/activities")
def activities():
    """Activity charts page."""
    from ..services.training_context import is_daily_summary

    # Summary stats exclude day summaries: a 1439-minute "walk" is
    # background life, not training, and would drown every total. The rule
    # lives in training_context.is_daily_summary (prefix matching with
    # NULLs has no clean SQL spelling), so ids filter in Python and the
    # sums stay in SQL.
    genuine_ids = [
        activity.id for activity in Activity.query.all()
        if not is_daily_summary(activity)
    ]
    total_activities = len(genuine_ids)

    total_duration = db.session.query(
        db.func.sum(Activity.duration_seconds)
    ).filter(Activity.id.in_(genuine_ids)).scalar() or 0

    total_calories = db.session.query(
        db.func.sum(Activity.calories)
    ).scalar() or 0

    # Walking in the last 30 days, split two ways. Tracked walks are the
    # sessions the watch actually detected (your 10-minute-walk alerts live
    # here); daily totals are the background rollups. Previously one number
    # lumped both and read as walking every minute of every day.
    month_start = datetime.now() - timedelta(days=30)
    walking = Activity.query.filter(
        Activity.activity_type == "walking",
        Activity.started_at >= month_start,
    ).all()
    sessions = [a for a in walking if not is_daily_summary(a)]
    daily = [a for a in walking if is_daily_summary(a)]
    walking_summary = {
        "sessions": len(sessions),
        "minutes": sum(
            (a.duration_seconds or 0) for a in sessions
        ) // 60,
        "km": round(sum(a.distance_m or 0 for a in sessions) / 1000, 1),
        "calories": round(sum(a.calories or 0 for a in sessions)),
        "steps": sum(a.steps or 0 for a in daily),
        "daily_km": round(sum(a.distance_m or 0 for a in daily) / 1000, 1),
        "daily_calories": round(sum(a.calories or 0 for a in daily)),
        "days": len({a.started_at.date() for a in daily}),
    }

    return render_template(
        "activities.html",
        total_activities=total_activities,
        total_duration=round(total_duration / 60),
        total_calories=round(total_calories),
        walking_summary=walking_summary,
    )


@main_bp.route("/measurements/<int:measurement_id>/delete", methods=["POST"])
def delete_measurement(measurement_id):
    """Delete a single body measurement (the bin icon).

    Only manual readings can be deleted — imported data is re-imported
    from its source, so deleting it here would silently resurrect on the
    next import and lie about what happened.
    """
    measurement = BodyMeasurement.query.get_or_404(measurement_id)
    if measurement.source != "manual":
        flash("Only manual readings can be deleted here — imported data "
              "comes back on the next import.", "warning")
        return redirect(url_for("main.profile"))
    db.session.delete(measurement)
    db.session.commit()
    flash("Reading deleted.", "success")
    return redirect(url_for("main.profile"))


@main_bp.route("/activities/<int:activity_id>")
def activity_detail(activity_id):
    """Activity detail, embed-friendly for calendar overlays."""
    activity = Activity.query.get_or_404(activity_id)
    return render_template("activity_detail.html", activity=activity)


@main_bp.route("/calendar/<day>", methods=["GET", "POST"])
def calendar_day(day):
    """View and edit one calendar day: plan a routine or mark rest.

    Overrides the weekday schedule for a single date without touching any
    routine. Clearing back to the weekday default deletes the override.
    """
    from ..models import CalendarOverride, Routine

    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        flash("Invalid date.", "error")
        return redirect(url_for("main.dashboard"))

    person = Person.query.first()
    if person is None:
        flash("Set up your profile first.", "warning")
        return redirect(url_for("main.profile"))

    if request.method == "POST":
        routine_id = request.form.get("routine_id", type=int)
        is_rest = bool(request.form.get("is_rest"))
        override = CalendarOverride.query.filter_by(
            person_id=person.id, day=day).first()
        if routine_id is None and not is_rest:
            if override is not None:
                db.session.delete(override)
                db.session.commit()
            flash("Back to the weekday schedule for that day.", "success")
        else:
            if override is None:
                override = CalendarOverride(person_id=person.id, day=day)
                db.session.add(override)
            override.routine_id = routine_id
            override.is_rest = is_rest
            db.session.commit()
            flash("Day updated.", "success")
        return redirect(url_for("main.dashboard"))

    routines = Routine.query.order_by(Routine.name).all()
    override = CalendarOverride.query.filter_by(
        person_id=person.id, day=day).first()
    return render_template(
        "calendar_day.html", day=day, routines=routines, override=override,
    )
