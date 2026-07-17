pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "photonforge-android"

include(":core")

// The :app module needs the Android SDK (and Google's maven repo). Include it
// only when an SDK is discoverable so `gradle :core:test` works on plain-JVM
// CI/dev machines with no Android toolchain.
val hasSdk = System.getenv("ANDROID_HOME") != null ||
    System.getenv("ANDROID_SDK_ROOT") != null ||
    File(rootDir, "local.properties").let { it.exists() && it.readText().contains("sdk.dir") }
if (hasSdk) {
    include(":app")
} else {
    logger.lifecycle("Android SDK not found - only :core is configured (unit-test/JVM mode)")
}
