package com.fittracker.companion

import android.content.ContentValues
import android.content.Context
import android.os.Environment
import android.provider.MediaStore
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/**
 * Writes Health Connect data as CSV files byte-compatible in shape with the
 * Health Data Export app, so the tracker's existing importer reads them
 * unchanged. Headers below are verbatim copies of that app's headers —
 * including columns this watch never fills. An unrecorded column stays
 * empty; a zero would be a lie about the body.
 *
 * Only Activity and Vitals are exported. Sleep is excluded by the owner's
 * decision; body measurements come from scales, not this app.
 */
object CsvExporter {

    private val dayFmt = DateTimeFormatter.ofPattern("yyyy-MM-dd")
    private val momentFmt = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")

    /** Verbatim header of the reference app's Activity.csv. */
    val ACTIVITY_HEADER = listOf(
        "Date", "Source(s)", "Timezone", "Steps", "Distance (m)",
        "Elevation (m)", "Floors climbed", "Total Calories (kcal)",
        "Active Calories (kcal)", "Power min (W)", "Power max (W)",
        "Power avg (W)", "Speed min (m/s)", "Speed max (m/s)",
        "Speed avg (m/s)", "VO2 max min (ml/min/kg)", "VO2 max max (ml/min/kg)",
        "VO2 max avg (ml/min/kg)", "Wheelchair pushes", "Start Date/Time",
        "Exercise Name", "Duration (min)", "Exercise Calories (kcal)",
        "Exercise Distance (m)",
    )

    /** Verbatim header of the reference app's Vitals.csv. */
    val VITALS_HEADER = listOf(
        "Date", "Source(s)", "Timezone", "Heart rate min (bpm)",
        "Heart rate max (bpm)", "Heart rate avg (bpm)",
        "Heart rate variability min (ms)", "Heart rate variability max (ms)",
        "Heart rate variability avg (ms)", "Oxygen saturation min (%)",
        "Oxygen saturation max (%)", "Oxygen saturation avg (%)",
        "Respiratory rate min (breaths/min)", "Respiratory rate max (breaths/min)",
        "Respiratory rate avg (breaths/min)", "Resting heart rate min (bpm)",
        "Resting heart rate max (bpm)", "Resting heart rate avg (bpm)",
        "Blood pressure (mmHg)", "Blood glucose (mmol/L)",
        "Body temperature (°C)",
    )

    private fun num(value: Number?): String =
        if (value == null) "" else value.toString()

    /**
     * Build Activity.csv rows: one aggregate row per day plus one row per
     * session with the day's aggregates repeated — exactly the reference
     * app's layout, which the importer relies on.
     */
    fun activityRows(days: List<HcDay>, zone: ZoneId): List<List<String>> {
        val rows = mutableListOf<List<String>>()
        for (day in days) {
            val base = listOf(
                day.date.format(dayFmt),
                day.origins.sorted().joinToString(";"),
                zone.id,
                num(day.steps), num(day.distanceM), "", "",
                num(day.totalCaloriesKcal),
            ) + List(11) { "" }
            if (day.sessions.isEmpty() &&
                (day.steps != null || day.distanceM != null || day.totalCaloriesKcal != null)
            ) {
                // Day with data but no sessions still gets its aggregate row.
                rows.add(base + List(5) { "" })
            }
            for (s in day.sessions) {
                val start = LocalDateTime.ofInstant(s.start, zone).format(momentFmt)
                val minutes = java.time.Duration.between(s.start, s.end).toMinutes()
                rows.add(
                    base + listOf(
                        start, "${s.code} - ${s.label}", minutes.toString(), "", "",
                    )
                )
            }
        }
        return rows
    }

    /** Build Vitals.csv rows: daily heart-rate summaries only. */
    fun vitalsRows(days: List<HcDay>, zone: ZoneId): List<List<String>> {
        val rows = mutableListOf<List<String>>()
        for (day in days) {
            if (day.hrMin == null && day.hrMax == null && day.hrAvg == null) continue
            rows.add(
                listOf(
                    day.date.format(dayFmt),
                    day.origins.sorted().joinToString(";"),
                    zone.id,
                    num(day.hrMin), num(day.hrMax), num(day.hrAvg),
                ) + List(15) { "" }
            )
        }
        return rows
    }

    private fun render(header: List<String>, rows: List<List<String>>): String {
        fun cell(v: String): String =
            if (v.contains(',') || v.contains('"') || v.contains('\n')) {
                "\"" + v.replace("\"", "\"\"") + "\""
            } else v
        return buildString {
            appendLine(header.joinToString(","))
            for (row in rows) appendLine(row.map(::cell).joinToString(","))
        }
    }

    /**
     * Save a CSV to Downloads so it can be uploaded to the tracker.
     * Scoped storage (minSdk 29) means no storage permission is needed.
     *
     * @return display name of the saved file.
     */
    fun save(context: Context, fileName: String, content: String): String {
        val bytes = content.toByteArray(Charsets.UTF_8)
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, fileName)
            put(MediaStore.Downloads.MIME_TYPE, "text/csv")
            put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
        }
        val uri = context.contentResolver.insert(
            MediaStore.Downloads.EXTERNAL_CONTENT_URI, values
        ) ?: error("Could not create $fileName in Downloads")
        context.contentResolver.openOutputStream(uri)!!.use { it.write(bytes) }
        return fileName
    }

    fun renderActivity(days: List<HcDay>, zone: ZoneId): String =
        render(ACTIVITY_HEADER, activityRows(days, zone))

    fun renderVitals(days: List<HcDay>, zone: ZoneId): String =
        render(VITALS_HEADER, vitalsRows(days, zone))
}
