use notify::{Config, Event, RecommendedWatcher, RecursiveMode, Watcher};
use serde::Serialize;
use std::path::Path;
use std::sync::mpsc;
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
        let mount_point = parts[1];
        if mount_point == "/mnt/photon_sd" {
            sd_mounted = true;
        } else if mount_point.starts_with("/mnt/photon_ssd/") {
            ssd_mounted = true;
        }
    }

    DeviceState {
        ssd_mounted,
        ssd_label: if ssd_mounted { read_ssd_label() } else { None },
        sd_mounted,
    }
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

fn read_mounts() -> DeviceState {
    let content = std::fs::read_to_string("/proc/mounts").unwrap_or_default();
    parse_proc_mounts(&content)
}

pub fn run(app: AppHandle) {
    let initial = read_mounts();
    let _ = app.emit("device-state-changed", initial.clone());

    let (tx, rx) = mpsc::channel::<notify::Result<Event>>();
    let mut watcher = match RecommendedWatcher::new(tx, Config::default()) {
        Ok(w) => w,
        Err(_) => return,
    };

    #[cfg(target_os = "linux")]
    if watcher
        .watch(Path::new("/proc/mounts"), RecursiveMode::NonRecursive)
        .is_err()
    {
        return;
    }

    let mut prev = initial;
    for result in rx {
        if result.is_ok() {
            let next = read_mounts();
            if next != prev {
                let _ = app.emit("device-state-changed", next.clone());
                prev = next;
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
}
