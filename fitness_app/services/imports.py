"""Run a named importer and describe what happened.

Why this module exists
----------------------
Imports can be started from three places: the import dashboard, a button on the
log-workout page, and a scheduled script on the Pi. All three need the same
things — the same availability checks, the same messages, the same
created/skipped/failed wording. Duplicating that in each place is how the three
drift apart and start lying to the user ("imported 0 records" meaning "already
imported" in one place and "no data found" in another).

So the logic lives here once. Routes flash :func:`messages`; the CLI script prints
them and writes them to a log file.

Idempotency
-----------
Every importer is safe to run repeatedly, so running all of them on a schedule is
expected rather than risky. Two independent mechanisms guarantee it:

1. **``ImportLog``** — each importer writes one row per record it creates, keyed
   by ``(source, source_id, record_type)``. :meth:`check_already_imported`
   consults it and skips the record.

2. **A database unique constraint** on
   ``body_measurements(person_id, measured_at, measurement_type, source, source_id)``
   — a backstop for the Wii Fit case where the same body test appears in more than
   one save file.

Both are checked *before* a row is written, which is why a second run reports
"already imported" rather than duplicating anything.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

from ..importers.base import ImportResult
from ..importers.health_connect_csv import HealthConnectCsvImporter
from ..importers.technogym import TechnogymImporter
from ..importers.technogym_manual import TechnogymManualImporter
from ..importers.wii_fit import WiiFitImporter

# Message levels, matching the Flask flash categories used by the routes.
INFO = "info"
SUCCESS = "success"
WARNING = "warning"
ERROR = "error"


class ImportUnavailable(Exception):
    """Raised when a source cannot be reached at all.

    This is deliberately distinct from an import that ran and failed. A missing
    save-file folder or absent credentials means "there was nothing to import
    from", not "the import broke", and the two deserve different messages.

    Args:
        source: The source key, e.g. ``"wii_fit"``.
        reason: Human-readable explanation of what was missing.
    """

    def __init__(self, source: str, reason: str):
        super().__init__(reason)
        self.source = source
        self.reason = reason


def _run_wii_fit(**kwargs) -> ImportResult:
    """Import Wii Fit save files.

    Raises:
        ImportUnavailable: If no folder containing ``FitPlus*.dat`` can be found.
    """
    importer = WiiFitImporter()

    if not importer.is_available():
        raise ImportUnavailable(
            "wii_fit",
            f"No Wii Fit source folder found. Looked for {importer.data_dir}. "
            f"Set WII_FIT_SOURCE_PATH in your .env file, or upload the files.",
        )

    if not importer.find_save_files():
        raise ImportUnavailable(
            "wii_fit",
            f"No FitPlus*.dat files in {importer.data_dir}. "
            f"Copy or upload your Wii Fit save files there.",
        )

    return importer.import_data(**kwargs)


def _run_technogym(days: int = 30, **kwargs) -> ImportResult:
    """Import from the live mywellness.com API.

    Raises:
        ImportUnavailable: If credentials are not configured.
    """
    if not (os.environ.get("MYWELLNESS_EMAIL") and os.environ.get("MYWELLNESS_PASSWORD")):
        raise ImportUnavailable(
            "technogym",
            "MYWELLNESS_EMAIL / MYWELLNESS_PASSWORD are not set. "
            "Add them to your .env file to import from the gym portal.",
        )

    importer = TechnogymImporter()
    # The importer holds an open HTTP client; make sure it is closed even if the
    # import raises part-way through.
    try:
        return importer.import_data(
            from_date=date.today() - timedelta(days=days),
            to_date=date.today(),
            **kwargs,
        )
    finally:
        importer.close()


def _run_technogym_manual(**kwargs) -> ImportResult:
    """Import the manually downloaded JSON export from mywellness.com."""
    return TechnogymManualImporter().import_data(**kwargs)


def _run_health_connect_csv(**kwargs) -> ImportResult:
    """Import Health Data Export CSV files (Health Connect via phone app).

    Raises:
        ImportUnavailable: If the folder holds no CSV files.
    """
    importer = HealthConnectCsvImporter()

    if not importer.is_available():
        raise ImportUnavailable(
            "health_connect_csv",
            f"No CSV files in {importer.data_dir}. "
            f"Export from the Health Data Export app and copy the files there, "
            f"or upload them on the import page.",
        )

    return importer.import_data(**kwargs)


#: Source key -> (runner, label used in messages).
RUNNERS = {
    "wii_fit": (_run_wii_fit, "Wii Fit"),
    "technogym": (_run_technogym, "Technogym"),
    "technogym_manual": (_run_technogym_manual, "Technogym export"),
    "health_connect_csv": (_run_health_connect_csv, "Health Connect CSV"),
}

#: Every source, in the order a scheduled run should process them.
ALL_SOURCES = ("technogym", "wii_fit", "technogym_manual", "health_connect_csv")


def run_import(source: str, **kwargs) -> ImportResult:
    """Run one importer by key.

    Args:
        source: One of the keys in :data:`RUNNERS`.
        **kwargs: Passed through to the importer.

    Returns:
        The ImportResult.

    Raises:
        ValueError: If ``source`` is not a known key.
        ImportUnavailable: If the source cannot be reached.
    """
    if source not in RUNNERS:
        raise ValueError(
            f"Unknown source {source!r}. Valid sources: {', '.join(RUNNERS)}"
        )
    runner, label = RUNNERS[source]
    result = runner(**kwargs)
    # Stamp the human label here, because two importers can share one `source`
    # key and their messages still have to be distinguishable.
    result.label = label
    return result


def label_for(source: str) -> str:
    """Return the display name for a source key.

    Args:
        source: Key from :data:`RUNNERS`.

    Returns:
        e.g. ``"Wii Fit"``.
    """
    return RUNNERS.get(source, (None, source))[1]


def messages(result: ImportResult) -> list[tuple[str, str]]:
    """Turn an ImportResult into ``(level, text)`` pairs ready to display.

    Ordering is deliberate: conflicts first, because they need a decision; then
    errors; then the headline count; then routine notes. A user scanning the
    output should meet anything requiring action first.

    The wording distinguishes the three outcomes that are easy to conflate:

    - ``records_created`` > 0  — genuinely new data arrived.
    - ``records_created`` == 0 and ``records_skipped`` > 0 — the source was read
      successfully and everything in it was already stored. This is the normal
      result of a second run and is *not* a problem.
    - neither — the source was read but held nothing we can use.

    Args:
        result: What an importer returned.

    Returns:
        List of ``(level, text)`` tuples. ``level`` is one of
        ``"error"``, ``"warning"``, ``"success"``, ``"info"``.
    """
    out: list[tuple[str, str]] = []

    # Anything needing a decision comes before anything else.
    out.extend((WARNING, text) for text in result.conflicts)
    out.extend((ERROR, text) for text in result.errors)

    label = result.label or label_for(result.source)
    noun = "measurement" if "wii_fit" in result.source else "record"
    created = result.records_created
    updated = result.records_updated
    skipped = result.records_skipped

    # Only describe what actually happened. An import that creates nothing new but
    # refreshed an existing row is an update, not a success with new data - saying
    # "imported 1 new record" for a profile timestamp touch would be a lie.
    if created > 0:
        detail = f" ({skipped} already imported)" if skipped else ""
        out.append((
            SUCCESS,
            f"Imported {created} new {noun}{'s' if created != 1 else ''} "
            f"from {label}{detail}.",
        ))
    elif updated > 0:
        out.append((
            SUCCESS,
            f"Updated {updated} existing {noun}{'s' if updated != 1 else ''} "
            f"from {label} - nothing new to add.",
        ))
    elif skipped > 0:
        out.append((
            INFO,
            f"Nothing new from {label} - all {skipped} "
            f"{noun}{'s are' if skipped != 1 else ' is'} already imported.",
        ))
    else:
        out.append((
            WARNING,
            f"No usable {noun}s found in the {label} source.",
        ))

    out.extend((INFO, text) for text in result.notes)

    return out
