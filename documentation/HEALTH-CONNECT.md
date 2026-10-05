# Health Connect Sync — Design Document

Phase 4 design: how Android Health Connect data flows into the fitness tracker
running on the Pi.

---

## 1. What is Health Connect?

Health Connect is Google's unified health data platform for Android. It acts as
a central store that other apps and devices can read from and write to, with the
user's permission. It aggregates data from phones, watches, and third-party apps.

### Data types available

| Category | Data types |
|----------|-----------|
| **Activity** | Steps, calories burned, distance, active time, workouts (type, duration, calories, start/end time) |
| **Body** | Weight, height, BMI, body fat percentage |
| **Heart** | Heart rate (resting, continuous), HRV |
| **Sleep** | Sleep stages, duration, quality |
| **Nutrition** | Hydration, calories consumed, macros |
| **Cycle** | Menstrual cycle tracking |

### What we care about

For the fitness tracker, the relevant types are:

- **Weight** → maps to `BodyMeasurement` (measurement_type='weight')
- **BMI** → maps to `BodyMeasurement` (measurement_type='bmi')
- **Workouts** → maps to `Workout` + `WorkoutExercise` (or `Activity`)
- **Steps / active time** → could map to `Activity` (activity_type='steps' or similar)
- **Heart rate** → new model or JSON field on `Workout`

---

## 2. Sync direction

**Health Connect → Pi** (one-way, via an Android app on the phone).

The Pi pulls data from Health Connect and incorporates it alongside gym and Wii
Fit data. The Pi remains the single source of truth. We do not push data from
the Pi to Health Connect.

### Why one-way?

- The gym records a workout → that workout *causes* the activity Health Connect
  sees. The workout is the source; Health Connect is a supplement.
- Health Connect data is a complement (steps, daily activity, resting heart
  rate), not a replacement for structured workout data.
- Keeping it one-way avoids circular sync and conflicting writes.

### A hard constraint: there is no server-side API

Google Health Connect has **no REST API and no OAuth flow a backend can use**.
The data lives on the Android device and can only be read by an Android app
running on that device (via the Jetpack Health Connect client library, with
per-data-type user permission). There is no token the Pi can hold, no endpoint
the Pi can poll, and no webhook that pushes to a server.

This rules out any design where the Pi "pulls from Health Connect" directly.
Every workable design goes through an Android app on the phone, which reads
Health Connect on-device and sends the data to the Pi.

---

## 3. Sync mechanism — three options

All three centre on an Android app, because of the constraint above. The
difference is who initiates the transfer and when.

### Option A: Manual sync from the phone app (recommended first step)

A small Android app that reads Health Connect on-device and POSTs the records
to an endpoint on the Pi. The user opens the app and taps "Sync".

**Pros:** Simple, user-controlled, no background processes, no persistent
credentials beyond a static API key.
**Cons:** Requires the user to remember to sync; not automatic.

### Option B: Background sync from the phone app

The same app, but using Android WorkManager to read Health Connect and push to
the Pi on a schedule (e.g. every few hours), without the user opening anything.

**Pros:** Automatic, no user intervention.
**Cons:** More complex; background work can be killed by battery optimisation;
permissions can be revoked silently, so the app must check and report.

### Option C: Scheduled processing on the Pi

A cron job on the Pi that processes data the phone has already pushed —
matching Health Connect activities to gym workouts, enriching records,
reporting conflicts. It cannot fetch anything itself; it works through the
queue the phone app fills.

**Pros:** Heavy lifting (matching, enrichment) happens on the always-on Pi.
**Cons:** Not a sync mechanism on its own — it depends on A or B having
delivered the data.

### Recommendation

**Start with Option A (manual phone-app push), then add Option C (Pi-side
processing) once data is flowing.** Add Option B (background push) last, when
the manual flow has proven the mapping is right. Yes, all three — in that
order.

---

## 4. Authentication

Two separate trust boundaries, neither of which is Google OAuth:

### Phone → Health Connect (on-device permissions)

The Android app declares the data types it needs in its manifest (e.g.
`READ_WEIGHT`, `READ_EXERCISE`, `READ_STEPS`) and requests them through the
Health Connect permission screen. Permission is per data type, granted by the
user in the Health Connect system UI, and revocable at any time. The app must
check granted permissions at the start of every sync and skip revoked types
rather than fail.

