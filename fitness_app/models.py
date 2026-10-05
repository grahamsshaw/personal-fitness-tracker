"""Database models for the fitness tracker."""

from datetime import datetime
from . import db


class Person(db.Model):
    """User profile."""
    __tablename__ = "person"

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    birth_date = db.Column(db.Integer)  # YYYYMMDD format
    gender = db.Column(db.String(10))
    height_cm = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    body_measurements = db.relationship("BodyMeasurement", backref="person", lazy=True)
    activities = db.relationship("Activity", backref="person", lazy=True)
    workouts = db.relationship("Workout", backref="person", lazy=True)
    preferences = db.relationship("ExercisePreference", backref="person", lazy=True)

    def __repr__(self):
        return f"<Person {self.first_name} {self.last_name}>"


class BodyMeasurement(db.Model):
    """Body measurements (weight, BMI, etc.) from any source.

    Conflict handling
    -----------------
    Two sources can easily disagree about the same day - the Wii Fit scale says
    99.5 kg while Technogym's own record for that date says 105 kg. Nothing is
    ever deleted or silently overridden on import: both readings are kept and
    the disagreement is simply *visible* (see ``services.measurements``).

    ``is_superseded`` records the user's decision, not an automatic one. When
    they pick a winner for a day, the readings they rejected are flagged here
    and pointed at the winner via ``superseded_by_id``. Superseded readings stay
    in the database and remain visible on request; they are just left out of the
    current-value calculation and the default chart series.
    """
    __tablename__ = "body_measurements"

    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    measured_at = db.Column(db.DateTime, nullable=False)
    measurement_type = db.Column(db.String(50), nullable=False)  # 'weight', 'bmi', 'height', 'body_fat'
    value = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(20), nullable=False)  # 'kg', 'cm', '%'
    source = db.Column(db.String(50), default="manual")  # 'manual', 'wii_fit', 'technogym', 'health_connect'
    source_id = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Set only by an explicit user decision on the profile page.
    is_superseded = db.Column(db.Boolean, default=False, nullable=False)
    superseded_by_id = db.Column(db.Integer, db.ForeignKey("body_measurements.id"))
    superseded_at = db.Column(db.DateTime)

    __table_args__ = (
        db.UniqueConstraint("person_id", "measured_at", "measurement_type", "source", "source_id"),
    )

    def __repr__(self):
        return f"<BodyMeasurement {self.measurement_type}={self.value}{self.unit}>"


class Activity(db.Model):
    """Activities (any type: gym, walking, running, cycling, Wii Fit)."""
    __tablename__ = "activities"

    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    activity_type = db.Column(db.String(50), nullable=False)  # 'gym', 'walking', 'running', 'cycling', 'wii_fit', 'rowing'
    started_at = db.Column(db.DateTime, nullable=False)
    ended_at = db.Column(db.DateTime)
    duration_seconds = db.Column(db.Integer)
    distance_m = db.Column(db.Float)
    calories = db.Column(db.Float)
    avg_heart_rate = db.Column(db.Integer)
    max_heart_rate = db.Column(db.Integer)
    notes = db.Column(db.Text)
    source = db.Column(db.String(50), default="manual")
    source_id = db.Column(db.String(100))
    correlated_with = db.Column(db.Integer, db.ForeignKey("activities.id"))
    enrichment_data = db.Column(db.Text)  # JSON blob for extra data
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("source", "source_id"),
    )

    def __repr__(self):
        return f"<Activity {self.activity_type} at {self.started_at}>"


