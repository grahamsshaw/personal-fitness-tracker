package com.fittracker.companion

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.fragment.app.Fragment
import com.fittracker.companion.databinding.FragmentSettingsBinding

/** Tracker URL + API key, entered once and kept on the phone. */
class SettingsFragment : Fragment() {

    private var _binding: FragmentSettingsBinding? = null
    private val binding get() = _binding!!

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?
    ): View {
        _binding = FragmentSettingsBinding.inflate(inflater, container, false)
        binding.baseUrlInput.setText(Prefs.baseUrl(requireContext()))
        // The key itself is never shown back: it is a secret, and shoulder
        // readers exist. Clearing it requires typing a new one.
        binding.apiKeyInput.hint = if (Prefs.apiKey(requireContext()).isEmpty()) {
            "Not set"
        } else {
            "Set (enter a new key to replace it)"
        }
        binding.saveButton.setOnClickListener {
            val baseUrl = binding.baseUrlInput.text.toString()
            val apiKey = binding.apiKeyInput.text.toString()
            if (baseUrl.isBlank()) {
                Toast.makeText(requireContext(), "Tracker URL is required", Toast.LENGTH_SHORT)
                    .show()
                return@setOnClickListener
            }
            Prefs.save(
                requireContext(), baseUrl,
                apiKey.ifBlank { Prefs.apiKey(requireContext()) },
            )
            binding.apiKeyInput.text.clear()
            Toast.makeText(requireContext(), "Saved", Toast.LENGTH_SHORT).show()
        }
        return binding.root
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
