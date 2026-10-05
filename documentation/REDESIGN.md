# App redesign programme (openGym-inspired)

Recreating what makes openGym good inside this tracker — its information
architecture, screens and training logic — without copying its code.

## Licence boundary (non-negotiable)

openGym (original and AI-coach fork) is **AGPL v3**. This project is public
with no licence. Therefore:

- **Borrow**: ideas, screen flows, training methodology, MIT data (exercise
  metadata, body geometry — see `THIRD-PARTY-NOTICES.md`), MIT/Apache
  libraries.
- **Never copy**: openGym components, stylesheets, JS logic, progression
  code, importer code, coach code, non-English text, exercise media.
- **Keep out**: anything with unclear ownership (exercise images/GIFs).

Every phase below is designed to be implementable from scratch. If a phase
ever seems to require openGym code, stop and re-scope — the design must stand
on its own.

## What is kept regardless of phase

- All import paths (Technogym live/manual, Wii Fit, Health Connect CSV +
  push endpoint) and their idempotency guarantees.
- The conflict philosophy: nothing auto-resolved, user decides.
- The Health Connect concept and the companion app.
- Single-user, no-login design. No passkeys, no multi-profile, no admin
  dashboard — those solve problems this tracker does not have.
- English only. No i18n framework.

## Phases

### Phase 1 — Look, theme, dashboard (this document's first build)
- Theme system: light/dark via CSS variables, accent colour choices,
  persisted per device. No server state — appearance is device-local.
- Responsive layout + bottom tab bar on small screens (the companion
  WebView benefits directly).
- Dashboard rework: today card (last session, this week's count), weight
  card with goal progress, stat row, neglected-muscles nudge.
- Weight goal on the profile (new `Person.weight_goal_kg`).

### Phase 2 — Guided workout runner (built)
- Start page leads with cross-source awareness (week by source, recent
  sessions, hot muscles) from `services/training_context.py`.
- Session page: last-time prefill, PR detection (Epley, warm-ups excluded),
  rest timer with beep/vibration, screen wake lock, superset linking,
  timed and cardio set modes, RIR/RPE as-logged.
- `services/training_context.py` + `GET /api/training-context`: the
  holistic snapshot (goals, current values, cross-source week, sessions,
  muscles, conflicts) — the context the future assistant consumes.
- Dashboard "This week" card breaks sessions/minutes down by source.
- Set schema extended (mode, duration, distance, effort, type, warm-up);
  WorkoutExercise gained mode + superset group.

### Phase 3 — Plans, routines, progression
- Weekly plan (routine per weekday), reschedule without touching the plan.
- Progression policies per routine: linear, double progression, Greyskull-style
  AMRAP — standard methodology, reimplemented with tests.
- Plan share as merge-safe JSON export/import.
- Needs: Routine/Plan tables.

### Phase 4 — Library, stats, measurements
- Searchable exercise library UI (filter by equipment, muscle preview,
  instructions, custom exercises).
- Stats additions: activity heatmap, weight goal line, 1RM curves, effort trends.
- Body measurements beyond weight (waist, arms…) — the model already allows
  any `measurement_type`.
- Plate calculator.
- Strong/Hevy-style CSV import (same importer architecture; fuzzy headers).

### Phase 5 — Assistant (LLM)
- Adopt the fork's principles, not its code: judgement/configure vs
  math/calculate split, discrete explained proposals, approval-required,
  snapshot + revert, payload allowlist, per-profile consent, degrade
  gracefully with the assistant off.
- Server contract already stubbed: `POST /api/assistant/ask`.
