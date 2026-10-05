package com.fittracker.companion

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import com.fittracker.companion.databinding.FragmentScanBinding
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions

/**
 * Equipment QR scanner. The tracker's equipment rows carry QR labels whose
 * URL points at the equipment page — scanning one jumps the Tracker tab
 * straight there instead of navigating by hand from a blurry photo of a
 * machine label.
 */
class ScanFragment : Fragment() {

    private var _binding: FragmentScanBinding? = null
    private val binding get() = _binding!!

    private val cameraPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) launchScanner()
        else binding.scanResult.text = "Camera permission is needed to scan labels."
    }

    private val scanner = registerForActivityResult(ScanContract()) { result ->
        if (result.contents == null) {
            binding.scanResult.text = "No code scanned."
            return@registerForActivityResult
        }
        val contents = result.contents
        binding.scanResult.text = contents
        // Equipment labels point back at the tracker: open them in its tab.
        // Anything else is shown as text — the app never follows surprises.
        val base = Prefs.baseUrl(requireContext())
        if (contents.startsWith(base)) {
            parentFragmentManager.beginTransaction()
                .replace(R.id.fragment_container, TrackerFragment.withUrl(contents))
                .commit()
        }
    }

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?
    ): View {
        _binding = FragmentScanBinding.inflate(inflater, container, false)
        binding.scanButton.setOnClickListener {
            if (ContextCompat.checkSelfPermission(
                    requireContext(), Manifest.permission.CAMERA
                ) == PackageManager.PERMISSION_GRANTED
            ) {
                launchScanner()
            } else {
                cameraPermission.launch(Manifest.permission.CAMERA)
            }
        }
        return binding.root
    }

    private fun launchScanner() {
        scanner.launch(
            ScanOptions()
                .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                .setPrompt("Point at an equipment QR label")
                .setBeepEnabled(true)
                .setOrientationLocked(false)
        )
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
