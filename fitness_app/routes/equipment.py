"""Equipment routes: CRUD for gym equipment."""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..models import db, Equipment, Exercise, EquipmentExercise

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
    return render_template("equipment_detail.html", equipment=equipment)


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
