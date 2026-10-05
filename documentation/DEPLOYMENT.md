# Deployment Guide - Personal Fitness Tracker

How the app gets from this Windows PC onto the Raspberry Pi (4B) and runs
there 24/7 without the PC being switched on.

---

## 1. Layout on the Raspberry Pi

```
/opt/stacks/python/scripts/
├── archive/                  # (existing, unrelated)
├── logs/                     # (existing, unrelated)
├── docker-compose.yml        # rail_app  <- NOT touched by this project
├── Dockerfile                # rail_app  <- NOT touched by this project
├── requirements.txt          # rail_app  <- NOT touched by this project
├── README.md                 # rail_app  <- NOT touched by this project
├── rail_app/                 # (existing, unrelated)
├── gym_booking_*.py          # (existing, unrelated)
│
└── fitness-tracker/          # <-- THIS PROJECT lives here
    ├── fitness_app/          # application code (copied from PC)
    ├── data/                 # SQLite database + imported files (NOT copied)
    ├── .env                  # credentials (NOT copied - you create it once)
    ├── Dockerfile
    ├── docker-compose.yml
    ├── requirements.txt
    ├── .dockerignore
    └── .env.example
```

**Why the sub-folder?** The parent folder already holds `rail_app` plus its own
`Dockerfile`, `docker-compose.yml`, `requirements.txt` and `README.md`. Copying
the fitness tracker files straight into `/opt/stacks/python/scripts/` would
overwrite those and break the yoga-class booking scripts. The sub-folder keeps
the two projects completely independent.

If you still see a stray `fitness_app` folder directly inside
`/opt/stacks/python/scripts/` it is a leftover from an earlier copy and can be
deleted - nothing uses it. (Left alone for now, delete when you are happy.)

---

## 2. One-time setup on the Pi

Nothing needs creating by hand - the first `deploy-to-pi.bat` run makes the
folder and seeds `.env` from `.env.example`. You only need to **edit `.env`
once** to add your credentials:

```bash
ssh grahamsshaw@192.168.0.97
nano /opt/stacks/python/scripts/fitness-tracker/.env
```

`.env` on the Pi:

```ini
SECRET_KEY=<some long random string>
FITNESS_DEBUG=0
FITNESS_HOST_PORT=5000
MYWELLNESS_EMAIL=your@email.com
MYWELLNESS_PASSWORD=yourpassword
WII_FIT_SOURCE_PATH=/mnt/shield-internal/Android/data/org.dolphinemu.dolphinemu/files/Wii/title/00010004/52465050/data
```

Notes:
- `.env` is **never** copied from your PC, and the deploy script only creates
  it when it is missing - it never overwrites an existing one.
- The app starts fine without valid credentials; only the Mywellness live
  import needs them.
- `FITNESS_HOST_PORT` is the port published on the Pi. Change it if `rail_app`
  already uses 5000 - nothing else needs editing.
- `WII_FIT_SOURCE_PATH` is optional. Leave it blank and the app falls back to
  its own `data/wii_fit` folder. See section 6.

---

## 3. Deploying (the normal workflow)

Double-click **`deploy-to-pi.bat`** in the project root, or run it from a
terminal:

```bat
deploy-to-pi.bat
```

You will be asked for the Pi password (3 times: folder check, file copy, build).
For a password-free deploy, set up an SSH key - see section 5.

The script:

| Step | What happens |
|------|--------------|
| 1/5 | Connects over SSH and creates `/opt/stacks/python/scripts/fitness-tracker/data` |
| 2/5 | Reports whether `.env` already exists on the Pi |
| 3/5 | Streams `fitness_app/`, `scripts/`, `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `README.md` to the Pi over `tar`/SSH, then verifies the extraction landed |
| 3b | Creates `.env` from `.env.example` **only if it is missing** |
| 4/5 | Detects whether the Pi uses `docker compose` (v2) or `docker-compose` (v1) |
| 5/5 | `down` -> `build` -> `up -d`, then prints the container status |

Force a full rebuild (ignores the cached layers, slow on a Pi):

```bat
deploy-to-pi.bat --no-cache
```

Then open **http://192.168.0.97:5000**.

### What is never sent to the Pi

- `data/` - the database and imported Wii Fit / Technogym files
- `.env` - your credentials (the Pi's own copy is used instead)
- `debug/`, `log/`, `Archive/`, `Resources_Archive/`, `documentation/`
- `__pycache__` / `*.pyc` - excluded from the transfer *and* from the image
  via `.dockerignore`

> **Tar exclude trap.** The transfer uses bsdtar `--exclude` patterns, which
> match *nested* path components too — a bare `--exclude "data"` once
> silently stripped `fitness_app/static/data/` from every deploy (the muscle
> map's geometry 404'd on the Pi while everything else worked). Never name
> a shipped folder `data` or `backups`, and never add a bare-word exclude
> without listing a test tar first.

### Why tar-over-SCP instead of plain `scp -r`

`scp -r fitness_app user@host:/path/` copies *into* an existing folder, which on
the second run produces `/path/fitness_app/fitness_app`. Streaming a tar archive
over SSH overwrites files in place, so repeated deploys stay clean.

---

## 4. Day-to-day commands

```bash
# Follow the logs
ssh grahamsshaw@192.168.0.97 "docker logs -f fitness-web"

# Restart after changing .env
ssh grahamsshaw@192.168.0.97 "cd /opt/stacks/python/scripts/fitness-tracker && docker compose -p fitness up -d"

