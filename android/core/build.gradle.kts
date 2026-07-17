plugins {
    kotlin("jvm") version "2.0.21"
}

// Target 17 bytecode (Android-friendly) while building with whatever JDK >= 17
// is running Gradle — no separate toolchain download needed.
java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

dependencies {
    // JSON tree API only (no @Serializable compiler plugin needed).
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    testImplementation(kotlin("test"))
}

tasks.test {
    useJUnitPlatform()
}
