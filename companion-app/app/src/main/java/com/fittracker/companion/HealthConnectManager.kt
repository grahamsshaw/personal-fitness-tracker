package com.fittracker.companion

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.DistanceRecord
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.records.TotalCaloriesBurnedRecord
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/**
 * One exercise session as the tracker understands it.
 *
 * @property code Health Connect exercise-type id (e.g. 79). Kept because the
 *   tracker's CSV importer keys sessions partly on the human label, and the
 *   code disambiguates types that share a label.
 * @property label Human label (e.g. "Walking").
 * @property start session start (device time zone).
 * @property end session end.
 */
data class HcSession(
    val code: Int,
    val label: String,
    val start: Instant,
    val end: Instant,
)

/** One day of aggregate readings plus that day's sessions. */
data class HcDay(
    val date: LocalDate,
    val steps: Long?,
    val distanceM: Double?,
    val totalCaloriesKcal: Double?,
    val hrMin: Long?,
    val hrMax: Long?,
    val hrAvg: Double?,
    val origins: Set<String>,
    val sessions: List<HcSession>,
)

/**
 * All Health Connect access lives here so the UI never touches the client
 * directly. Reads only — this app never writes to Health Connect.
 */
class HealthConnectManager(private val context: Context) {

    private val zone: ZoneId = ZoneId.systemDefault()

    /** Permissions covering exactly what the tracker imports: no sleep. */
    val permissions: Set<String> = setOf(
        HealthPermission.getReadPermission(StepsRecord::class),
        HealthPermission.getReadPermission(DistanceRecord::class),
        HealthPermission.getReadPermission(TotalCaloriesBurnedRecord::class),
        HealthPermission.getReadPermission(ExerciseSessionRecord::class),
        HealthPermission.getReadPermission(HeartRateRecord::class),
    )

    /** Null when Health Connect is unavailable (old device, no Play Store app). */
    fun clientOrNull(): HealthConnectClient? =
        HealthConnectClient.getOrNull(context)

    /**
     * Exercise-type id to the label the tracker's CSV importer expects.
     * Only types the owner's watch has ever produced are mapped by hand;
     * everything else is honestly "Other Workout" with its code preserved.
     */
    fun sessionLabel(code: Int): String = when (code) {
        ExerciseSessionRecord.EXERCISE_TYPE_OTHER_WORKOUT -> "Other Workout"
        ExerciseSessionRecord.EXERCISE_TYPE_WALKING -> "Walking"
        ExerciseSessionRecord.EXERCISE_TYPE_ELLIPTICAL -> "Elliptical"
        ExerciseSessionRecord.EXERCISE_TYPE_ROWING_MACHINE -> "Rowing Machine"
        else -> "Other Workout"
    }

    /**
     * Read [daysBack] days ending today: per-day aggregates plus sessions.
     *
     * Aggregation is done here (sums per day, HR min/max/mean) so the CSV
     * writer and the Pi push share one reading of the data.
     */
    suspend fun readDays(daysBack: Int): List<HcDay> {
        val client = clientOrNull() ?: return emptyList()
        val today = LocalDate.now(zone)
        val startDay = today.minusDays(daysBack.toLong() - 1)
        val start = startDay.atStartOfDay(zone).toInstant()
        val end = today.plusDays(1).atStartOfDay(zone).toInstant()
        val filter = TimeRangeFilter.between(start, end)

        val steps = client.readRecords(ReadRecordsRequest(StepsRecord::class, filter))
        val distances = client.readRecords(ReadRecordsRequest(DistanceRecord::class, filter))
        val calories = client.readRecords(
            ReadRecordsRequest(TotalCaloriesBurnedRecord::class, filter)
        )
        val sessions = client.readRecords(
            ReadRecordsRequest(ExerciseSessionRecord::class, filter)
        )
        val heartRates = client.readRecords(
            ReadRecordsRequest(HeartRateRecord::class, filter)
        )

        val origins = mutableMapOf<LocalDate, MutableSet<String>>()
        fun originOf(pkg: String, time: Instant) {
            origins.getOrPut(LocalDate.ofInstant(time, zone)) { mutableSetOf() }.add(pkg)
        }

        val stepsByDay = mutableMapOf<LocalDate, Long>()
        for (r in steps.records) {
            val day = LocalDate.ofInstant(r.startTime, zone)
            stepsByDay[day] = (stepsByDay[day] ?: 0L) + r.count
            originOf(r.metadata.dataOrigin.packageName, r.startTime)
        }
        val distByDay = mutableMapOf<LocalDate, Double>()
        for (r in distances.records) {
            val day = LocalDate.ofInstant(r.startTime, zone)
            distByDay[day] = (distByDay[day] ?: 0.0) + r.distance.inMeters
            originOf(r.metadata.dataOrigin.packageName, r.startTime)
        }
        val calByDay = mutableMapOf<LocalDate, Double>()
        for (r in calories.records) {
            val day = LocalDate.ofInstant(r.startTime, zone)
            calByDay[day] = (calByDay[day] ?: 0.0) + r.energy.inKilocalories
            originOf(r.metadata.dataOrigin.packageName, r.startTime)
        }

        val hrSamples = mutableMapOf<LocalDate, MutableList<Long>>()
        for (r in heartRates.records) {
            for (s in r.samples) {
                val day = LocalDate.ofInstant(s.time, zone)
                hrSamples.getOrPut(day) { mutableListOf() }.add(s.beatsPerMinute)
                originOf(r.metadata.dataOrigin.packageName, s.time)
            }
        }

        val sessionsByDay = mutableMapOf<LocalDate, MutableList<HcSession>>()
        for (r in sessions.records) {
            val day = LocalDate.ofInstant(r.startTime, zone)
            sessionsByDay.getOrPut(day) { mutableListOf() }.add(
                HcSession(r.exerciseType, sessionLabel(r.exerciseType), r.startTime, r.endTime)
            )
            originOf(r.metadata.dataOrigin.packageName, r.startTime)
        }

        val days = mutableSetOf<LocalDate>()
        days += stepsByDay.keys + distByDay.keys + calByDay.keys +
            hrSamples.keys + sessionsByDay.keys

        return days.sorted().map { day ->
            val samples = hrSamples[day].orEmpty()
            HcDay(
                date = day,
                steps = stepsByDay[day],
                distanceM = distByDay[day],
                totalCaloriesKcal = calByDay[day],
                hrMin = samples.minOrNull(),
                hrMax = samples.maxOrNull(),
                hrAvg = if (samples.isEmpty()) null else samples.average(),
                origins = origins[day].orEmpty(),
                sessions = sessionsByDay[day].orEmpty().sortedBy { it.start },
            )
        }
    }
}
