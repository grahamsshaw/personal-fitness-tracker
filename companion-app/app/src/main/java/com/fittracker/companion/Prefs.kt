package com.fittracker.companion

import android.content.Context
import android.content.SharedPreferences
import androidx.core.content.edit

/** Tracker URL and API key, entered once in Settings and kept on the phone. */
object Prefs {
    private const val FILE = "tracker_prefs"
    private const val KEY_BASE_URL = "base_url"
    private const val KEY_API_KEY = "api_key"

    /** Default: the Pi on the home LAN. */
    const val DEFAULT_BASE_URL = "http://192.168.0.97:5000"

    private fun prefs(context: Context): SharedPreferences =
        context.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun baseUrl(context: Context): String =
        prefs(context).getString(KEY_BASE_URL, DEFAULT_BASE_URL)!!
            .trim().trimEnd('/')

    fun apiKey(context: Context): String =
        prefs(context).getString(KEY_API_KEY, "")!!.trim()

    fun save(context: Context, baseUrl: String, apiKey: String) {
        prefs(context).edit {
            putString(KEY_BASE_URL, baseUrl.trim().trimEnd('/'))
            putString(KEY_API_KEY, apiKey.trim())
        }
    }
}
