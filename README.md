# Personal Fitness Tracker

A local-first fitness tracking system that brings together data from multiple sources (Technogym, Wii Fit, Samsung Health) into one database, accessible through a single web interface.

## Quick Start (Development)

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Create .env file:**
   ```bash
   copy .env.example .env
   ```
   Edit `.env` with your credentials.

3. **Run the app:**
   ```bash
   python -m fitness_app
   ```

4. **Open in browser:**
   http://localhost:5000

## Docker Deployment (Raspberry Pi)

One-click deploy from Windows:

```bat
deploy-to-pi.bat
```

This copies the app code to `/opt/stacks/python/scripts/fitness-tracker/` on
the Pi (192.168.0.97) and rebuilds the `fitness-web` container.

**First-time setup on the Pi** - create the folder and its `.env` once:

```bash
ssh grahamsshaw@192.168.0.97
mkdir -p /opt/stacks/python/scripts/fitness-tracker/data
cd /opt/stacks/python/scripts/fitness-tracker
nano .env      # SECRET_KEY, MYWELLNESS_EMAIL, MYWELLNESS_PASSWORD, FITNESS_HOST_PORT
```

`.env` is never overwritten by the deploy script, and `data/` (the SQLite
database) survives every rebuild.

**Access:** http://192.168.0.97:5000

Full details, day-to-day commands, SSH-key setup and troubleshooting are in
[`documentation/DEPLOYMENT.md`](documentation/DEPLOYMENT.md).

## Project Structure

```
fitness_app/
├── __init__.py          # Flask app factory
├── __main__.py          # Entry point (env-driven host/port/debug)
├── config.py            # Configuration
├── migrations.py        # Idempotent schema upgrades (ALTER TABLE)
├── models.py            # SQLAlchemy models
├── importers/           # Data importers (independent + idempotent)
│   ├── base.py
│   ├── wii_fit.py
│   ├── technogym.py
│   └── technogym_manual.py
├── services/            # Domain logic, shared by routes, importers and scripts
│   ├── measurements.py  # Body measurement conflicts and current values
│   └── imports.py       # Runs an importer by name; shared wording for all callers
├── routes/              # Flask blueprints
│   ├── main.py          # Dashboard, profile, history, activities
│   ├── api.py           # REST API
│   ├── charts.py        # JSON data for the charts
│   ├── workouts.py      # Workout management
│   ├── equipment.py     # Equipment management
│   └── imports.py       # Import triggers
├── templates/           # Jinja2 templates
└── static/              # CSS, Chart.js rendering

scripts/
└── import_data.py       # Scheduled/manual import; what cron or Task Scheduler runs
deploy-to-pi.bat         # One-click deploy + Docker rebuild on the Pi
THIRD-PARTY-NOTICES.md   # MIT data/artwork attributions; what is NOT reused and why
documentation/
├── BODY-MEASUREMENTS.md # Weight/BMI conflict handling
├── DEPLOYMENT.md        # Full Pi deployment guide
└── IMPORTING.md         # Data sources, import buttons, daily job, duplicate checks
```

## Features

**Core**
- User profile management
- Equipment database with QR code support
- Exercise library
- Workout logging (exercises, sets, reps, weight)
- Workout history with pagination
- Dashboard with quick stats

**Charts**
- Weight over time and BMI over time (Profile page)
- Activity duration, calories and activity types (Activities page)
- Manual weight entry, so the charts are useful even with no imports
- Chart.js fed by `/api/charts/*` - no build step, easy to add more charts
- Current weight and BMI always shown with the source they came from

**Body measurements**
- Imports are checked against other sources for the same day, and any
  disagreement is reported rather than resolved automatically
- Every reading is kept - you pick which value to use for a disputed day on the
  profile page, and can change your mind later
- Manual weight entry derives BMI from your recorded height
- See `documentation/BODY-MEASUREMENTS.md`

**Muscles and exercise library**
- 1,300+ exercise library with instructions, target and secondary muscles
  (MIT-licensed ExerciseDB metadata - see `THIRD-PARTY-NOTICES.md`)
- Clickable body map: fatigue (how recently trained - high means rest) and
  strength (retained training) per muscle, plus the neglected list
- Equipment pages show a mini muscle map of what each machine works
- Clicking a muscle shows what trained it and when

**Imports**
- Wii Fit Plus save files (weight, BMI, balance)
- Technogym / Mywellness live API
- Technogym manual JSON export
- Each importer is standalone, idempotent, and keeps `source` / `source_id`
- Buttons on the log workout page pull in a session straight after finishing it
- `py scripts/import_data.py` runs everything from a terminal or a scheduler
- See `documentation/IMPORTING.md`

## Future Phases

- Phase 4: Android app + Health Connect sync
- Phase 5: LLM-powered workout suggestions (optional, additive)
