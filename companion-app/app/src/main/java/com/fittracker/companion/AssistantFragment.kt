package com.fittracker.companion

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import com.fittracker.companion.databinding.FragmentAssistantBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Assistant tab (Phase 5 placeholder with the wiring already in place).
 *
 * The contract the server side will implement — agreed here so both ends
 * can be built independently:
 * - ``POST <tracker>/api/assistant/ask`` with header ``X-API-Key`` and body
 *   ``{"message": "..."}``
 * - ``200`` with ``{"reply": "..."}``.
 *
 * Until that endpoint exists the tab says so honestly instead of pretending.
 * The equipment profiles, workout history and body measurements already in
 * SQLite are the knowledge base it will query — that data work is done,
 * which is why this tab is UI-only.
 */
class AssistantFragment : Fragment() {

    private var _binding: FragmentAssistantBinding? = null
    private val binding get() = _binding!!

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?
    ): View {
        _binding = FragmentAssistantBinding.inflate(inflater, container, false)
        append("Assistant isn't built yet (Phase 5).\n" +
            "When it is, this tab will answer questions using your workouts, " +
            "equipment profiles and measurements.\n")
        binding.sendButton.setOnClickListener { ask() }
        return binding.root
    }

    private fun ask() {
        val message = binding.input.text.toString().trim()
        if (message.isEmpty()) return
        binding.input.text.clear()
        append("You: $message\n")
        append("…\n")
        lifecycleScope.launch(Dispatchers.IO) {
            val reply = try {
                postAsk(message)
            } catch (e: Exception) {
                null
            }
            withContext(Dispatchers.Main) {
                append(if (reply != null) "Assistant: $reply\n" else
                    "Assistant: not available yet — the server endpoint " +
                    "POST /api/assistant/ask does not exist.\n")
            }
        }
    }

    /** Returns the reply text, or null when the endpoint is absent/broken. */
    private fun postAsk(message: String): String? {
        val baseUrl = Prefs.baseUrl(requireContext())
        val apiKey = Prefs.apiKey(requireContext())
        val url = URL("$baseUrl/api/assistant/ask")
        val body = JSONObject().put("message", message).toString()
        val conn = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15_000
            readTimeout = 60_000
            setRequestProperty("Accept", "application/json")
            setRequestProperty("Content-Type", "application/json")
            if (apiKey.isNotEmpty()) setRequestProperty("X-API-Key", apiKey)
            doOutput = true
            outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
        }
        try {
            if (conn.responseCode !in 200..299) return null
            val text = conn.inputStream.bufferedReader().readText()
            return JSONObject(text).optString("reply", null)
        } finally {
            conn.disconnect()
        }
    }

    private fun append(line: String) {
        _binding?.conversation?.post {
            _binding?.conversation?.append(line)
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
