package com.fittracker.companion

import java.net.HttpURLConnection
import java.net.URL
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import org.json.JSONArray
import org.json.JSONObject

/**
 * Talks to the tracker's push endpoint over the home LAN.
 *
 * Contract (server side: ``fitness_app/routes/health_connect.py``):
 * - ``POST /api/health-connect/push`` with header ``X-API-Key`` and body
 *   ``{"records": [...]}`` → 202 with imported/skipped/enriched/conflicts.
 * - ``GET /api/health-connect/status`` → last push info, no key needed.
 *
 * Plain HttpURLConnection is enough for two small JSON calls; no HTTP
 * library is worth the dependency for this.
 */
object PiApiClient {

    private val momentFmt = DateTimeFormatter.ISO_LOCAL_DATE_TIME

    /** Map one exported day to push-endpoint record dicts. */
    fun recordsForDay(day: HcDay, zone: ZoneId): List<JSONObject> {
        val out = mutableListOf<JSONObject>()
        val dayStart = day.date.atStartOfDay(zone)

        if (day.steps != null || day.distanceM != null || day.totalCaloriesKcal != null) {
            out.add(JSONObject()
                .put("type", "steps")
                .put("source_id", "hcapp-day:${day.date}")
                .put("start", dayStart.format(momentFmt))
                .put("steps", day.steps ?: JSONObject.NULL)
                .put("distance_m", day.distanceM ?: JSONObject.NULL)
                .put("calories", day.totalCaloriesKcal ?: JSONObject.NULL)
                .put("avg_heart_rate", day.hrAvg ?: JSONObject.NULL))
        }
        for (s in day.sessions) {
            out.add(JSONObject()
                .put("type", "exercise")
                .put("source_id", "hcapp-sess:${s.start.epochSecond}:${s.code}")
                .put("start", s.start.atZone(zone).format(momentFmt))
                .put("end", s.end.atZone(zone).format(momentFmt))
                .put("exercise_type", s.label))
        }
        return out
    }

    /** POST records; returns the server's JSON reply. Throws on transport error. */
    fun push(baseUrl: String, apiKey: String, records: List<JSONObject>): JSONObject {
        val url = URL("$baseUrl/api/health-connect/push")
        val body = JSONObject().put("records", JSONArray(records)).toString()
        return request(url, "POST", apiKey, body)
    }

    /** GET status; returns the server's JSON reply. Throws on transport error. */
    fun status(baseUrl: String): JSONObject =
        request(URL("$baseUrl/api/health-connect/status"), "GET", null, null)

    private fun request(
        url: URL, method: String, apiKey: String?, body: String?
    ): JSONObject {
        val conn = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 15_000
            readTimeout = 30_000
            setRequestProperty("Accept", "application/json")
            if (apiKey != null) {
                setRequestProperty("X-API-Key", apiKey)
                setRequestProperty("Content-Type", "application/json")
                doOutput = true
                outputStream.use { it.write(body!!.toByteArray(Charsets.UTF_8)) }
            }
        }
        try {
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream.bufferedReader().readText()
            if (code !in 200..299) error("Server returned $code: $text")
            return JSONObject(text)
        } finally {
            conn.disconnect()
        }
    }
}
