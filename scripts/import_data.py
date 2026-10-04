"""Import new data from every configured source, on demand or on a schedule.

This is the script to point cron (or Task Scheduler) at. It shares its logic with
the web import buttons via :mod:`fitness_app.services.imports`, so a scheduled run
and a button press import exactly the same things and report them the same way.

It needs no web server and does not start Flask's dev server - it builds an
application context, runs the importers, prints a summary, and exits. That makes
it safe to run when nothing else is using the app.

Running every importer is safe at any time. Each one skips records it has already
stored, so a daily job costs a few seconds and produces no duplicates. See
``documentation/IMPORTING.md``.

Usage
-----
    # Everything (this is what the daily job runs)
    py scripts/import_data.py

    # One source
    py scripts/import_data.py --source wii_fit

    # How far back the Technogym API is asked for
    py scripts/import_data.py --source technogym --days 90

    # Just check it works, change nothing (used by the troubleshooting steps)
    py scripts/import_data.py --dry-run

    # Skip the log file, for a one-off manual run
    py scripts/import_data.py --no-log

Exit codes
----------
    0   every source either imported cleanly or had nothing new
    1   at least one source failed or was unreachable

A source being unreachable is reported as a failure so that a cron job surfaces
it, but the other sources are still attempted - one broken source must not stop
the rest.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Allow running as `py scripts/import_data.py` from anywhere by putting the
# project root on the import path before touching the application package.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fitness_app import create_app                                  # noqa: E402
from fitness_app.services import imports as import_service          # noqa: E402

# Where the rolling log is written. Matches the project's `log/` convention.
LOG_DIR = PROJECT_ROOT / "log"
LOG_FILE = LOG_DIR / "import.log"

logger = logging.getLogger("import_data")


def configure_logging(to_file: bool, verbose: bool) -> None:
    """Set up console output and, optionally, the rolling log file.

    Args:
        to_file: Also append to ``log/import.log``.
        verbose: Emit INFO-level records rather than only warnings and errors.
    """
    level = logging.INFO if verbose else logging.WARNING

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if to_file:
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(LOG_FILE, encoding="utf-8"))
        except OSError as error:
            # Never fail the import just because a log file cannot be opened.
            print(f"Warning: could not open {LOG_FILE} ({error}); "
                  f"logging to the console only.", file=sys.stderr)

    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )


def report(label: str, lines: list[tuple[str, str]], log) -> None:
    """Print and log the outcome of one source.

    Args:
        label: Display name of the source.
        lines: ``(level, text)`` pairs from
            :func:`fitness_app.services.imports.messages`.
        log: Callable taking a single message string, used for the log file.
    """
    for level, text in lines:
        marker = {
            "success": "+",
            "info": "=",
            "warning": "!",
            "error": "x",
        }.get(level, " ")
        print(f"  [{marker}] {text}")
        log(f"{label}: [{level}] {text}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list. Defaults to ``sys.argv[1:]``.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(
        prog="import_data.py",
        description="Import new data from Technogym and Wii Fit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exit codes:\n"
            "  0  every source imported cleanly or had nothing new\n"
            "  1  at least one source failed or was unreachable\n"
        ),
    )

    parser.add_argument(
        "--source",
        choices=[*import_service.RUNNERS, "all"],
        default="all",
        help="Which source to import. 'all' (default) runs every one.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help=(
            "How many days of Technogym history to request. Only affects the "
            "live API source. Default: %(default)s"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Report whether each source is reachable without importing "
            "anything. Useful for diagnosing a scheduled job."
        ),
    )
    parser.add_argument(
        "--no-log",
        action="store_true",
        help="Do not append to log/import.log.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show INFO-level logging.",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Argument list. Defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code: 0 on success, 1 if any source failed.
    """
    args = parse_args(argv)
    configure_logging(to_file=not args.no_log, verbose=args.verbose)

    sources = (
        list(import_service.ALL_SOURCES)
        if args.source == "all"
        else [args.source]
    )

    started = datetime.now()
    print(f"Fitness Tracker import - started {started:%Y-%m-%d %H:%M:%S}")
    print(f"Sources: {', '.join(import_service.label_for(s) for s in sources)}")
    if args.dry_run:
        print("Mode: DRY RUN (nothing will be imported)")
    print()

    app = create_app()

    def log(message: str) -> None:
        logger.info(message)

    failures = 0

    with app.app_context():
        if args.dry_run:
            failures = _dry_run(sources, log)
        else:
            failures = _run(sources, args.days, log)

    finished = datetime.now()
    duration = (finished - started).total_seconds()

    print()
    print(f"Finished {finished:%Y-%m-%d %H:%M:%S} in {duration:.1f}s")

    if not args.no_log:
        print(f"Log: {LOG_FILE}")

    if failures:
        print(f"Completed with {failures} problem(s).")
        return 1

    print("All sources OK.")
    return 0


