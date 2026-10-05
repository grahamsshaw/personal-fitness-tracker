# Importing data

How data gets into the app from the gym portal and from a Wii Fit console, how
to trigger it, and how to schedule it.

- [Where the data comes from](#where-the-data-comes-from)
- [Triggering an import by hand](#triggering-an-import-by-hand)
- [The scheduled script](#the-scheduled-script)
- [Setting up a daily job](#setting-up-a-daily-job)
- [Does it check for duplicates?](#does-it-check-for-duplicates)
- [Messages you might see](#messages-you-might-see)
- [Troubleshooting](#troubleshooting)
- [Known issue: two importers share one source name](#known-issue-two-importers-share-one-source-name)

## Where the data comes from

| Source | What it brings | How it is reached |
|--------|----------------|-------------------|
| **Technogym** | Gym sessions, calories, moves, per-exercise performance | Live mywellness.com JSON API. Needs `MYWELLNESS_EMAIL` and `MYWELLNESS_PASSWORD` in `.env`. |
| **Wii Fit** | Weight, BMI, balance from Body Tests | The console's save files (`FitPlus*.dat`). Reads a folder, not a network service. |
| **Technogym export** | Biometrics, indoor/outdoor sessions, profile | JSON files downloaded by hand from mywellness.com into `data/technogym_export/`. |
| **Health Connect CSV** | Daily steps/distance/calories, exercise sessions, sleep sessions, daily heart-rate summaries | CSV files exported by the Health Data Export app into `data/health_data_export/`, or uploaded on the import page. |

The first two are the ones worth automating. The Technogym export only changes
when you download a new one, and the Health Connect CSVs only change when you
export afresh, so a daily job will just skip both when there is nothing new.

### Health Connect CSV files

The Health Data Export app (Play Store) reads Health Connect on-device and
writes one CSV per category. The importer reads three of them:

- **`Activity.csv`** — one row per day per exercise session. Daily aggregates
  (steps, distance, calories) repeat on every row for the day, so the aggregate
  is stored once per date and each session separately. Exercise names carry a
  numeric type code (`"79 - Walking"`); the code is stripped for display but
  kept in the `source_id`. `"0 - Other Workout"` rows become `gym` activities —
  on this setup those are the Technogym strength sessions as Samsung Health saw
  them.
- **`Sleep.csv`** — one row per sleep session, stored as-is in
  `sleep_records`. Nights are often fragmented into several rows; they are
  deliberately not merged.
- **`Vitals.csv`** — one row per day. Daily heart-rate summaries are attached
  to the day's aggregate activity rather than stored as standalone rows.

When a pushed session overlaps a gym workout in time, the workout is enriched
(heart rate, calories, a note) instead of creating a duplicate — the gym
workout is the session, Health Connect is the physiology. See
`HEALTH-CONNECT.md`.

Device limits are visible in the data, not hidden: the Galaxy Fit3 records no
resting heart rate, HRV, oxygen or respiratory columns (all empty), and rarely
reports REM sleep. Empty columns are skipped, never zero-filled — a zero would
be a lie about your body.

### How the Wii Fit folder is chosen

The Wii Fit importer is a folder reader, so the interesting decision is *which*
folder. `WiiFitImporter` resolves it in this order, first match wins:

1. An explicit `data_dir` argument (used by the upload route).
2. `WII_FIT_SOURCE_PATH` from `.env` — this is what the Raspberry Pi uses.
3. The hard-coded SMB path to the NVIDIA Shield Pro.
4. Local fallback: `<project>/data/wii_fit`.

A candidate that does not exist is not an error; it falls through to the next one.
`is_available()` reports whether a folder was actually found, and the import
dashboard shows the resolved path so there is never any doubt which one is in use.

On the Pi, `WII_FIT_SOURCE_PATH` must point at a folder the Pi can actually reach.
A cron job cannot read the Shield's share unless it is mounted on the Pi.

## Triggering an import by hand

### From the log workout page

`/workouts/new` has an **Import from my devices** panel above the manual entry
form, because finishing a session is exactly when there is new data to pull in:

- **Import gym session (Technogym)** — asks the API for the last 7 days.
- **Import Wii Fit data** — re-reads the save-file folder.

Both return you to the log workout form afterwards, keeping anything you have
already typed. Pressing either twice is harmless.

### From the import dashboard

`/imports/` has the same actions plus the Wii Fit file uploader and the recent
import history, and it shows which folder the Wii Fit importer resolved to.

### From the command line

```
py scripts/import_data.py
```

See below for options.

## The scheduled script

`scripts/import_data.py` is the entry point for unattended runs. It needs no web
server: it builds an application context, runs the importers, prints a summary,
and exits. It shares its logic with the web buttons via
`fitness_app/services/imports.py`, so a scheduled run and a button press import
the same things and describe them the same way.

```
py scripts/import_data.py                      # everything (what the daily job runs)
py scripts/import_data.py --source wii_fit     # one source
py scripts/import_data.py --source technogym --days 90
py scripts/import_data.py --dry-run            # check reachability, import nothing
py scripts/import_data.py --no-log             # skip the log file
py -m pip install -r requirements.txt         # first time only
```

### Output

Each source reports one of four outcomes, and they are deliberately distinct:

```
Technogym
  [+] Imported 3 new records from Technogym (12 already imported).
Wii Fit
  [=] Nothing new from Wii Fit - all 8 measurements are already imported.
  [=] FitPlus2.dat holds Wii Fit's non-profile data block and contains no body tests.
```

| Marker | Meaning |
|--------|---------|
| `+` | New data arrived. |
| `=` | Read the source fine; everything in it was already stored. **This is the normal result of a second run, not a problem.** |
| `!` | Nothing usable found, or a source that needs attention (a source disagreement, or a missing source). |
| `x` | The importer raised an exception. |

Conflicts — two sources disagreeing about the same day — are reported as `!` and
told you to settle them on the profile page. Nothing is overwritten. See
`BODY-MEASUREMENTS.md`.

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Every source either imported cleanly or had nothing new. |
| `1` | At least one source failed or was unreachable. |

One broken source does not stop the others, but it does produce a non-zero exit
so a scheduler or monitoring job can notice.

### Logging

Every run appends to `log/import.log` unless `--no-log` is given. The log records
what was imported *and* what was skipped, which is what you want when asking
"did it already have that?" weeks later.

## Setting up a daily job

### On the Raspberry Pi (recommended)

The Pi runs 24/7, so this is where the job belongs — the Windows PC does not need
to be on.

```bash
ssh grahamsshaw@192.168.0.97
cd /opt/stacks/python/scripts/fitness-tracker
crontab -e
```

Add one line, using the absolute path to the interpreter in the container:

```cron
30 7 * * * cd /opt/stacks/python/scripts/fitness-tracker && /usr/bin/docker exec fitness-tracker python scripts/import_data.py --source technogym >> log/cron-import.log 2>&1
```

Notes on that line:

- `docker exec` runs it inside the running container, so it uses the same
  virtualenv, the same `.env` and the same `data/fitness.db` as the web app.
- Change `fitness-tracker` if you renamed the compose project.
- Pick a time when the gym portal is reachable and the Shield share is mounted.
- The `>>` appends stdout and stderr to `log/cron-import.log`.

If you prefer to run it outside the container, use the host's Python and set
`DATABASE_URL` to the bind-mounted database path instead.

### On Windows (Task Scheduler)

1. Open **Task Scheduler** → **Create Task**.
2. **General**: name it `Fitness Tracker import`; select *Run whether the user is
   logged on or not*.
3. **Trigger**: Daily, at your chosen time.
4. **Action**: *Start a program*, program
   `C:\Users\Graham\AppData\Local\Programs\Python\Python313\python.exe`,
   arguments
   `"C:\Users\Graham\Desktop\Personal Fitness Tracker\scripts\import_data.py"`,
   and *Start in*
   `C:\Users\Graham\Desktop\Personal Fitness Tracker`.
5. **Settings**: tick *If the task fails, restart every 1 minute*.

The "Start in" folder matters — the script resolves paths relative to itself, but
the database URI defaults to a relative `data/fitness.db`, so setting it removes a
whole class of confusing failures.

### Checking the job worked

```bash
# Did it run, and what did it say?
tail -n 20 /opt/stacks/python/scripts/fitness-tracker/log/cron-import.log

# Would it work right now, without changing anything?
docker exec fitness-tracker python scripts/import_data.py --dry-run
```

`--dry-run` is the first thing to reach for when a scheduled job has gone quiet.

## Does it check for duplicates?

**Yes, twice over, and both checks happen before anything is written.**

### 1. The `import_log` table

Every importer writes one row per record it creates, keyed by
`(source, source_id, record_type)`. Before writing a record, each importer calls
`check_already_imported(source_id, record_type)` and skips it if that key is
already present.

Each importer builds a `source_id` that is stable across runs, so the same
upstream record always produces the same key:

| Importer | Example `source_id` |
|----------|---------------------|
| Wii Fit | `Bagsy_2026-10-02T21:42:00_weight` |
| Technogym (live) | the session id, e.g. `session_1041` |
| Technogym export | `biometric_weight_2024-08-01T00:00:00+00:00` |
| Health Connect CSV | `hcday:2026-09-07` (daily aggregate), `hcsess:2026-09-07 08:07:00:79 - Walking:11` (session), `hcsleep:<start>:<end>` (sleep) |

### 2. A database unique constraint

`body_measurements` has
`UNIQUE(person_id, measured_at, measurement_type, source, source_id)`.

This is the backstop for the case the log cannot cover on its own: Wii Fit keeps
two identical copies of the profile block in `FitPlus0.dat` and `FitPlus1.dat`.
If both got that far, the second insert would be rejected by the database rather
than silently duplicating a reading.

### Both mechanisms verified

Three consecutive runs of every importer:

```
Run 1: Nothing new - all 1 record is already imported.      (Technogym)
       Nothing new - all 8 measurements already imported.   (Wii Fit)
       Nothing new - all 182 records already imported.      (Technogym export)
Run 2: identical
Run 3: identical
```

Row counts in the database were unchanged across all three.

### What "nothing new" means, and what it does not

A skipped record is one the app has seen before. It is not deleted, updated, or
otherwise modified, and re-running never rewrites history. If you *do* want a
record re-read, delete its `import_log` row first.

## Messages you might see

| Message | What it means | Do |
|---------|---------------|-----|
| `Nothing new from Wii Fit - all N measurements are already imported.` | The save files were read; you have them all. | Nothing. |
| `FitPlus2.dat holds Wii Fit's non-profile data block and contains no body tests.` | Informational. That file is not a profile. | Nothing. |
| `No Wii Fit source folder found.` | The importer could not find any save files. | See [Troubleshooting](#troubleshooting). |
| `No CSV files in ...` | The Health Connect folder holds no CSV files. | Export from the phone app, or upload them on the import page. |
| `no Activity.csv found - skipping activity import` | That category was not exported. | Nothing, unless you expected it — re-export with the category ticked. |
| `N activities matched an existing gym workout and enriched it.` | Health Connect sessions overlapped gym workouts; the workouts gained heart-rate/calorie notes. | Nothing. This is the intended behaviour. |
| `MYWELLNESS_EMAIL / MYWELLNESS_PASSWORD are not set.` | Credentials missing, so the gym portal was not contacted. | Add them to `.env`. |
| `2026-10-02: Wii Fit recorded 99.5 kg, but 105 kg from technogym on 2026-10-02.` | Two sources disagree about the same day. | Open the profile page and pick which to use. Nothing was overwritten. |
| `No usable records found in the ... source.` | The source was read but held nothing importable. | Usually means the export is genuinely empty. |

## Troubleshooting

**"No Wii Fit source folder found"**

Check what the importer actually resolved to — the import dashboard shows it.
Then, in order:

1. Is `WII_FIT_SOURCE_PATH` set in `.env`, and does that path exist *from the
   machine running the import*?
2. On the Pi, is the Shield share mounted? A cron job cannot read an unmounted
   SMB path.
3. Does the folder contain files named `FitPlus0.dat`, `FitPlus1.dat`, etc.?
   Only those names are read.

**Technogym import finds nothing new, but you did a session**

The live API needs credentials. Confirm with:

```
py scripts/import_data.py --dry-run
```

It reports whether credentials are present, without touching anything.

**The daily job is not running at all**

- `crontab -l` — is the entry actually there?
- Is the `&&` chain correct, and does `log/` exist and is writable?
- Check `log/cron-import.log`.

**Does a daily job need internet / the console on?**

- Technogym: yes, it is an HTTP API.
- Wii Fit: **no**. It reads save files from disk. The console does not need to be
  on, and it does not need to be in sync — but the *files* must be reachable, so
  the Shield must have synced them to wherever `WII_FIT_SOURCE_PATH` points.

## Known issue: two importers share one source name

Both the live Technogym importer and the JSON-export importer report
`source = "technogym"`. Their `import_log` rows are therefore indistinguishable,
and in principle one could skip a record the other created if their `source_id`
formats ever collided.

They have not collided in practice — the two use different `record_type` values
for different tables — so this is a latent risk rather than an active bug.

Fixing it properly means giving the export importer its own name and migrating the
existing rows, because `source` is part of the unique constraint on
`body_measurements` and `activities`. Renaming it without migrating first would
cause the next import to insert duplicates. It is left alone deliberately until
that migration is worth doing.

The practical consequence today is cosmetic: both importers' messages are
labelled correctly ("Technogym" vs "Technogym export") because the runner stamps a
display label separately from the stored source key.
