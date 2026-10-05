"""Health Connect receiver: accept records pushed from the phone app.

Health Connect has no server-side API, so the Pi cannot pull. Instead the
Android app reads Health Connect on-device and POSTs records here. See
``documentation/HEALTH-CONNECT.md`` for the full design.

Authentication is a static API key (``HEALTH_CONNECT_API_KEY`` in ``.env``),
sent as the ``X-API-Key`` header. Proportionate for a LAN-only endpoint
carrying the owner's own data to their own server; revisit if the endpoint is
ever exposed beyond the home network. When the key is not configured, the push
endpoint refuses everything rather than accepting unauthenticated health data.
"""

from __future__ import annotations

import os

from flask import Blueprint, jsonify, request
from ..models import ImportLog, db
from ..services import health_connect as hc

health_connect_bp = Blueprint("health_connect", __name__)

#: Header carrying the API key.
API_KEY_HEADER = "X-API-Key"


def _check_key(provided: str | None) -> tuple[bool, str]:
    """Validate the caller's API key against configuration.

    Fails closed: a missing server-side key disables the endpoint entirely,
    and a wrong caller key is rejected. Comparison uses ``hmac.compare_digest``
    so key checking does not leak prefix information through timing.

    Args:
        provided: Value of the ``X-API-Key`` header, if any.

    Returns:
        ``(True, "")`` when accepted, else ``(False, reason)``.
    """
    import hmac

    expected = os.environ.get("HEALTH_CONNECT_API_KEY", "").strip()

    if not expected:
        return False, (
            "Health Connect push is not configured: "
            "HEALTH_CONNECT_API_KEY is not set on the server."
        )

    if not provided or not hmac.compare_digest(provided, expected):
        return False, "invalid or missing API key"

    return True, ""


@health_connect_bp.route("/push", methods=["POST"])
def push():
    """Accept records pushed from the phone app.

    Request body (JSON)::

        { "records": [ { "type": ..., "source_id": ..., ... }, ... ] }

    See :mod:`fitness_app.services.health_connect` for the record shape.
    Processing is idempotent: already-stored records are skipped, so the app
    can push the same window repeatedly.

    Returns:
        ``202`` with imported/skipped/enriched counts plus any conflicts and
        errors. ``401`` when the API key is wrong or unconfigured.
    """
    accepted, reason = _check_key(request.headers.get(API_KEY_HEADER))
    if not accepted:
        return jsonify({"error": reason}), 401

    data = request.get_json(silent=True) or {}
    records = data.get("records")

    if not isinstance(records, list):
        return jsonify({"error": '"records" must be a list'}), 400

    result = hc.process_records(records)

    return jsonify({
        "imported": result["imported"],
        "skipped": result["skipped"],
        "enriched": result["enriched"],
        "conflicts": result["conflicts"],
        "errors": result["errors"],
    }), 202


@health_connect_bp.route("/status")
def status():
    """Show Health Connect sync status.

    Reports the last push time and per-action counts from ``import_log``.
    Deliberately unauthenticated and data-free: it reveals only that pushes
    happened, never any health values. Useful for the phone app to display
    "last synced …" without needing the API key.

    Returns:
        ``200`` with last-push time, total pushes and record counts.
    """
    logs = ImportLog.query.filter_by(source=hc.SOURCE).order_by(
        ImportLog.imported_at.desc()
    ).all()

    actions: dict[str, int] = {}
    for log in logs:
        actions[log.action] = actions.get(log.action, 0) + 1

    return jsonify({
        "configured": bool(os.environ.get("HEALTH_CONNECT_API_KEY", "").strip()),
        "last_push": logs[0].imported_at.isoformat() if logs else None,
        "total_records": len(logs),
        "actions": actions,
    })