class Exercise(db.Model):
    """Canonical exercise definitions."""
    __tablename__ = "exercises"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    category = db.Column(db.String(50))  # 'strength', 'cardio', 'flexibility', 'balance'
    muscle_group = db.Column(db.String(100))  # 'chest', 'legs', 'back', etc.
    # Library enrichment (seed_exercises.py, MIT-licensed ExerciseDB metadata).
    # target_muscle/secondary_muscles hold the dataset's raw spellings;
    # services/muscles.py normalises them onto canonical names for the map.
    external_id = db.Column(db.String(50))  # dataset id, e.g. "0001"
    body_part = db.Column(db.String(100))  # dataset body part, e.g. "waist"
    equipment_label = db.Column(db.String(100))  # dataset equipment, e.g. "cable"
    target_muscle = db.Column(db.String(100))
    secondary_muscles = db.Column(db.Text)  # JSON list
    instructions = db.Column(db.Text)  # JSON list of step strings
    source = db.Column(db.String(50), default="manual")
    is_cardio = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    workout_exercises = db.relationship("WorkoutExercise", backref="exercise", lazy=True)
    equipment = db.relationship("Equipment", secondary="equipment_exercises", backref="exercises")
    preferences = db.relationship("ExercisePreference", backref="exercise", lazy=True)

    def __repr__(self):
        return f"<Exercise {self.name}>"


class Equipment(db.Model):
    """Gym equipment (machines, free weights, cardio, etc.)."""
    __tablename__ = "equipment"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    manufacturer = db.Column(db.String(100))
    model = db.Column(db.String(100))
    category = db.Column(db.String(50))  # 'machine', 'free_weight', 'cardio', 'bodyweight'
    muscle_group = db.Column(db.String(100))
    gym_location = db.Column(db.String(200))
    qr_code = db.Column(db.String(500))
    qr_url = db.Column(db.String(500))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("name", "manufacturer", "model"),
    )

    # Relationships
    workout_exercises = db.relationship("WorkoutExercise", backref="equipment", lazy=True)
    profile = db.relationship("EquipmentProfile", backref="equipment", uselist=False, lazy=True)

    def __repr__(self):
        return f"<Equipment {self.name}>"


class EquipmentProfile(db.Model):
    """Rich training details for a piece of equipment.

    Holds information for weight machines (muscles used, supported exercises)
    and cardio machines (program modes, etc.). Can be linked to an Equipment
    entry or exist independently for machines not yet in the equipment list.

    This data is meant to be interrogated by the LLM later and surfaced when
    logging exercises.
    """
    __tablename__ = "equipment_profiles"

    id = db.Column(db.Integer, primary_key=True)

    # Optional link to an Equipment entry
    equipment_id = db.Column(db.Integer, db.ForeignKey("equipment.id"),
                             nullable=True, unique=True)

    # Machine type: 'weight', 'cardio', 'functional', 'free_weight'
    machine_type = db.Column(db.String(50), nullable=False)

    # Human-readable name (useful if not linked to Equipment)
    name = db.Column(db.String(200))

    # Muscles used (JSON array of strings)
    muscles_used = db.Column(db.Text)

    # Supported exercise types (JSON array of strings)
    supported_exercises = db.Column(db.Text)

    # Program modes for cardio machines (JSON array of strings)
    program_modes = db.Column(db.Text)

    # Additional details (JSON object)
    details = db.Column(db.Text)

    # Source: 'manufacturer_manual', 'technogym_website', 'manual_entry'
    source = db.Column(db.String(100))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<EquipmentProfile {self.name or self.machine_type}>"


class SleepRecord(db.Model):
    """Sleep sessions, currently from Health Connect CSV exports.

    The Fit3 fragments sleep into several sessions per night and rarely
    reports REM, so rows are stored as-reported — one row per session, never
    merged. Merging fragmented nights is a presentation concern, not a storage
    one; the raw sessions must survive for the charts to be honest.
    """
    __tablename__ = "sleep_records"

    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    started_at = db.Column(db.DateTime, nullable=False)
    ended_at = db.Column(db.DateTime)
    light_min = db.Column(db.Integer)
    deep_min = db.Column(db.Integer)
    rem_min = db.Column(db.Integer)
    awake_min = db.Column(db.Integer)
    source = db.Column(db.String(50), default="health_connect_csv")
    source_id = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("source", "source_id"),
    )

    def __repr__(self):
        return f"<SleepRecord {self.started_at}>"


