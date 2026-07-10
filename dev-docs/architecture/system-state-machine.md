# System State Machine

The SysML **State Machine Diagram** for PHOTONForge. Two concurrent
state machines run side-by-side: the **cartridge lifecycle**
(physical SSD presence) and the **ingest session** (logical workflow
on inserted SD card). They synchronize through the `cartridge_ready`
guard.

## Cartridge Lifecycle

Tracks the physical SSD cartridge (PHOTON-001, etc.) from the
host's perspective. Driven by udisks2 auto-mount + `/proc/mounts`
polling events.

```mermaid
stateDiagram-v2
    [*] --> idle: boot
    idle --> detected: device inserted\n(USB-C front)
    detected --> identified: volume label\nmatches PHOTON-* (lsblk)
    detected --> idle: not a PHOTON cartridge
    identified --> mounting: udisks2 auto-mount
    mounting --> mounted: mount appears in /proc/mounts poll
    mounting --> failed_mount: filesystem error
    failed_mount --> idle: operator removes
    mounted --> in_use: pipeline starts
    in_use --> mounted: pipeline ends
    mounted --> flushing: safe_eject.sh\n(SQLite WAL flush)
    flushing --> unmounted: unmount
    unmounted --> idle: mount gone from /proc/mounts
    in_use --> flushing: forced eject\n(operator pulled cartridge)
    note right of flushing
        Critical KPM-1.4 path:
        WAL flush must complete
        before unmount or library.db
        corrupts.
    end note
```

## Ingest Session

Triggered by SD insertion. Runs once per ingest. Independent of cartridge
state machine except for the `cartridge_ready` guard.

```mermaid
stateDiagram-v2
    [*] --> idle_session
    idle_session --> sd_inserted: new mount in /proc/mounts\n(SD reader, udisks2 auto-mount)
    sd_inserted --> sd_check: read DCIM/
    sd_check --> ingesting: cartridge_ready &&\nphotos found
    sd_check --> empty_warning: cartridge_ready &&\nno photos
    sd_check --> no_cartridge: !cartridge_ready
    no_cartridge --> idle_session: zenity dismissed
    empty_warning --> idle_session: zenity dismissed
    ingesting --> sd_ejected: rsync complete
    sd_ejected --> grouping: SD safe to remove
    grouping --> dedup: clusters formed
    dedup --> scoring: uniques identified
    scoring --> naming: scores written
    naming --> syncing: filenames generated
    syncing --> ready: library.db updated\nXMP sidecars written
    ready --> idle_session: pipeline done

    state scoring {
        [*] --> sharpness
        sharpness --> composition
        composition --> exposure
        exposure --> genre_routing
        genre_routing --> fusion
        fusion --> [*]
    }

    note left of ingesting
        KPM-1.1: ≥ 80% USB 3.0
        bandwidth (≥ 500 MB/s)
    end note
    note right of naming
        KPM-1.2: ≤ 2.5 s/image
        (Florence-2 INT8)
    end note
    note right of ready
        KPM-1.3: peak RSS
        ≤ 1.5 GB across full
        pipeline
    end note
```

## Concurrency

The two state machines synchronize on:

- `cartridge_ready` — true iff cartridge is in `mounted` and not
  `flushing`. The `sd_check` transition reads this.
- `pipeline_running` — true iff the ingest session is between
  `ingesting` and `ready`. The cartridge's `in_use` state reads this;
  a `safe_eject.sh` while `pipeline_running` is true blocks until
  pipeline reaches `ready`.

## SysML traceability

| State / transition | Related requirement |
|---|---|
| `detected → identified` (PHOTON-* match) | FR-1.9 — Library Cartridge Management |
| `mounting → mounted` | NFR-2.3 — Database Portability (library.db must live on the cartridge) |
| `sd_check → ingesting` (cartridge_ready guard) | NFR-2.4 — Interactive UI Prompts |
| `ingesting → sd_ejected` | UN-040 — staging path for safe SD removal |
| `flushing → unmounted` | FR-1.10 — Safe Ejection, KPM-1.4 — Zero corruption |
| `sd_inserted → ingesting` (rsync) | FR-1.1 — Automated Media Ingest, KPM-1.1 |
| `scoring → naming` | FR-1.4..FR-1.7 |
| `naming → syncing` | FR-1.8 — Darktable Integration |