No Google Cloud project, no OAuth client, no consent screen hosted by us. This
is the investigation outcome: there is nothing to set up server-side.

### Phone → Pi (API key)

The Pi exposes a push endpoint on the home LAN. The phone app authenticates
with a static API key stored in the Pi's `.env` (e.g.
`HEALTH_CONNECT_API_KEY=<long random string>`) and configured once in the app.
The Pi rejects requests with a missing or wrong key.

This is proportionate: the endpoint is only reachable on the home network, the
payload is the user's own health data going to their own server, and there is
no third party involved. If the endpoint is ever exposed beyond the LAN, this
should be revisited (TLS + per-device keys).

### What needs investigation (remaining)

- **Health Connect Toolbox** — Google's test app for writing sample data, so
  the phone app and Pi endpoint can be tested without real workout data.
- **Change tokens** — Health Connect offers change tokens per data type so a
  sync can ask "what changed since last time" instead of re-reading everything.
  The phone app should store the token between syncs.
- **Samsung Health interplay** — on Samsung devices, Samsung Health both reads
  and writes Health Connect. Worth confirming which app is the origin for
  weight/workout records to set `dataOrigin` expectations.

---

## 5. Data mapping

### Proposed mapping

| Health Connect data | Our model | Notes |
|---------------------|-----------|-------|
| Weight | `BodyMeasurement` (type='weight') | Source='health_connect' |
| BMI | `BodyMeasurement` (type='bmi') | Derived from weight + height |
| Workout (type, duration, calories) | `Workout` | Source='health_connect' |
| Workout exercises | `WorkoutExercise` | If the API provides exercise-level detail |
| Steps | `Activity` (type='steps') | New activity type |
| Distance | `Activity` (distance_m) | Part of steps/walk activity |
| Heart rate (resting) | New field on `Person` or new table | Daily resting HR |
| Heart rate (workout) | New field on `Workout` | Average/max HR during workout |
| Sleep | New table `SleepRecord` | Duration, stages, quality |

### New models needed

```python
class SleepRecord(db.Model):
    """Sleep data from Health Connect."""
    __tablename__ = "sleep_records"

    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    started_at = db.Column(db.DateTime, nullable=False)
    ended_at = db.Column(db.DateTime, nullable=False)
    duration_seconds = db.Column(db.Integer)
    source = db.Column(db.String(50))  # 'health_connect'
    source_id = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("source", "source_id"),
    )
```

Heart rate could be a new table or a JSON field on `Workout`. This depends on
what granularity the Health Connect API provides.

---

## 6. Conflict handling

### The scenario

The gym records a workout (e.g. "Bench Press — 3×10×80kg"). Health Connect also
records an activity (e.g. "Strength training — 45 min, 250 kcal"). These are the
same event from two sources.

### The rule

**The workout is the source; Health Connect is a supplement.**

- The gym workout is the structured, detailed record.
- Health Connect adds context: heart rate during the workout, calories, steps.
- We do not create a duplicate workout from Health Connect data.
- We *enrich* the existing workout with Health Connect data (heart rate, calories).

### How to match

Match Health Connect activities to existing workouts by:
1. **Time overlap** — the Health Connect activity overlaps with the workout's
   start/end time.
2. **Activity type** — both are "strength training" or similar.
3. **Duration** — similar duration.

When a match is found, enrich the workout. When no match is found, create a new
`Activity` from the Health Connect data (e.g. a walk or run that wasn't logged
at the gym).

### Wii Fit

Wii Fit activities are more stationary/gentle and may not show up in Health
Connect as distinct activities. They may appear as general "active time" or not
at all. This is lower priority — we can skip Wii Fit ↔ Health Connect matching
initially.

---

## 7. API design (Pi side)

The Pi receives data; it never fetches. One endpoint, idempotent like every
other importer.

```
POST /api/health-connect/push
    Accept records read from Health Connect by the phone app.
    Headers: X-API-Key: <HEALTH_CONNECT_API_KEY>
    Body: { "records": [ { "type": "weight" | "workout" | "steps" | ...,
                           "source_id": "<health-connect-uid>",
                           ...type-specific fields } ] }
    Returns: { "imported": N, "skipped": M, "errors": [...] }

GET /api/health-connect/status
    Show sync status: last push time, per-type counts, open conflicts.
```

