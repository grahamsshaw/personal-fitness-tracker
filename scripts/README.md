# scripts

Standalone entry points — the things you run from a terminal, a scheduler, or a
`.bat` file. Nothing here is imported by the web app.

Each script has a full docstring at the top of the file explaining what it is for
and how to use it. This file is just the index.

| Script | What it does |
|--------|--------------|
| `import_data.py` | Runs the Technogym and Wii Fit importers and prints a summary. This is what the daily scheduled job calls. |
| `seed_equipment_profiles.py` | Seeds `EquipmentProfile` rows for known Technogym machines, linked to the `equipment` table. Idempotent — re-running only fills gaps. |

## import_data.py

Pulls in anything new from every configured source. Safe to run as often as you
like — each importer skips records it has already stored, so a daily job costs a
few seconds and creates no duplicates.

```
py scripts/import_data.py                          # everything (what the daily job runs)
py scripts/import_data.py --source wii_fit         # one source
py scripts/import_data.py --source technogym --days 90
py scripts/import_data.py --dry-run                # check reachability, import nothing
py scripts/import_data.py --no-log                 # skip the log file
```

It needs no web server: it builds an application context, runs the importers,
prints a summary and exits. Exit code is `0` when everything worked or had nothing
new, and `1` when a source failed or could not be reached.

It shares its logic with the web import buttons through
`fitness_app/services/imports.py`, so a scheduled run and a button press import
the same things and report them the same way.

Output goes to `log/import.log` unless `--no-log` is given.

## Setting up the daily job

Full instructions, including the Raspberry Pi `crontab` line and the Windows Task
Scheduler steps, are in
[`../documentation/IMPORTING.md`](../documentation/IMPORTING.md).

Short version for the Pi, which is where the job belongs because it runs 24/7:

```cron
30 7 * * * cd /opt/stacks/python/scripts/fitness-tracker && /usr/bin/docker exec fitness-tracker python scripts/import_data.py --source technogym >> log/cron-import.log 2>&1
```
