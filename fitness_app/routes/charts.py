"""Chart data API endpoints.

Provides data for Chart.js visualizations:
- Weight over time
- BMI over time
- Activity duration/calories over time
- Summary statistics
- Body measurement conflicts awaiting a decision

All body measurement endpoints delegate to
:mod:`fitness_app.services.measurements`, which owns the rules about which
readings are current and which the user has chosen to ignore. These routes only
shape the result for JSON.
"""

from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request
from ..models import db, Activity, Workout
from ..services import measurements as measurement_service

charts_bp = Blueprint("charts", __name__)


def _series_payload(measurement_type: str) -> dict:
    """Build the JSON payload for one measurement type's chart.

    Args:
        measurement_type: e.g. ``"weight"`` or ``"bmi"``.

    Returns:
        Dict with ``labels``, ``values``, ``sources``, ``ids``, ``superseded``
        and ``include_superseded``.
    """
    include_superseded = request.args.get("include_superseded", "false").lower() == "true"
    points = measurement_service.series(
        measurement_type, include_superseded=include_superseded
    )

    return {
        "labels": [point["date"] for point in points],
        "values": [point["value"] for point in points],
        "sources": [point["source"] for point in points],
        # Full timestamp, not just the date: several readings can share a day.
        "times": [point["time"] for point in points],
        "ids": [point["id"] for point in points],
        "superseded": [point["superseded"] for point in points],
        "include_superseded": include_superseded,
    }


@charts_bp.route("/weight")
def weight_data():
    """Return weight measurements over time.

    Query args:
        include_superseded: ``true`` to also include readings the user has
            chosen to ignore, so they can be reviewed.
    """
    return jsonify(_series_payload("weight"))


@charts_bp.route("/bmi")
def bmi_data():
    """Return BMI measurements over time.

    Query args:
        include_superseded: ``true`` to also include ignored readings.
    """
    return jsonify(_series_payload("bmi"))


@charts_bp.route("/activities")
def activities_data():
    """Return activity data over time."""
    # Get query parameters
    days = request.args.get("days", 90, type=int)
    activity_type = request.args.get("type", "all")

    query = Activity.query

    if activity_type != "all":
        query = query.filter_by(activity_type=activity_type)

    # Filter by date range
    from_date = datetime.utcnow() - timedelta(days=days)
    query = query.filter(Activity.started_at >= from_date)

    activities = query.order_by(Activity.started_at).all()

    data = [{
        "date": a.started_at.strftime("%Y-%m-%d"),
        "type": a.activity_type,
        "duration": a.duration_seconds or 0,
        "calories": a.calories or 0,
        "distance": a.distance_m or 0,
    } for a in activities]

    return jsonify({
        "labels": [d["date"] for d in data],
        "durations": [d["duration"] for d in data],
        "calories": [d["calories"] for d in data],
        "distances": [d["distance"] for d in data],
        "types": [d["type"] for d in data],
    })


@charts_bp.route("/conflicts")
def conflicts_data():
    """Return body measurement conflicts that still need a decision.

    Nothing is ever superseded automatically, so this is the list of days where
    sources disagree and the user has not yet picked a value.
    """
    conflicts = measurement_service.find_conflicts()

    return jsonify({
        "conflicts": [
            {
                "measurement_type": conflict.measurement_type,
                "day": conflict.day.isoformat(),
                "spread": round(conflict.spread, 2),
                "sources": conflict.sources,
                "readings": [
                    {
                        "id": reading.id,
                        "value": reading.value,
                        "unit": reading.unit,
                        "source": reading.source,
                        "time": reading.measured_at.strftime("%H:%M"),
                    }
                    for reading in conflict.readings
                ],
            }
            for conflict in conflicts
        ],
        "count": len(conflicts),
    })


@charts_bp.route("/summary")
def summary_data():
    """Return summary statistics for dashboard."""
    # Total workouts
    total_workouts = Workout.query.count()

    # Total activities
    total_activities = Activity.query.count()

    # Total duration (minutes)
    total_duration = db.session.query(
        db.func.sum(Activity.duration_seconds)
    ).scalar() or 0

    # Total calories
    total_calories = db.session.query(
        db.func.sum(Activity.calories)
    ).scalar() or 0

    # Current weight and BMI, honouring any decisions the user has made.
    current = measurement_service.current_values()
    latest_weight = current.get("weight")
    latest_bmi = current.get("bmi")

    # Activities by type
    activity_types = db.session.query(
        Activity.activity_type,
        db.func.count(Activity.id)
    ).group_by(Activity.activity_type).all()

    # Open conflicts the user has not settled yet.
    open_conflicts = measurement_service.find_conflicts()

    return jsonify({
        "total_workouts": total_workouts,
        "total_activities": total_activities,
        "total_duration_minutes": round(total_duration / 60),
        "total_calories": round(total_calories),
        "latest_weight": latest_weight.value if latest_weight else None,
        "latest_weight_date": latest_weight.measured_at.strftime("%Y-%m-%d") if latest_weight else None,
        "latest_weight_source": latest_weight.source if latest_weight else None,
        "latest_bmi": latest_bmi.value if latest_bmi else None,
        "latest_bmi_date": latest_bmi.measured_at.strftime("%Y-%m-%d") if latest_bmi else None,
        "latest_bmi_source": latest_bmi.source if latest_bmi else None,
        "activity_types": {t: c for t, c in activity_types},
        "open_conflicts": len(open_conflicts),
    })