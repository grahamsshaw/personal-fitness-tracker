"""Personal Fitness Tracker - Flask application factory."""

import json
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

db = SQLAlchemy()

# Absolute path to the data directory (project root / data)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(BASE_DIR, "data")


def _fromjson(value):
    """Jinja filter: parse a JSON string, returning None when empty or invalid.

    Used by the equipment profile templates to unpack JSON columns for display.

    Args:
        value: A JSON string, or None.

    Returns:
        The parsed value, or None.
    """
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def create_app(config=None):
    """Application factory pattern."""
    app = Flask(__name__)

    # Load .env file
    load_dotenv()

    # Ensure data directory exists before any DB operations
    os.makedirs(DATA_DIR, exist_ok=True)

    # Default configuration
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
    db_path = os.path.join(DATA_DIR, "fitness.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", f"sqlite:///{db_path}"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Override with provided config
    if config:
        app.config.update(config)

    # Register custom Jinja filters
    app.jinja_env.filters["fromjson"] = _fromjson

    # Initialize extensions
    db.init_app(app)

    # Register blueprints
    from .routes.main import main_bp
    from .routes.api import api_bp
    from .routes.workouts import workouts_bp
    from .routes.equipment import equipment_bp
    from .routes.imports import imports_bp
    from .routes.charts import charts_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(workouts_bp, url_prefix="/workouts")
    app.register_blueprint(equipment_bp, url_prefix="/equipment")
    app.register_blueprint(imports_bp, url_prefix="/imports")
    app.register_blueprint(charts_bp, url_prefix="/api/charts")

    # Create tables for anything not yet present, then bring existing tables up
    # to date. create_all() alone will not add a column to a table that
    # already exists, which would leave new fields silently missing on an
    # established database.
    #
    # Imported here rather than at module scope because migrations.py needs the
    # `db` object defined above, and importing it at the top would be circular.
    from .migrations import apply_migrations

    with app.app_context():
        db.create_all()
        apply_migrations()

    return app
