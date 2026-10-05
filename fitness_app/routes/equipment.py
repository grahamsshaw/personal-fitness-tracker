"""Equipment routes: CRUD for gym equipment and equipment profiles."""

import json

from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..models import db, Equipment, Exercise, EquipmentExercise, EquipmentProfile

equipment_bp = Blueprint("equipment", __name__)


@equipment_bp.route("/")
def list_equipment():
    """List all equipment."""
    equipment = Equipment.query.order_by(Equipment.name).all()
    return render_template("equipment_list.html", equipment=equipment)


@equipment_bp.route("/new", methods=["GET", "POST"])
def new_equipment():
    """Add new equipment."""
    exercises = Exercise.query.order_by(Exercise.name).all()
    
    if request.method == "POST":
        equipment = Equipment(
            name=request.form.get("name"),
            manufacturer=request.form.get("manufacturer"),
            model=request.form.get("model"),
            category=request.form.get("category"),
            muscle_group=request.form.get("muscle_group"),
            gym_location=request.form.get("gym_location"),
            qr_code=request.form.get("qr_code"),
            qr_url=request.form.get("qr_url"),
            notes=request.form.get("notes"),
        )
        db.session.add(equipment)
        db.session.flush()
        
        # Link exercises
        exercise_ids = request.form.getlist("exercises")
        for ex_id in exercise_ids:
            link = EquipmentExercise(equipment_id=equipment.id, exercise_id=int(ex_id))
            db.session.add(link)
        
        db.session.commit()
        flash("Equipment added successfully!", "success")
        return redirect(url_for("equipment.list_equipment"))
    
    return render_template("equipment_form.html", equipment=None, exercises=exercises)


@equipment_bp.route("/<int:equipment_id>")
def view_equipment(equipment_id):
    """View equipment details."""
    equipment = Equipment.query.get_or_404(equipment_id)
    return render_template(
        "equipment_detail.html",
        equipment=equipment,
        map_muscles=_profile_muscles(equipment),
    )


@equipment_bp.route("/<int:equipment_id>/edit", methods=["GET", "POST"])
def edit_equipment(equipment_id):
    """Edit equipment."""
    equipment = Equipment.query.get_or_404(equipment_id)
    exercises = Exercise.query.order_by(Exercise.name).all()
    
    if request.method == "POST":
        equipment.name = request.form.get("name", equipment.name)
        equipment.manufacturer = request.form.get("manufacturer", equipment.manufacturer)
        equipment.model = request.form.get("model", equipment.model)
        equipment.category = request.form.get("category", equipment.category)
        equipment.muscle_group = request.form.get("muscle_group", equipment.muscle_group)
        equipment.gym_location = request.form.get("gym_location", equipment.gym_location)
        equipment.qr_code = request.form.get("qr_code", equipment.qr_code)
        equipment.qr_url = request.form.get("qr_url", equipment.qr_url)
        equipment.notes = request.form.get("notes", equipment.notes)
        
        # Update exercise links
        EquipmentExercise.query.filter_by(equipment_id=equipment.id).delete()
        exercise_ids = request.form.getlist("exercises")
        for ex_id in exercise_ids:
            link = EquipmentExercise(equipment_id=equipment.id, exercise_id=int(ex_id))
            db.session.add(link)
        
        db.session.commit()
        flash("Equipment updated successfully!", "success")
        return redirect(url_for("equipment.view_equipment", equipment_id=equipment.id))
    
    return render_template("equipment_form.html", equipment=equipment, exercises=exercises)


@equipment_bp.route("/<int:equipment_id>/delete", methods=["POST"])
def delete_equipment(equipment_id):
    """Delete equipment."""
    equipment = Equipment.query.get_or_404(equipment_id)
    EquipmentExercise.query.filter_by(equipment_id=equipment.id).delete()
    db.session.delete(equipment)
    db.session.commit()
    flash("Equipment deleted successfully!", "success")
    return redirect(url_for("equipment.list_equipment"))


