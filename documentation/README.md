# Documentation

Reference notes for the Personal Fitness Tracker. Written to be read later -
each file explains *why* something is set up the way it is, not just what.

| File | What it covers |
|------|----------------|
| `BODY-MEASUREMENTS.md` | Weight and BMI conflict handling: why nothing is auto-overwritten, what counts as a conflict, the schema, the HTTP surface, and how importers report a disagreement. |
| `IMPORTING.md` | Where data comes from (Technogym, Wii Fit), the import buttons, `scripts/import_data.py`, setting up the daily job, and how duplicate detection works. |
| `DEPLOYMENT.md` | Deploying to the Raspberry Pi with `deploy-to-pi.bat`: folder layout, one-time setup, day-to-day commands, SSH keys, Wii Fit files on the Pi, troubleshooting. |
| `wii fit save game data extract.url` | Shortcut to the Wii Fit save-file format documentation. |
| `Project structure.docx` | Original project structure notes. |

## Where things are

| Folder | Purpose |
|--------|---------|
| `fitness_app/` | All application code (routes, models, importers, templates, static files). |
| `scripts/` | Standalone entry points meant to be run from a terminal or a scheduler. `import_data.py` is the one. |
| `data/` | The SQLite database plus imported Wii Fit / Technogym source files. Never deployed, never in git. |
| `debug/` | One-off diagnostic scripts used while reverse-engineering file formats and APIs. See `debug/README.md`. |
| `documentation/` | This folder. |
| `log/` | Application logs, plus `import.log` written by `scripts/import_data.py`. |
| `Archive/` | Retired files, kept for reference. |
| `Resources_Archive/` | Third-party reference code that informed the importers. See `Resources_Archive/README.md`. |

## Conventions

- `.env` holds every secret and machine-specific setting. It is gitignored and
  is never copied to the Pi - the Pi keeps its own copy.
- Every importer is standalone and idempotent: re-running it never duplicates
  rows, and every row keeps its `source` and `source_id`.
- Manual entry always works. The app must stay usable with no LLM and with
  every external integration offline.
- Nothing is ever deleted or silently overwritten by an importer. Where two
  sources disagree, both readings are kept and the disagreement is surfaced for
  the user to settle. See `BODY-MEASUREMENTS.md`.
- Schema changes go through `fitness_app/migrations.py`, not just
  `db.create_all()` — `create_all()` will not add a column to a table that
  already exists.
