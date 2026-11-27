plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "ru.kyrsovaya.mood"
    compileSdk = 35

    defaultConfig {
        applicationId = "ru.kyrsovaya.mood"
        minSdk = 26
        targetSdk = 34
        versionCode = 5
        versionName = "2.0"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin {
    jvmToolchain(17)
}