# ===================================================================
# Exercise library
# ===================================================================

@equipment_bp.route("/library")
def exercise_library():
    """Searchable exercise library.

    Filters narrow by equipment (only combinations with results stay
    selectable is a later refinement; for now the selects are independent
    and an empty result suggests clearing a filter).
    """
    query = (request.args.get("q") or "").strip()
    equipment_id = request.args.get("equipment_id", type=int)
    muscle = (request.args.get("muscle") or "").strip().lower()

    pool = Exercise.query
    if query:
        pool = pool.filter(Exercise.name.ilike(f"%{query}%"))
    if equipment_id:
        pool = pool.join(
            EquipmentExercise,
            EquipmentExercise.exercise_id == Exercise.id,
        ).filter(EquipmentExercise.equipment_id == equipment_id)

    exercises = pool.order_by(Exercise.name).limit(200).all()

    if muscle:
        from ..services.muscles import muscles_for_exercise, normalize_muscle
        canonical = normalize_muscle(muscle)
        if canonical is None:
            exercises = []
        else:
            exercises = [ex for ex in exercises
                         if canonical in muscles_for_exercise(ex)]

    equipment = Equipment.query.order_by(Equipment.name).all()
    return render_template(
        "exercise_library.html", exercises=exercises, equipment=equipment,
        query=query, equipment_id=equipment_id, muscle=muscle,
    )


@equipment_bp.route("/library/new", methods=["GET", "POST"])
def new_library_exercise():
    """Add a custom exercise. A name and body part is enough; it behaves
    like built-in ones everywhere (runner, plans, muscle map)."""
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Name is required.", "error")
            return redirect(url_for("equipment.new_library_exercise"))
        if Exercise.query.filter(
            db.func.lower(Exercise.name) == name.lower()
        ).first():
            flash("An exercise with that name already exists.", "warning")
            return redirect(url_for("equipment.exercise_library"))

        db.session.add(Exercise(
            name=name,
            category=request.form.get("category") or "strength",
            muscle_group=request.form.get("muscle_group"),
            target_muscle=request.form.get("target_muscle"),
            source="manual",
        ))
        db.session.commit()
        flash(f"Exercise '{name}' added.", "success")
        return redirect(url_for("equipment.exercise_library"))

    return render_template("exercise_form.html")


@equipment_bp.route("/library/<int:exercise_id>")
def exercise_detail(exercise_id):
    """Exercise detail: instructions, muscles with map, history charts."""
    from ..services.muscles import muscles_for_exercise

    exercise = Exercise.query.get_or_404(exercise_id)
    return render_template(
        "exercise_detail.html",
        exercise=exercise,
        map_muscles={muscle: 4 for muscle in muscles_for_exercise(exercise)},
    )


# ===================================================================
# Equipment profiles
# ===================================================================

def _split_csv(raw: str | None) -> list[str]:
    """Split a comma-separated form field into a list of trimmed strings.

    Empty strings are discarded so a blank field becomes an empty list.

    Args:
        raw: Raw form value, e.g. "Quadriceps, Glutes, Hamstrings".

    Returns:
        List of trimmed, non-empty strings.
    """
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _profile_muscles(equipment: Equipment) -> dict[str, int]:
    """Canonical muscles for an equipment's profile, for the mini body map.

    Combines the profile's muscles-used list with the supported exercises'
    target muscles from the exercise library, so the map shows what the
    machine works the way the diagrams printed on machines do.

    Args:
        equipment: The equipment row (with its optional profile).

    Returns:
        Mapping of canonical muscle to shade level (target 4, secondary 2).
    """
    import json as json_module

    from ..services.muscles import normalize_muscle

    highlight: dict[str, int] = {}
    profile = equipment.profile

    if profile is None:
        return highlight

    def add(raw: str | None, level: int) -> None:
        canonical = normalize_muscle(raw)
        if canonical is not None:
            highlight[canonical] = max(highlight.get(canonical, 0), level)

    try:
        muscles_used = json_module.loads(profile.muscles_used or "[]")
    except (ValueError, TypeError):
        muscles_used = []
    for raw in muscles_used or []:
        add(raw, 4)

    try:
        supported = json_module.loads(profile.supported_exercises or "[]")
    except (ValueError, TypeError):
        supported = []
    if supported:
        from ..models import Exercise
        for name in supported:
            exercise = Exercise.query.filter(
                db.func.lower(Exercise.name) == name.lower()
            ).first()
            if exercise is None or exercise.target_muscle is None:
                continue
            add(exercise.target_muscle, 4)
            try:
                secondary = json_module.loads(exercise.secondary_muscles or "[]")
            except (ValueError, TypeError):
                secondary = []
            for raw in secondary or []:
                add(raw, 2)

    return highlight