# Stop
ssh grahamsshaw@192.168.0.97 "cd /opt/stacks/python/scripts/fitness-tracker && docker compose -p fitness down"

# Inspect the database (row counts, latest measurements, conflicts)
ssh grahamsshaw@192.168.0.97 "docker exec fitness-web python /app/scripts/db_tool.py info"

# Back up the database manually
ssh grahamsshaw@192.168.0.97 "docker exec fitness-web python /app/scripts/db_tool.py backup"

# Restore a backup
ssh grahamsshaw@192.168.0.97 "docker exec fitness-web python /app/scripts/db_tool.py restore <backup-name>"

# Run an import now (instead of waiting for the cron job)
ssh grahamsshaw@192.168.0.97 "docker exec fitness-web python /app/scripts/import_data.py"
```

The compose project name is pinned to `fitness` (`-p fitness`) so the
fitness-tracker containers/volumes never mix with `rail_app`'s.

---

## 5. Password-free deploys (SSH key) — DONE

SSH key auth is already set up. The PC's public key is in
`~/.ssh/authorized_keys` on the Pi, so `deploy-to-pi.bat` and all other SSH
commands run without a password prompt.

If you ever need to re-add the key (e.g. after replacing the PC):

```powershell
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh grahamsshaw@192.168.0.97 "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

---

## 6. Wii Fit save files on the Pi

The save files live on the NVIDIA Shield Pro. The Pi needs a path to them:

```bash
# Mount the Shield's share (edit /etc/fstab to make this permanent)
sudo mount -t cifs //192.168.0.57/internal /mnt/shield-internal \
  -o username=guest,vers=2.1,ro
```

Then point `WII_FIT_SOURCE_PATH` at the save folder, e.g.
`/mnt/shield-internal/Android/data/org.dolphinemu.dolphinemu/files/Wii/title/00010004/52465050/data`.

The import page (`/imports`) shows the folder it is actually reading and warns
if it is unreachable, so a failed mount is obvious rather than silent.

---

## 7. Scheduled jobs (cron)

Two cron jobs run on the Pi:

| Time | Job |
|------|-----|
| 02:00 | Database backup — copies `data/fitness.db` to `backups/fitness-YYYYMMDD.db`, deletes backups older than 14 days |
| 07:30 | Import — runs `import_data.py` inside the container to pull new Technogym and Wii Fit data |

The backup runs **before** the import, so you always have a clean snapshot from
before any new data arrives.

View or edit the cron jobs:

```bash
ssh grahamsshaw@192.168.0.97 "crontab -l"
```

---

## 8. Database sync (PC ↔ Pi)

The Pi database is the source of truth. The PC database is a disposable scratch
copy for testing.

| Command | What it does |
|---------|--------------|
| `deploy-to-pi.bat` | Push code to the Pi and rebuild. **Never touches the database.** |
| `push-database.bat` | Back up the Pi database, then overwrite it with the PC database. |
| `fetch-database.bat` | List or download a Pi database backup to the PC for inspection. |

### Inspecting the database

```bash
# On the Pi (inside the container)
ssh grahamsshaw@192.168.0.97 "docker exec fitness-web python /app/scripts/db_tool.py info"

# On the PC
py scripts/db_tool.py info
```

### Backing up and restoring

```bash
# On the Pi
ssh grahamsshaw@192.168.0.97 "docker exec fitness-web python /app/scripts/db_tool.py backup"
ssh grahamsshaw@192.168.0.97 "docker exec fitness-web python /app/scripts/db_tool.py restore <backup-name>"

# On the PC
py scripts/db_tool.py backup
py scripts/db_tool.py restore <backup-name>
```

### Why the split?

A routine code deploy must never be able to lose the database. By keeping
database movement separate and guarded (always backs up first), the dangerous
operation requires an explicit, deliberate action.

---

## 9. Health checks

```bash
# Is the container up and what port is it publishing?
ssh grahamsshaw@192.168.0.97 "docker ps --filter name=fitness-web"

# Does the app answer?
ssh grahamsshaw@192.168.0.97 "curl -s -o /dev/null -w '%{http_code}' http://localhost:5000/"

# Any errors in the log?
ssh grahamsshaw@192.168.0.97 "docker logs --tail 50 fitness-web"
```

---

## 10. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `ERROR: SSH failed` | SSH key not set up or wrong key. Test with `ssh grahamsshaw@192.168.0.97` in PowerShell. |
| `ERROR: File transfer failed` | The tar stream was cut short (network drop). Just run the script again - it is safe to repeat. |
| `port is already allocated` | `rail_app` is using 5000. Set `FITNESS_HOST_PORT=5001` in the Pi's `.env` and redeploy. |
| `Neither docker compose nor docker-compose found` | Docker is not installed, or your user is not in the `docker` group: `sudo usermod -aG docker grahamsshaw` then log out and back in. |
| App loads but charts are empty | No measurements imported yet. Use **Profile -> Log Weight**, or run an import from `/imports`. |
| Changes do not appear | Hard refresh the browser (Ctrl+F5); Chart.js is loaded from a CDN and Flask caches static files. |
| Deploy says success but the old code runs | Run `deploy-to-pi.bat --no-cache`. |
| `ModuleNotFoundError: No module named 'httpx'` | `httpx` was missing from `requirements.txt`. Fixed — rebuild the container. |
| Wii Fit import finds no files | The Shield SMB share is not mounted on the Pi. See section 6. |
| `push-database.bat` says backup failed | The Pi database path is wrong, or the Pi is unreachable. Check SSH access first. |
