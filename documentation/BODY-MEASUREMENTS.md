# Body measurements: conflicts and current values

Weight and BMI arrive from several places at once — the Wii Fit scale, Technogym's
own records, Health Connect (planned) and manual entry. Those sources disagree, and
the app has to do something sensible with the disagreement without ever throwing
data away.

This note explains the rules it follows and why each one is that way.

## The rule that matters most

**Nothing is ever discarded automatically.**

An importer never overwrites, deletes or hides an existing reading. It stores what
arrived, then reports any disagreement with other readings for the same day as a
*conflict*. The user decides which value to believe, on the profile page.

That decision — and only that decision — is what changes what the app treats as
current. It is recorded as `is_superseded` on the rejected rows, which means:

- the rejected reading is still in the database,
- it can still be inspected or brought back,
- and the choice is reversible at any time.

### Why not just pick a winner automatically?

It is tempting to rank sources by trustworthiness and let the app decide. It was
rejected deliberately, for two reasons.

First, there is no reliable ranking here. Technogym biometrics are values the user
typed into a gym kiosk weeks or months ago; a Wii Fit reading is an actual scale
measurement but comes from a consumer balance board that estimates its own
accuracy. Neither is reliably better, and on different days either could be.

Second, and more importantly, a weight that disagrees with today's weight is not
necessarily an error. The Technogym record of 105 kg in 2024 and the Wii Fit
reading of 99.5 kg today are both true — they describe a period of loss. An
automatic rule that hid the older value would quietly rewrite that history and
make the chart show a smoother, less truthful line.

So the app's job is to *make the disagreement visible* and let you settle it.

## What counts as a conflict

Two readings conflict when all four of these are true:

1. They are the same **measurement type** (weight vs weight, BMI vs BMI).
2. They are attributed to the **same calendar day**.
3. They come from **different sources**.
4. Their values differ by more than the tolerance for that type.

Each condition excludes something that looks like a conflict but is not:

| Condition | Excludes |
|-----------|----------|
| Same type | Weight vs BMI comparisons, which are the same fact in different units. |
| Same calendar day | A weight last month differing from today's — that is history, not disagreement. |
| Different sources | Stepping on the Wii Fit scale twice in one day, which is normal. Only *disagreement between sources* is interesting. |
| Value tolerance | Sources reporting 99.500 and 99.502 kg. Rounding noise is not worth bothering anyone about. |

### Tolerances

Defined in `fitness_app/services/measurements.py`:

```python
VALUE_TOLERANCE = {
    "weight": 0.05,   # kg - catches 99.5 vs 99.53, ignores float noise
    "bmi":    0.01,   #     BMI is quoted to two decimal places
}
```

### Which types participate

```python
CONFLICT_TYPES = ("weight", "bmi")
```

**Height is deliberately excluded.** Height is a fixed physical property, not a
fluctuating measurement, so two different heights on the same day means one source
simply has the wrong person — a different problem that needs an error, not a
pick-one-of-two prompt.

## Current values

`current_measurement(type)` returns the newest reading that is **not** superseded.
This is what the profile page, the dashboard and `/api/charts/summary` all show.

Where a day still has an open conflict, the choice between same-day readings is
genuinely arbitrary — it picks the most recent one. That arbitrariness is the point:
it is temporary, it only affects an unsettled day, and the conflict panel on the
profile page makes it obvious that a decision is outstanding.

## Schema

Three columns were added to `body_measurements`:

| Column | Meaning |
|--------|---------|
| `is_superseded` | The user rejected this reading in favour of another for the same day. |
| `superseded_by_id` | Points at the reading that was kept instead. |
| `superseded_at` | When the decision was made. |

`db.create_all()` will **not** add columns to a table that already exists, so
these are applied by `fitness_app/migrations.py` — a small set of idempotent
`ALTER TABLE` steps run at every start-up. Adding a future column means adding a
function to `MIGRATIONS` that calls `_ensure_column`; nothing else changes.

## HTTP surface

| Endpoint | Purpose |
|----------|---------|
| `GET /api/charts/weight` | Weight series. Add `?include_superseded=true` to include set-aside readings. |
| `GET /api/charts/bmi` | BMI series. Same query parameter. |
| `GET /api/charts/conflicts` | Every day still awaiting a decision, with each competing reading. |
| `GET /api/charts/summary` | Current weight/BMI **and** `open_conflicts`, the count of unsettled days. |
| `POST /measurements/resolve` | Record the user's choice: `measurement_type`, `day`, `keep_id`. |
| `POST /measurements/undo` | Reopen a day: `measurement_type`, `day`. |

