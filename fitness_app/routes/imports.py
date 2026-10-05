"""Import routes: trigger data imports from various sources.

These routes are thin. The actual work lives in
:mod:`fitness_app.services.imports`, which is shared with the scheduled import
script so the web buttons and the cron job behave identically. Here we only:

- validate the request,
- flash whatever the shared runner produced,
- decide where to send the browser afterwards.

The ``next`` form field lets a button on the log-workout page return the user to
that page instead of bouncing them to the import dashboard.
"""

import os
from datetime import date, timedelta
from urllib.parse import urlparse

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from ..models import db, BodyMeasurement, ImportLog
from ..services import imports as import_service

imports_bp = Blueprint("imports", __name__)


def wii_fit_upload_dir() -> str:
    """Folder that receives manually uploaded / hand-copied Wii Fit files.

    This is always the project's own ``data/wii_fit`` folder so that uploads
    work even when the importer is pointed at a network share.

    Returns:
        Absolute path to the upload folder (created if missing).
    """
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    upload_dir = os.path.join(base_dir, "data", "wii_fit")
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


def safe_next_url(candidate: str | None, default_endpoint: str = "imports.import_dashboard") -> str:
    """Resolve a ``next`` form field to a URL inside this app.

    Import buttons appear on more than one page, so they submit where they came
    from. Without this check, a crafted ``?next=https://evil.example`` would turn
    a routine import into an open redirect.

    Only same-host absolute paths are honoured; anything with a scheme or a netloc
    (``//evil.example`` and ``https://evil.example`` alike) is rejected.

    Args:
        candidate: Raw value of the ``next`` field, if the button supplied one.
        default_endpoint: Where to send the browser when the field is absent or
            rejected.

    Returns:
        A URL safe to redirect to.
    """
    fallback = url_for(default_endpoint)

    if not candidate:
        return fallback

    parsed = urlparse(candidate)

    # Reject absolute URLs, protocol-relative URLs, and anything that is not a
    # plain path.
    if parsed.scheme or parsed.netloc or not candidate.startswith("/"):
        return fallback

    return candidate


def _flash_result(result) -> None:
    """Flash the messages from a completed import.

    Args:
        result: The ImportResult returned by the shared runner.
    """
    for level, text in import_service.messages(result):
        flash(text, level)


@imports_bp.route("/")
def import_dashboard():
    """Import dashboard showing available importers and status."""
    # Get import statistics
    wii_fit_count = ImportLog.query.filter_by(source="wii_fit").count()
    technogym_count = ImportLog.query.filter_by(source="technogym").count()

    # Get recent imports
    recent_imports = ImportLog.query.order_by(ImportLog.imported_at.desc()).limit(10).all()

    # The importer resolves its own source folder (env var -> network share ->
    # local data folder), so the dashboard always shows the truth.
    from ..importers.wii_fit import WiiFitImporter
    importer = WiiFitImporter()
    wii_fit_dir = str(importer.data_dir)
    wii_fit_files = importer.find_save_files()

    # Uploads always land in the project's own folder
    upload_dir = wii_fit_upload_dir()
    upload_files = WiiFitImporter(data_dir=upload_dir).find_save_files()

    # Health Connect CSVs and workout CSVs live in their own data folders.
    from ..importers.health_connect_csv import HealthConnectCsvImporter
    from ..importers.workout_csv import GymCsvImporter
    hc_importer = HealthConnectCsvImporter()
    gym_importer = GymCsvImporter()

    return render_template(
        "import_dashboard.html",
        wii_fit_count=wii_fit_count,
        technogym_count=technogym_count,
        recent_imports=recent_imports,
        wii_fit_files=wii_fit_files or upload_files,
        wii_fit_dir=wii_fit_dir,
        wii_fit_available=importer.is_available(),
        upload_dir=upload_dir,
        hc_files=hc_importer.find_csv_files(),
        hc_dir=str(hc_importer.data_dir),
        hc_count=ImportLog.query.filter_by(source="health_connect_csv").count(),
        gym_files=gym_importer.find_csv_files(),
        gym_dir=str(gym_importer.data_dir),
        gym_count=ImportLog.query.filter_by(source="gym_csv").count(),
    )


@imports_bp.route("/wii-fit", methods=["POST"])
def import_wii_fit():
    """Import Wii Fit data from the configured source folder."""
    destination = safe_next_url(request.form.get("next"))

    try:
        result = import_service.run_import("wii_fit")
    except import_service.ImportUnavailable as unavailable:
        flash(unavailable.reason, "warning")
        return redirect(destination)

    _flash_result(result)
    return redirect(destination)


@imports_bp.route("/wii-fit/upload", methods=["POST"])
def upload_wii_fit():
    """Upload Wii Fit .dat files (always stored in the project's data folder)."""
    wii_fit_dir = wii_fit_upload_dir()

    files = request.files.getlist("wii_fit_files")
    uploaded = 0

    for file in files:
        if file and file.filename.startswith("FitPlus") and file.filename.endswith(".dat"):
            filepath = os.path.join(wii_fit_dir, file.filename)
            file.save(filepath)
            uploaded += 1

    if uploaded > 0:
        flash(f"Uploaded {uploaded} Wii Fit file(s).", "success")
    else:
        flash("No valid Wii Fit .dat files uploaded.", "warning")

    return redirect(url_for("imports.import_dashboard"))


