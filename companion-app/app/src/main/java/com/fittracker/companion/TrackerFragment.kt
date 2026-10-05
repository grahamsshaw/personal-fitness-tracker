package com.fittracker.companion

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.webkit.WebViewClient
import androidx.fragment.app.Fragment
import com.fittracker.companion.databinding.FragmentTrackerBinding

/**
 * The Pi's web UI inside a WebView. This is how the phone "integrates the
 * pages we've been building": no duplication, no second UI to maintain —
 * the tracker tab IS the tracker. Flask's session cookie works in the
 * WebView, so flashed messages and forms behave as on desktop.
 */
class TrackerFragment : Fragment() {

    private var _binding: FragmentTrackerBinding? = null
    private val binding get() = _binding!!

    companion object {
        private const val ARG_URL = "start_url"

        /** Open the tracker tab directly on [url] (e.g. a scanned label). */
        fun withUrl(url: String): TrackerFragment = TrackerFragment().apply {
            arguments = Bundle().apply { putString(ARG_URL, url) }
        }
    }

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?
    ): View {
        _binding = FragmentTrackerBinding.inflate(inflater, container, false)
        binding.webView.apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            webViewClient = WebViewClient()
            if (savedInstanceState == null) {
                loadUrl(arguments?.getString(ARG_URL) ?: Prefs.baseUrl(requireContext()))
            } else {
                restoreState(savedInstanceState)
            }
        }
        binding.refreshButton.setOnClickListener { binding.webView.reload() }
        return binding.root
    }

    /** True when the WebView consumed the Back press for its own history. */
    fun goBack(): Boolean {
        val webView = _binding?.webView ?: return false
        return if (webView.canGoBack()) {
            webView.goBack()
            true
        } else {
            false
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        _binding?.webView?.saveState(outState)
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