def _run(sources: list[str], days: int, log) -> int:
    """Run each source and report. Returns the number that failed.

    Args:
        sources: Source keys to run.
        days: Technogym history window.
        log: Callable used to write to the log file.

    Returns:
        Count of sources that raised or reported an error.
    """
    failures = 0

    for source in sources:
        label = import_service.label_for(source)
        print(f"{label}")

        kwargs = {"days": days} if source == "technogym" else {}
        log(f"--- {label} ---")

        try:
            result = import_service.run_import(source, **kwargs)
        except import_service.ImportUnavailable as unavailable:
            # The source could not be reached at all - no folder, no credentials.
            # Worth a non-zero exit so a scheduled job surfaces it.
            print(f"  [!] {unavailable.reason}")
            log(f"{label}: [warning] unavailable - {unavailable.reason}")
            failures += 1
            continue
        except Exception as exc:  # noqa: BLE001 - keep going through the sources
            print(f"  [x] {label} raised {type(exc).__name__}: {exc}")
            log(f"{label}: [error] {type(exc).__name__}: {exc}")
            failures += 1
            continue

        lines = import_service.messages(result)
        report(label, lines, log)

        if result.errors:
            failures += 1

        print()

    return failures


def _dry_run(sources: list[str], log) -> int:
    """Check that each source is reachable, importing nothing.

    Args:
        sources: Source keys to check.
        log: Callable used to write to the log file.

    Returns:
        Count of unreachable sources.
    """
    from fitness_app.importers.wii_fit import WiiFitImporter

    unreachable = 0

    for source in sources:
        label = import_service.label_for(source)

        if source == "wii_fit":
            importer = WiiFitImporter()
            files = importer.find_save_files()
            ok = importer.is_available() and bool(files)
            detail = (
                f"{len(files)} save file(s) in {importer.data_dir}"
                if ok
                else f"no save files found in {importer.data_dir}"
            )
        elif source == "technogym":
            has_creds = bool(
                os.environ.get("MYWELLNESS_EMAIL")
                and os.environ.get("MYWELLNESS_PASSWORD")
            )
            ok = has_creds
            detail = (
                "credentials present"
                if ok
                else "MYWELLNESS_EMAIL / MYWELLNESS_PASSWORD not set"
            )
        else:
            export_dir = PROJECT_ROOT / "data" / "technogym_export"
            files = list(export_dir.glob("*.json")) if export_dir.is_dir() else []
            ok = bool(files)
            detail = (
                f"{len(files)} JSON file(s) in {export_dir}"
                if ok
                else f"no JSON export files in {export_dir}"
            )

        marker = "+" if ok else "!"
        print(f"{label:<18} [{marker}] {detail}")
        log(f"dry run: {label} [{'ok' if ok else 'unreachable'}] {detail}")

        if not ok:
            unreachable += 1

    return unreachable


if __name__ == "__main__":
    sys.exit(main())
