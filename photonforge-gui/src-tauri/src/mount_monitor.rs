use serde::Serialize;
use std::path::Path;
#[cfg(feature = "tauri")]
use tauri::{AppHandle, Emitter};

#[derive(Clone, Serialize, Debug, PartialEq)]
pub struct DeviceState {
    pub ssd_mounted: bool,
    pub ssd_label: Option<String>,
    pub sd_mounted: bool,
}

pub fn parse_proc_mounts(content: &str) -> DeviceState {
    let mut ssd_mounted = false;
    let mut sd_mounted = false;

    for line in content.lines() {
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() < 2 {
            continue;
        }
        let device = parts[0];
        let mount_point = parts[1];
        if mount_point == "/mnt/photon_sd" {
            sd_mounted = true;
        } else if mount_point.starts_with("/mnt/photon_ssd/") {
            ssd_mounted = true;
        } else if mount_point.starts_with("/media/") && is_removable_block_device(device) {
            // Fallback for dev environments where udev rules aren't installed and
            // the SD card auto-mounts via udisks2 to /media/<user>/<label>.
            sd_mounted = true;
        }
    }

    DeviceState {
        ssd_mounted,
        ssd_label: if ssd_mounted { read_ssd_label() } else { None },
        sd_mounted,
    }
}

fn is_removable_block_device(device: &str) -> bool {
    // Accept /dev/sd* only (Yoga 910 SD reader is USB, shows as /dev/sdX).
    let name = device.strip_prefix("/dev/").unwrap_or("");
    if !name.starts_with("sd") {
        return false;
    }
    // "sdb1" → "sdb"
    let base = name.trim_end_matches(|c: char| c.is_ascii_digit());
    std::fs::read_to_string(format!("/sys/block/{}/removable", base))
        .map(|s| s.trim() == "1")
        .unwrap_or(false)
}

fn read_ssd_label() -> Option<String> {
    let by_label = Path::new("/dev/disk/by-label");
    if !by_label.exists() {
        return None;
    }
    std::fs::read_dir(by_label).ok()?.find_map(|entry| {
        let name = entry.ok()?.file_name().to_string_lossy().into_owned();
        if name.starts_with("PHOTON-") {
            Some(name)
        } else {
            None
        }
    })
}

#[cfg(feature = "tauri")]
#[tauri::command]
pub fn get_device_state() -> DeviceState {
    read_mounts()
}

#[cfg(feature = "tauri")]
fn read_mounts() -> DeviceState {
    let content = std::fs::read_to_string("/proc/mounts").unwrap_or_default();
    parse_proc_mounts(&content)
}

#[cfg(feature = "tauri")]
pub fn run(app: AppHandle) {
    // Wait for the WebView to load and register its event listener before
    // emitting the initial state — /proc/mounts doesn't support inotify.
    std::thread::sleep(std::time::Duration::from_millis(500));

    let mut prev = read_mounts();
    let _ = app.emit("device-state-changed", prev.clone());

    // Emit unconditionally for the first 5 polls (~10s) so the WebView has
    // multiple chances to catch the initial state regardless of load time.
    let mut force_remaining: u8 = 5;
    loop {
        std::thread::sleep(std::time::Duration::from_secs(2));
        let next = read_mounts();
        if next != prev || force_remaining > 0 {
            let _ = app.emit("device-state-changed", next.clone());
            prev = next;
            if force_remaining > 0 {
                force_remaining -= 1;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_mounts_all_absent() {
        let state = parse_proc_mounts("");
        assert!(!state.ssd_mounted);
        assert!(state.ssd_label.is_none());
        assert!(!state.sd_mounted);
    }

    #[test]
    fn sd_mount_detected() {
        let content = "/dev/sda1 /mnt/photon_sd ext4 rw 0 0\n";
        let state = parse_proc_mounts(content);
        assert!(state.sd_mounted);
        assert!(!state.ssd_mounted);
    }

    #[test]
    fn ssd_mount_detected() {
        let content = "/dev/sdb1 /mnt/photon_ssd/001 ext4 rw 0 0\n";
        let state = parse_proc_mounts(content);
        assert!(state.ssd_mounted);
        assert!(!state.sd_mounted);
    }

    #[test]
    fn both_mounted() {
        let content = "/dev/sda1 /mnt/photon_sd ext4 rw 0 0\n\
                       /dev/sdb1 /mnt/photon_ssd/001 ext4 rw 0 0\n";
        let state = parse_proc_mounts(content);
        assert!(state.sd_mounted);
        assert!(state.ssd_mounted);
    }

    #[test]
    fn unrelated_mounts_ignored() {
        let content = "tmpfs /tmp tmpfs rw 0 0\n/dev/sda2 / ext4 rw 0 0\n";
        let state = parse_proc_mounts(content);
        assert!(!state.ssd_mounted);
        assert!(!state.sd_mounted);
    }

    #[test]
    fn malformed_line_ignored() {
        let content = "incomplete_line\n/dev/sdb1 /mnt/photon_ssd/001 ext4 rw 0 0\n";
        let state = parse_proc_mounts(content);
        assert!(state.ssd_mounted);
    }

    #[test]
    fn nvme_at_media_not_treated_as_sd() {
        // nvme root is not removable — must not be counted as SD.
        let content = "/dev/nvme0n1p1 /media/alex/DATA ext4 rw 0 0\n";
        let state = parse_proc_mounts(content);
        assert!(!state.sd_mounted);
    }
}