def health_connect_upload_dir() -> str:
    """Folder receiving Health Data Export CSV files uploaded by hand.

    Always the project's own ``data/health_data_export`` folder, matching the
    CSV importer's default, so uploads work wherever the app runs.

    Returns:
        Absolute path to the upload folder (created if missing).
    """
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    upload_dir = os.path.join(base_dir, "data", "health_data_export")
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


@imports_bp.route("/health-connect-csv", methods=["POST"])
def import_health_connect_csv():
    """Import Health Data Export CSV files from the source folder."""
    destination = safe_next_url(request.form.get("next"))

    try:
        result = import_service.run_import("health_connect_csv")
    except import_service.ImportUnavailable as unavailable:
        flash(unavailable.reason, "warning")
        return redirect(destination)

    _flash_result(result)
    return redirect(destination)


@imports_bp.route("/health-connect-csv/upload", methods=["POST"])
def upload_health_connect_csv():
    """Upload Health Data Export CSV files, then import them straight away.

    Accepts the files exactly as the phone app writes them (``Activity.csv``,
    ``Sleep.csv``, ``Vitals.csv`` — anything ending in ``.csv``). Uploading
    and importing in one step matches the phone workflow: export on the phone,
    open the Pi's import page in the phone browser, upload.
    """
    upload_dir = health_connect_upload_dir()

    files = request.files.getlist("health_connect_files")
    uploaded = 0

    for file in files:
        if file and file.filename.lower().endswith(".csv"):
            # Strip any path the browser may have sent; only the base name is
            # ever written, inside our own folder.
            filename = os.path.basename(file.filename)
            if filename:
                file.save(os.path.join(upload_dir, filename))
                uploaded += 1

    if uploaded == 0:
        flash("No CSV files uploaded.", "warning")
        return redirect(url_for("imports.import_dashboard"))

    flash(f"Uploaded {uploaded} CSV file(s).", "success")

    try:
        result = import_service.run_import("health_connect_csv")
    except import_service.ImportUnavailable as unavailable:
        flash(unavailable.reason, "warning")
        return redirect(url_for("imports.import_dashboard"))

    _flash_result(result)
    return redirect(url_for("imports.import_dashboard"))


def workout_csv_upload_dir() -> str:
    """Folder receiving workout CSV files uploaded by hand.

    Always the project's own ``data/workout_csv`` folder, matching the gym
    CSV importer's default.

    Returns:
        Absolute path to the upload folder (created if missing).
    """
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    upload_dir = os.path.join(base_dir, "data", "workout_csv")
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


@imports_bp.route("/gym-csv", methods=["POST"])
def import_gym_csv():
    """Import workout CSV files (Strong, Hevy style) from the source folder."""
    destination = safe_next_url(request.form.get("next"))

    try:
        result = import_service.run_import("gym_csv")
    except import_service.ImportUnavailable as unavailable:
        flash(unavailable.reason, "warning")
        return redirect(destination)

    _flash_result(result)
    return redirect(destination)


@imports_bp.route("/gym-csv/upload", methods=["POST"])
def upload_gym_csv():
    """Upload workout CSV files, then import them straight away."""
    upload_dir = workout_csv_upload_dir()

    files = request.files.getlist("gym_csv_files")
    uploaded = 0

    for file in files:
        if file and file.filename.lower().endswith(".csv"):
            filename = os.path.basename(file.filename)
            if filename:
                file.save(os.path.join(upload_dir, filename))
                uploaded += 1

    if uploaded == 0:
        flash("No CSV files uploaded.", "warning")
        return redirect(url_for("imports.import_dashboard"))

    flash(f"Uploaded {uploaded} CSV file(s).", "success")

    try:
        result = import_service.run_import("gym_csv")
    except import_service.ImportUnavailable as unavailable:
        flash(unavailable.reason, "warning")
        return redirect(url_for("imports.import_dashboard"))

    _flash_result(result)
    return redirect(url_for("imports.import_dashboard"))


@imports_bp.route("/technogym-manual", methods=["POST"])
def import_technogym_manual():
    """Import Technogym manual export data."""
    destination = safe_next_url(request.form.get("next"))

    try:
        result = import_service.run_import("technogym_manual")
    except import_service.ImportUnavailable as unavailable:
        flash(unavailable.reason, "warning")
        return redirect(destination)

    _flash_result(result)
    return redirect(destination)


@imports_bp.route("/technogym", methods=["POST"])
def import_technogym():
    """Import Technogym data from the live mywellness.com API."""
    destination = safe_next_url(request.form.get("next"))

    # The button on the log-workout page offers a short window by default: you
    # import straight after a session, so there is no reason to walk 30 days.
    days = request.form.get("days", 30, type=int)

    try:
        result = import_service.run_import("technogym", days=days)
    except import_service.ImportUnavailable as unavailable:
        flash(unavailable.reason, "warning")
        return redirect(destination)

    _flash_result(result)
    return redirect(destination)


@imports_bp.route("/measurements")
def view_measurements():
    """View body measurements history."""
    page = request.args.get("page", 1, type=int)
    measurement_type = request.args.get("type", "all")

    query = BodyMeasurement.query

    if measurement_type != "all":
        query = query.filter_by(measurement_type=measurement_type)

    measurements = query.order_by(BodyMeasurement.measured_at.desc()).paginate(
        page=page, per_page=50, error_out=False
    )

    # Get measurement types for filter
    types = db.session.query(BodyMeasurement.measurement_type).distinct().all()
    types = [t[0] for t in types]

    return render_template(
        "measurements.html",
        measurements=measurements,
        types=types,
        current_type=measurement_type,
    )
