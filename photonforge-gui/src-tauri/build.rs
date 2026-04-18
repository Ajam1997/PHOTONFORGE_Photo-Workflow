fn main() {
    // Only run tauri_build when compiling with the tauri feature (i.e., not during `cargo test
    // --no-default-features`).  Without the tauri CLI present the build step would fail with
    // "missing cargo:dev instruction", blocking pure-logic unit tests.
    #[cfg(feature = "tauri")]
    tauri_build::build()
}
