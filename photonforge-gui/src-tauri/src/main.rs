#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod mount_monitor;

#[cfg(feature = "tauri")]
fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![mount_monitor::get_device_state])
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || mount_monitor::run(handle));
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error running PhotonForge");
}

#[cfg(not(feature = "tauri"))]
fn main() {}
