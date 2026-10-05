# Companion app (Android)

Your fully-controlled Health Connect app. It reads Health Connect **on the
phone only** and either saves CSV files shaped exactly like the Health Data
Export app's (so the tracker's existing importer reads them unchanged) or
pushes straight to the Pi. No accounts, no servers, no data collection.

Five tabs:

| Tab | What it does |
|-----|--------------|
| **Tracker** | The Pi's web UI in a WebView — every page built for the project, unchanged. |
| **Export** | Grant Health Connect access, pick 7/30/90 days, save `Activity.csv` + `Vitals.csv` to Downloads or push to the Pi. Manual only — no background work. |
| **Scan** | Scan an equipment QR label to open its tracker page. |
| **Assistant** | Phase 5 placeholder. Defines the server contract (`POST /api/assistant/ask`) so both ends can be built independently. |
| **Settings** | Tracker URL (default `http://192.168.0.97:5000`) and API key. |

## What it exports

Exactly what your Galaxy Fit3 records, in the reference app's exact shape:

- `Activity.csv` — same 24-column header verbatim; daily steps/distance/calories plus one row per exercise session (`"79 - Walking"` style names preserved).
- `Vitals.csv` — same 21-column header verbatim; daily heart-rate min/max/avg only.

Everything else stays empty: the watch records no elevation, power, speed,
VO2, HRV, oxygen, respiratory, resting-HR or body data, so those columns are
blank rather than zero. **Sleep is never requested** — not declared, not read,
per your decision.

## Building it

You build this in Android Studio — it cannot be built here (no Android SDK on
the dev PC).

1. Install [Android Studio](https://developer.android.com/studio) (stable channel).
2. Open this `companion-app/` folder. Let Gradle sync (needs internet once).
3. If sync complains about versions, update what's flagged: AGP, Kotlin and
   `androidx.health.connect:connect-client` move fastest. Everything else is
   pinned to versions current when this was written — check for newer 1.x/2.x
   in Project Structure > Suggestions.
4. Connect the phone with USB debugging on, press **Run**. Or **Build > Build
   APK(s)**, copy `app/build/outputs/apk/debug/app-debug.apk` to the phone and
   open it (allow "Install unknown apps" once).

## Installing on the phone (sideload)

No Play Store release — this app is for one person, and a Play release would
mean a $25 account, Data Safety forms and review queues for zero benefit.

- **Via Android Studio**: Run with the phone connected. Quickest while iterating.
- **Via APK file**: Build APK, transfer it (USB, Drive, Bluetooth), open it on
  the phone, allow installs from that source once. Re-install the same way for
  updates — Android keeps the app's data (settings, key) across updates signed
  with the same debug key.

## First run

1. Open the app → **Settings** → check the tracker URL, paste the
   `HEALTH_CONNECT_API_KEY` from the Pi's `.env`.
2. **Export** → Grant Health Connect access (tick Steps, Distance, Calories,
   Exercise, Heart rate).
3. Pick a range → **Save CSVs** (upload them on the tracker's import page) or
   **Push straight to the tracker**.

## Things already decided (so you don't re-decide them)

- **minSdk 29** (Android 10+). Below Android 14, Health Connect comes from the
  Play Store app — the Export tab says so when it is missing. 29 is also the
  floor for permission-free Downloads access.
- **Manual sync only.** No WorkManager, no background battery use, no silent
  failures. Automation can come later once manual pushes prove the mapping.
- **Plain HTTP on the LAN** (`usesCleartextTraffic`). No certificate exists and
  nothing leaves the house. Revisit if the tracker is ever exposed beyond the LAN.
- **API key in plain preferences, never shown back.** Proportionate for a
  LAN-only secret; upgrade to EncryptedSharedPreferences if the threat model
  ever changes.
- **CSV and push use different `source_id` prefixes** (`hcday:`/`hcsess:` vs
  `hcapp-`). Consequence: importing the same day both ways stores it twice.
  Pick one path per export for now; cross-path dedup is a known follow-up.
- **Camera only when Scan opens.** The permission is requested there, not at
  install.
- **No launcher icon yet** — Android Studio: right-click `res` > New > Image
  Asset to generate one.

## Things still to think about

- **Package name** (`com.fittracker.companion`): fine as-is, but renaming later
  means Health Connect treats it as a new app and permissions must be
  re-granted. Rename now if you want to, never later.
- **Backup rules**: Android auto-backup includes preferences (i.e. the API key)
  to Google Drive. Acceptable for most; add a backup-rules XML excluding it if
  not.
- **Large ranges**: 90 days of heart-rate samples is a lot of records in one
  read. If it ever fails, export in smaller ranges — the importer dedups, so
  overlapping exports are safe.
- **Assistant endpoint**: the tab is wired to `POST /api/assistant/ask`
  (`{"message"}` → `{"reply"}`); Phase 5 builds the server side to that
  contract.
