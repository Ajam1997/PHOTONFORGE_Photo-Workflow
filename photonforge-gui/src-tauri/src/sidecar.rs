// Protocol types for the Python sidecar JSON-lines protocol.
// parse_event is scaffolding for future Tauri-side event forwarding;
// in Stage 7.2 the JS plugin layer handles parsing directly.
#![allow(dead_code)]
use serde::Deserialize;

#[derive(Debug, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum SidecarEvent {
    Progress {
        step: String,
        current: u64,
        total: u64,
        message: String,
    },
    Done {
        summary: IngestSummary,
    },
    Error {
        message: String,
    },
    Cartridges {
        items: Vec<CartridgeInfo>,
    },
    ReformatDone {
        label: String,
        mount_point: String,
    },
}

#[derive(Debug, Deserialize)]
pub struct IngestSummary {
    pub total: u64,
    pub duplicates_skipped: u64,
    pub scored: u64,
    pub xmp_written: u64,
    pub db_upserted: u64,
    pub elapsed_seconds: f64,
}

#[derive(Debug, Deserialize)]
pub struct CartridgeInfo {
    pub label: String,
    pub mount_point: String,
    pub free_bytes: u64,
    pub size_bytes: u64,
}

pub fn parse_event(line: &str) -> Option<SidecarEvent> {
    serde_json::from_str(line).ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_progress_event() {
        let line = r#"{"type":"progress","step":"copying","current":42,"total":150,"message":"DSC_0042.ARW"}"#;
        let event = parse_event(line).unwrap();
        match event {
            SidecarEvent::Progress { step, current, total, message } => {
                assert_eq!(step, "copying");
                assert_eq!(current, 42);
                assert_eq!(total, 150);
                assert_eq!(message, "DSC_0042.ARW");
            }
            _ => panic!("unexpected variant"),
        }
    }

    #[test]
    fn parses_done_event() {
        let line = r#"{"type":"done","summary":{"total":150,"duplicates_skipped":8,"scored":142,"xmp_written":142,"db_upserted":142,"elapsed_seconds":47.2}}"#;
        let event = parse_event(line).unwrap();
        match event {
            SidecarEvent::Done { summary } => {
                assert_eq!(summary.total, 150);
                assert_eq!(summary.duplicates_skipped, 8);
            }
            _ => panic!("unexpected variant"),
        }
    }

    #[test]
    fn malformed_json_returns_none() {
        assert!(parse_event("not json {{{").is_none());
    }

    #[test]
    fn parses_error_event() {
        let line = r#"{"type":"error","message":"SD card not mounted"}"#;
        let event = parse_event(line).unwrap();
        match event {
            SidecarEvent::Error { message } => assert_eq!(message, "SD card not mounted"),
            _ => panic!("unexpected variant"),
        }
    }

    #[test]
    fn parses_cartridges_event() {
        let line = r#"{"type":"cartridges","items":[{"label":"PHOTON-001","mount_point":"/mnt/photon_ssd/001","free_bytes":100,"size_bytes":200}]}"#;
        let event = parse_event(line).unwrap();
        match event {
            SidecarEvent::Cartridges { items } => {
                assert_eq!(items.len(), 1);
                assert_eq!(items[0].label, "PHOTON-001");
            }
            _ => panic!("unexpected variant"),
        }
    }
}
