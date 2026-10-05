package com.fittracker.companion

import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.fragment.app.Fragment
import com.fittracker.companion.databinding.ActivityMainBinding

/**
 * Single activity, five tabs. The Tracker tab is the star: it loads the Pi's
 * own web UI in a WebView, so every page built for the project (dashboard,
 * log workout, profile, imports, equipment) works on the phone unchanged.
 * The native tabs exist for things a web page cannot do: Health Connect,
 * the camera, and (later) the assistant.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.bottomNav.setOnItemSelectedListener { item ->
            val fragment: Fragment = when (item.itemId) {
                R.id.nav_tracker -> TrackerFragment()
                R.id.nav_export -> ExportFragment()
                R.id.nav_scan -> ScanFragment()
                R.id.nav_assistant -> AssistantFragment()
                R.id.nav_settings -> SettingsFragment()
                else -> return@setOnItemSelectedListener false
            }
            supportFragmentManager.beginTransaction()
                .replace(R.id.fragment_container, fragment)
                .commit()
            true
        }
        if (savedInstanceState == null) {
            binding.bottomNav.selectedItemId = R.id.nav_tracker
        }
    }

    /** Let the WebView tab consume Back for its own history first. */
    override fun onBackPressed() {
        val current = supportFragmentManager.findFragmentById(R.id.fragment_container)
        if (current is TrackerFragment && current.goBack()) return
        super.onBackPressed()
    }
}
