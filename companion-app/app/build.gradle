plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    // Rename this if you want your own identity in Health Connect's
    // "connected apps" list. If you do, update applicationId below AND the
    // Source(s) expectations nowhere else depend on it.
    namespace = "com.fittracker.companion"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.fittracker.companion"
        // 29 (Android 10) is the floor: it guarantees scoped storage, so
        // saving CSVs to Downloads needs no storage permission. Below
        // Android 14, Health Connect comes from the Play Store app.
        minSdk = 29
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        viewBinding = true
    }
}

dependencies {
    // AndroidX core / UI
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.webkit:webkit:1.12.1")
    implementation("androidx.preference:preference-ktx:1.2.1")
    // Coroutines tied to the UI lifecycle (lifecycleScope in fragments).
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.6")

    // Health Connect on-device client. Check for a newer 1.x before building.
    implementation("androidx.health.connect:connect-client:1.1.0")

    // QR scanning (equipment labels). JourneyApps wraps ZXing in one call.
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")

    // Plain HTTP for the Pi push endpoint; no extra client library needed
    // (HttpURLConnection is enough for two small JSON calls).
}