class Workout(db.Model):
    """A gym workout session."""
    __tablename__ = "workouts"

    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey("activities.id"))
    workout_name = db.Column(db.String(200))
    started_at = db.Column(db.DateTime, nullable=False)
    ended_at = db.Column(db.DateTime)
    duration_seconds = db.Column(db.Integer)
    total_moves = db.Column(db.Integer)
    notes = db.Column(db.Text)
    source = db.Column(db.String(50), default="manual")
    source_id = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("source", "source_id"),
    )

    # Relationships
    exercises = db.relationship("WorkoutExercise", backref="workout", lazy=True, order_by="WorkoutExercise.exercise_order")
    activity = db.relationship("Activity", backref="workouts")

    def __repr__(self):
        return f"<Workout {self.workout_name} at {self.started_at}>"


class WorkoutExercise(db.Model):
    """An exercise performed within a workout."""
    __tablename__ = "workout_exercises"

    id = db.Column(db.Integer, primary_key=True)
    workout_id = db.Column(db.Integer, db.ForeignKey("workouts.id"), nullable=False)
    exercise_id = db.Column(db.Integer, db.ForeignKey("exercises.id"))
    equipment_id = db.Column(db.Integer, db.ForeignKey("equipment.id"))
    exercise_name = db.Column(db.String(200))  # denormalized from source
    equipment_name = db.Column(db.String(200))  # denormalized from source
    machine = db.Column(db.String(200))  # Technogym machine name
    resistance_type = db.Column(db.String(50))
    duration_seconds = db.Column(db.Integer)
    calories = db.Column(db.Float)
    moves = db.Column(db.Integer)
    compliance = db.Column(db.Float)
    total_weight_kg = db.Column(db.Float)
    exercise_order = db.Column(db.Integer, default=0)
    source = db.Column(db.String(50), default="manual")
    source_id = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("workout_id", "exercise_order", "source", "source_id"),
    )

    # Relationships
    sets = db.relationship("Set", backref="workout_exercise", lazy=True, order_by="Set.set_number")

    def __repr__(self):
        return f"<WorkoutExercise {self.exercise_name}>"


class Set(db.Model):
    """An individual set within a workout exercise."""
    __tablename__ = "sets"

    id = db.Column(db.Integer, primary_key=True)
    workout_exercise_id = db.Column(db.Integer, db.ForeignKey("workout_exercises.id"), nullable=False)
    set_number = db.Column(db.Integer, nullable=False)
    reps_target = db.Column(db.Integer)
    reps_actual = db.Column(db.Integer)
    weight_kg_target = db.Column(db.Float)
    weight_kg_actual = db.Column(db.Float)
    compliance_target = db.Column(db.Float)
    compliance_actual = db.Column(db.Float)
    source = db.Column(db.String(50), default="manual")
    source_id = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("workout_exercise_id", "set_number", "source", "source_id"),
    )

    def __repr__(self):
        return f"<Set {self.set_number}: {self.reps_actual}reps @ {self.weight_kg_actual}kg>"


class ExercisePreference(db.Model):
    """User preferences for exercises (like, dislike, avoid, etc.)."""
    __tablename__ = "exercise_preferences"

    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    exercise_id = db.Column(db.Integer, db.ForeignKey("exercises.id"), nullable=False)
    preference = db.Column(db.String(20), default="neutral")  # 'preferred', 'neutral', 'disliked', 'avoid', 'cannot_do'
    reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("person_id", "exercise_id"),
    )

    def __repr__(self):
        return f"<ExercisePreference {self.exercise_id}: {self.preference}>"


class EquipmentExercise(db.Model):
    """Mapping between equipment and exercises they support."""
    __tablename__ = "equipment_exercises"

    equipment_id = db.Column(db.Integer, db.ForeignKey("equipment.id"), primary_key=True)
    exercise_id = db.Column(db.Integer, db.ForeignKey("exercises.id"), primary_key=True)


class ImportLog(db.Model):
    """Log of imported records for idempotency."""
    __tablename__ = "import_log"

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(50), nullable=False)
    source_id = db.Column(db.String(100), nullable=False)
    imported_at = db.Column(db.DateTime, default=datetime.utcnow)
    record_type = db.Column(db.String(50))
    record_id = db.Column(db.Integer)
    action = db.Column(db.String(20))  # 'created', 'updated', 'skipped'

    __table_args__ = (
        db.UniqueConstraint("source", "source_id", "record_type"),
    )

    def __repr__(self):
        return f"<ImportLog {self.source}:{self.source_id} {self.action}>"