@equipment_bp.route("/profiles")
def list_profiles():
    """List all equipment profiles."""
    profiles = EquipmentProfile.query.order_by(
        EquipmentProfile.name, EquipmentProfile.machine_type
    ).all()
    return render_template("equipment_profile_list.html", profiles=profiles)


@equipment_bp.route("/profiles/new", methods=["GET", "POST"])
def new_profile():
    """Create a new equipment profile."""
    equipment = Equipment.query.order_by(Equipment.name).all()

    if request.method == "POST":
        profile = EquipmentProfile(
            equipment_id=request.form.get("equipment_id") or None,
            machine_type=request.form.get("machine_type"),
            name=request.form.get("name"),
            muscles_used=json.dumps(_split_csv(request.form.get("muscles_used"))),
            supported_exercises=json.dumps(_split_csv(request.form.get("supported_exercises"))),
            program_modes=json.dumps(_split_csv(request.form.get("program_modes"))),
            details=request.form.get("details"),
            source=request.form.get("source"),
        )
        db.session.add(profile)
        db.session.commit()
        flash("Equipment profile created!", "success")
        return redirect(url_for("equipment.list_profiles"))

    return render_template("equipment_profile_form.html", profile=None, equipment=equipment)


@equipment_bp.route("/profiles/<int:profile_id>")
def view_profile(profile_id):
    """View an equipment profile."""
    profile = EquipmentProfile.query.get_or_404(profile_id)
    return render_template("equipment_profile_detail.html", profile=profile)


@equipment_bp.route("/profiles/<int:profile_id>/edit", methods=["GET", "POST"])
def edit_profile(profile_id):
    """Edit an equipment profile."""
    profile = EquipmentProfile.query.get_or_404(profile_id)
    equipment = Equipment.query.order_by(Equipment.name).all()

    if request.method == "POST":
        profile.equipment_id = request.form.get("equipment_id") or None
        profile.machine_type = request.form.get("machine_type", profile.machine_type)
        profile.name = request.form.get("name", profile.name)
        profile.muscles_used = json.dumps(_split_csv(request.form.get("muscles_used")))
        profile.supported_exercises = json.dumps(_split_csv(request.form.get("supported_exercises")))
        profile.program_modes = json.dumps(_split_csv(request.form.get("program_modes")))
        profile.details = request.form.get("details", profile.details)
        profile.source = request.form.get("source", profile.source)
        db.session.commit()
        flash("Equipment profile updated!", "success")
        return redirect(url_for("equipment.view_profile", profile_id=profile.id))

    return render_template("equipment_profile_form.html", profile=profile, equipment=equipment)


@equipment_bp.route("/profiles/<int:profile_id>/delete", methods=["POST"])
def delete_profile(profile_id):
    """Delete an equipment profile."""
    profile = EquipmentProfile.query.get_or_404(profile_id)
    db.session.delete(profile)
    db.session.commit()
    flash("Equipment profile deleted!", "success")
    return redirect(url_for("equipment.list_profiles"))