### Processing logic (Option C worker)

```
1. Reject the request when the API key is missing or wrong.
2. For each record:
   a. Check import_log for idempotency (source='health_connect',
      source_id=<uid>). Skip when already stored.
   b. Map to the model per section 5.
   c. For workouts/activities: check for an overlapping gym workout.
      On a match, enrich the workout (heart rate, calories, steps) instead
      of creating a duplicate.
   d. Otherwise create the record.
3. Report anything needing a decision as a conflict for the profile page.
```

---

## 8. Open questions

1. **What does the phone actually see?** — Which apps write weight/workouts on
   this device (Samsung Health? Technogym app? watch companion?), and what
   `dataOrigin` values come through? Determines what is worth syncing.
2. **Workout granularity** — Does the Health Connect exercise record carry
   per-exercise or per-set detail, or just workout-level type/duration/calories?
   Determines how much enrichment is possible.
3. **Samsung Health route** — Samsung offers its own Partner SDK. If Samsung
   Health holds data that never reaches Health Connect, that is a second source
   to consider. Check first; do not build for it speculatively.
4. **Change-token durability** — Where the phone app stores change tokens so an
   uninstall/reinstall does not cause a full re-import (idempotency covers
   correctness; tokens cover efficiency).

## 9. Next steps

0. **Try the Health Data Export app first (no custom app needed)** — the Play
   Store app *Health Data Export* (`com.teqxnology.healthdataexport`) reads
   Health Connect on-device and exports to **CSV** (saved to the phone) or
   Google Sheets. It covers Activity (steps, distance, exercise sessions,
   calories), Body measurements (weight, height, body fat), Sleep sessions
   and Vitals (heart rate, resting HR, HRV). It collects no user data.
   The CSV route is the right first integration:
   - Export CSV on the phone (bulk history first, then small ranges).
   - Transfer the file to the Pi and import it with a CSV importer —
     the same pattern as the Technogym manual JSON export.
   - CSV keeps the data at home; Google Sheets would hand it to Google and
     need Sheets API credentials on the Pi for no benefit.
   - A custom phone app is only worth building if this proves inadequate.
   - ~~Build the CSV importer~~ — **done**: `importers/health_connect_csv.py`
     reads `Activity.csv`/`Sleep.csv`/`Vitals.csv` from
     `data/health_data_export/`, reuses the push endpoint's processing
     (idempotency, workout enrichment, conflict reporting), stores sleep in
     `sleep_records`, and is wired into `import_data.py`, the upload route and
     the scheduled run. Verified against a real 31-day export.
1. **Confirm data origins** — on the phone, open Health Connect → see which
   apps contribute weight, exercise, steps, heart rate.
2. ~~**Build the Pi endpoint**~~ — **done**: `POST /api/health-connect/push`
   with API-key auth, idempotency, workout enrichment and conflict reporting,
   plus unauthenticated `GET /api/health-connect/status`. Verified with 44
   automated checks against a scratch database.
3. **Build the minimal phone app** — read weight + exercise records, POST them
   to the Pi endpoint with the API key. Manual "Sync" button only.
4. **Test with real data** — Health Connect Toolbox can write sample records if
   real data is thin; adjust the mapping to what actually arrives.
5. **Add Pi-side processing (Option C)** — matching/enrichment cron once pushes
   are reliable.
6. **Add background push (Option B)** — WorkManager schedule in the app, last.

---

## 10. References

- [Health Connect API documentation](https://developer.android.com/health-and-fitness/health-connect/get-started)
- [Health Connect data types](https://developer.android.com/reference/kotlin/androidx/health/connect/client/records)
- [Accessing Health Connect data from a backend (why an on-device app is required)](https://openwearables.io/blog/how-to-access-google-health-connect-data-in-your-backend)
- [Health Connect Toolbox (test data)](https://developer.android.com/health-and-fitness/health-connect/toolbox)
- [Technogym Live routines](https://www.technogym.com/en-GB/support/post/routines-on-technogym-live/)
