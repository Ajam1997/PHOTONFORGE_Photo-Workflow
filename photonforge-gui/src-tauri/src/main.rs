#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod mount_monitor;

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || mount_monitor::run(handle));
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error running PhotonForge");
}
