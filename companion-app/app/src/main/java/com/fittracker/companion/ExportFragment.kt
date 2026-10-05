package com.fittracker.companion

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.activity.result.contract.ActivityResultContracts
import androidx.fragment.app.Fragment
import androidx.health.connect.client.PermissionController
import androidx.lifecycle.lifecycleScope
import com.fittracker.companion.databinding.FragmentExportBinding
import java.time.ZoneId
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Health Connect export tab. Reads the last N days on demand (manual sync
 * only — no background work, no battery impact) and either saves
 * Activity.csv + Vitals.csv to Downloads or pushes straight to the Pi.
 *
 * Sleep is never requested: the owner decided sleep sessions stay out of the
 * tracker, so the permission is not declared and the data is never read.
 */
class ExportFragment : Fragment() {

    private var _binding: FragmentExportBinding? = null
    private val binding get() = _binding!!

    private lateinit var hc: HealthConnectManager
    private val zone: ZoneId = ZoneId.systemDefault()

    private val permissionLauncher = registerForActivityResult(
        PermissionController.createRequestPermissionResultContract()
    ) { granted ->
        if (granted.containsAll(hc.permissions)) {
            log("Permissions granted.")
        } else {
            log("Some permissions were refused — related data will be missing. " +
                "Re-grant them in the Health Connect app under App permissions.")
        }
    }

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?
    ): View {
        _binding = FragmentExportBinding.inflate(inflater, container, false)
        hc = HealthConnectManager(requireContext())

        binding.grantButton.setOnClickListener { requestPermissions() }
        binding.exportCsvButton.setOnClickListener { runExport(saveCsv = true) }
        binding.pushButton.setOnClickListener { runExport(saveCsv = false) }
        return binding.root
    }

    private fun requestPermissions() {
        val client = hc.clientOrNull()
        if (client == null) {
            log("Health Connect is not available on this phone. " +
                "On Android 13 and below, install it from the Play Store.")
            return
        }
        permissionLauncher.launch(hc.permissions)
    }

    private fun selectedDays(): Int = when (binding.rangeSpinner.selectedItemPosition) {
        0 -> 7
        1 -> 30
        2 -> 90
        else -> 30
    }

    private fun runExport(saveCsv: Boolean) {
        if (hc.clientOrNull() == null) {
            log("Health Connect is not available — grant access first.")
            return
        }
        setBusy(true)
        log(if (saveCsv) "Reading Health Connect…" else "Reading Health Connect…")
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val days = hc.readDays(selectedDays())
                if (days.isEmpty()) {
                    log("No data returned. Check the date range and permissions.")
                    return@launch
                }
                if (saveCsv) {
                    val activity = CsvExporter.renderActivity(days, zone)
                    val vitals = CsvExporter.renderVitals(days, zone)
                    val aName = CsvExporter.save(requireContext(), "Activity.csv", activity)
                    val vName = CsvExporter.save(requireContext(), "Vitals.csv", vitals)
                    log("Saved $aName (${days.size} days) and $vName to Downloads. " +
                        "Upload them on the tracker's import page.")
                } else {
                    val baseUrl = Prefs.baseUrl(requireContext())
                    val apiKey = Prefs.apiKey(requireContext())
                    if (apiKey.isEmpty()) {
                        log("No API key set — enter it in Settings first.")
                        return@launch
                    }
                    val records = days.flatMap { PiApiClient.recordsForDay(it, zone) }
                    val reply = PiApiClient.push(baseUrl, apiKey, records)
                    log("Pushed ${records.size} records: " +
                        "imported=${reply.optInt("imported")}, " +
                        "skipped=${reply.optInt("skipped")}, " +
                        "enriched=${reply.optInt("enriched")}.")
                    val conflicts = reply.optJSONArray("conflicts")
                    if (conflicts != null && conflicts.length() > 0) {
                        log("${conflicts.length()} conflict(s) need settling on the profile page.")
                    }
                }
            } catch (e: SecurityException) {
                log("Permission was revoked mid-read. Grant it again, then retry.")
            } catch (e: Exception) {
                log("Failed: ${e.message}")
            } finally {
                withContext(Dispatchers.Main) { setBusy(false) }
            }
        }
    }

    private fun setBusy(busy: Boolean) {
        binding.exportCsvButton.isEnabled = !busy
        binding.pushButton.isEnabled = !busy
        binding.grantButton.isEnabled = !busy
        binding.progressBar.visibility = if (busy) View.VISIBLE else View.GONE
    }

    private fun log(line: String) {
        // Called from background threads; post to the view safely.
        val view = _binding ?: return
        view.logView.post {
            view.logView.append(line + "\n")
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