The series endpoints return `labels`, `values`, `sources`, `times`, `ids` and
`superseded` as parallel arrays.

## How importers report conflicts

`ImportResult` has three separate lists, because they mean different things:

| Field | Shown as | Meaning |
|-------|----------|---------|
| `errors` | error | The import did not fully succeed. |
| `conflicts` | warning | Imported data contradicts another source for the same day. Needs a decision. |
| `notes` | info | Something deliberately skipped. Not a failure. |

Both body-measurement importers call `supersede_mismatches_within_day()` after
storing a reading:

```python
for other_id in supersede_mismatches_within_day(weight):
    other = db.session.get(BodyMeasurement, other_id)
    result.conflicts.append(...)
```

That helper **reports and returns ids; it does not modify anything.** The name is
historical — it describes the situation it detects, not an action it takes.

Because the check only runs for readings an import actually *created*, re-running
an import is silent: already-imported rows are skipped before the check, so an
idempotent re-import produces no spurious warnings. This is verified in
`debug/`-style test runs and is a deliberate property.

## The service module

`fitness_app/services/measurements.py` owns all of this. Routes and importers call
into it; neither implements conflict rules of its own.

| Function | Role |
|----------|------|
| `find_conflicts()` | Read-only. List every open conflict. |
| `current_measurement(type)` | The newest non-superseded reading. |
| `current_values()` | That, for every conflict-prone type at once. |
| `series(type, include_superseded=False)` | Chart-ready points. |
| `resolve_conflict(type, day, keep_id)` | Record the user's choice. |
| `clear_superseded(type, day)` | Undo it. |
| `supersede_mismatches_within_day(row)` | The importer-facing check. Reports, never edits. |
| `describe_reading(reading)` | `"99.5 kg from wii_fit on 2026-10-02"`, for messages. |

Keeping this out of the routes means the same rules apply to an import, a chart
request and a page render. A second importer (Health Connect) needs no new logic —
just a call to `supersede_mismatches_within_day` after it stores a reading.

## Charts

`fitness_app/static/js/charts.js` draws weight and BMI from one shared renderer,
differing only in an entry in `MEASUREMENT_STYLES`:

```js
const MEASUREMENT_STYLES = {
    weight: { unit: 'kg', label: 'Weight (kg)', axis: 'Weight (kg)', rgb: '37, 99, 235' },
    bmi:    { unit: '',    label: 'BMI',         axis: 'BMI',         rgb: '22, 163, 74' },
};
```

Adding a third body-measurement chart is therefore one new entry, one `<canvas>`, and
one `createMeasurementChart(canvasId, data, 'body_fat')` call.

Set-aside readings are drawn hollow and grey with a diamond marker, so they read as
"recorded but not in use" rather than as part of the current trend. The "Show
readings I've set aside" checkbox on each chart re-fetches with
`include_superseded=true`.

## Manual entry

Logging a weight manually on `routes/main.py`:

- computes BMI from `Person.height_cm` when a height is on record, so the BMI chart
  has no gap left by manual entries;
- sets `source_id` so repeated entries are idempotent rather than duplicating;
- checks for a same-day conflict with another source and warns if there is one,
  without overwriting anything.

## Worked example

The situation this feature was built for:

```
Technogym   2026-10-02  105.0 kg   (typed into a gym kiosk at some point)
Wii Fit     2026-10-02   99.5 kg   (scale reading at 21:42)
```

Different sources, same calendar day, 5.5 kg apart — a conflict.

1. The Wii Fit import stores 99.5 kg and appends a `conflicts` entry naming both
   readings. The import still reports success; nothing is marked superseded.
2. The profile page shows a panel: *Sources disagree — choose a value*, with both
   numbers, both source names and both times.
3. Choosing the Wii Fit reading sets `is_superseded=True` on the Technogym row and
   points `superseded_by_id` at the Wii Fit row.
4. The weight chart now shows one point for 2026-10-02. Ticking *Show readings I've
   set aside* brings the 105.0 kg point back, drawn in grey.
5. "Reopen day" (via `/measurements/undo`) clears the decision and puts both back.
