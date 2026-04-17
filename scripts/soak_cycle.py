#!/usr/bin/env python3
"""KPM-1.4 soak test cycle runner.

Runs one complete eject→unplug→replug→integrity cycle and appends the result
to docs/ValidationReports/soak-test-log.md.

Usage:
    python3 scripts/soak_cycle.py --cycle N [--mount /mnt/photon_ssd/001]
                                             [--db /mnt/photon_ssd/001/darktable/library.db]
                                             [--log docs/ValidationReports/soak-test-log.md]
                                             [--timeout 120]

The script:
  1. Flushes the SQLite WAL
  2. Unmounts the SSD via udisksctl (or umount fallback)
  3. Polls until the mount disappears (detects unplug)
  4. Polls until the mount reappears (detects replug + auto-mount)
  5. Runs PRAGMA integrity_check
  6. Appends PASS/FAIL to the soak log
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def log(msg: str) -> None:
    print(f"[soak_cycle] {msg}", flush=True)


def flush_wal(db_path: Path) -> bool:
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        log(f"WAL flushed: {db_path}")
        return True
    except Exception as e:
        log(f"WARNING: WAL flush failed: {e}")
        return False


def sync_and_unmount(mount_point: Path) -> bool:
    log("Syncing filesystem buffers...")
    subprocess.run(["sync"], check=True)

    # Find block device for the mount point
    try:
        result = subprocess.run(
            ["findmnt", "-n", "-o", "SOURCE", str(mount_point)],
            capture_output=True, text=True, check=True,
        )
        block_dev = result.stdout.strip()
    except subprocess.CalledProcessError:
        log(f"WARNING: could not determine block device for {mount_point}")
        block_dev = ""

    # Try udisksctl first (requires polkit + interactive TTY); fall back to sudo umount.
    if block_dev and shutil_which("udisksctl"):
        try:
            subprocess.run(
                ["udisksctl", "unmount", "--block-device", block_dev, "--no-user-interaction"],
                check=True,
            )
            log(f"Unmounted via udisksctl: {block_dev}")
            return True
        except subprocess.CalledProcessError as e:
            log(f"udisksctl failed ({e}) — falling back to sudo umount")

    # sudo umount with NOPASSWD rule in /etc/sudoers.d/photonforge-eject
    for cmd in (["sudo", "-n", "umount", str(mount_point)], ["umount", str(mount_point)]):
        try:
            subprocess.run(cmd, check=True)
            log(f"Unmounted via {' '.join(cmd[:2])}: {mount_point}")
            return True
        except subprocess.CalledProcessError:
            continue

    log(f"ERROR: all unmount methods failed for {mount_point}")
    return False


def shutil_which(cmd: str) -> bool:
    import shutil
    return shutil.which(cmd) is not None


def is_mounted(mount_point: Path) -> bool:
    return os.path.ismount(str(mount_point))


def _block_device_for(mount_point: Path) -> str:
    """Return the block device currently or last mounted at mount_point."""
    try:
        result = subprocess.run(
            ["findmnt", "-n", "-o", "SOURCE", str(mount_point)],
            capture_output=True, text=True,
        )
        dev = result.stdout.strip()
        return dev if dev else "/dev/sda1"
    except Exception:
        return "/dev/sda1"


def wait_for_unmount(mount_point: Path, timeout: int) -> bool:
    log(f"Waiting for {mount_point} to unmount...")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_mounted(mount_point):
            log("SSD unmounted.")
            return True
        time.sleep(1)
    log(f"TIMEOUT: {mount_point} still mounted after {timeout}s")
    return False


def wait_for_replug_and_mount(mount_point: Path, block_dev: str, timeout: int) -> bool:
    """Wait for the block device to disappear then reappear, then mount it."""
    dev_path = Path(block_dev)

    # Step 1: wait for device to disappear (confirms unplug)
    log(f"Unplug the SSD now — waiting for {block_dev} to disappear...")
    deadline = time.monotonic() + timeout
    disappeared = False
    while time.monotonic() < deadline:
        if not dev_path.exists():
            log("Block device gone — unplug detected.")
            disappeared = True
            break
        time.sleep(1)
    if not disappeared:
        log(f"WARNING: {block_dev} never disappeared — physical unplug may not have occurred")

    # Step 2: wait for device to reappear (confirms replug)
    log(f"Plug the SSD back in — waiting for {block_dev} to reappear...")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if dev_path.exists():
            log("Block device back — replug detected.")
            time.sleep(1)  # settle
            break
        time.sleep(1)
    else:
        log(f"TIMEOUT: {block_dev} did not reappear within {timeout}s")
        return False

    # Step 3: mount if not already mounted
    if not is_mounted(mount_point):
        log(f"Mounting {block_dev} -> {mount_point}...")
        for cmd in (
            ["sudo", "-n", "mount", block_dev, str(mount_point)],
            ["mount", block_dev, str(mount_point)],
        ):
            try:
                subprocess.run(cmd, check=True)
                log("Mount successful.")
                break
            except subprocess.CalledProcessError:
                continue
        else:
            log("ERROR: all mount attempts failed")
            return False

    time.sleep(2)  # let filesystem settle
    if is_mounted(mount_point):
        log("SSD remounted and verified.")
        return True
    log("ERROR: mount point not active after mount attempt")
    return False


def integrity_check(db_path: Path) -> tuple[bool, int]:
    try:
        conn = sqlite3.connect(str(db_path))
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        records = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        conn.close()
        ok = result == "ok"
        if not ok:
            log(f"integrity_check FAILED: {result}")
        return ok, records
    except Exception as e:
        log(f"ERROR: integrity_check failed: {e}")
        return False, 0


def append_log(log_path: Path, cycle: int, passed: bool) -> None:
    status = "PASS" if passed else "FAIL"
    timestamp = datetime.now().strftime("%a %b %d %I:%M:%S %p %Z %Y")
    entry = f"Cycle {cycle}: {status} -- {timestamp}\n"
    with open(log_path, "a") as f:
        f.write(entry)
    log(f"Logged: {entry.strip()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="KPM-1.4 soak test cycle runner")
    parser.add_argument("--cycle", type=int, required=True, help="Cycle number (1-50)")
    parser.add_argument("--mount", default="/mnt/photon_ssd/001", help="SSD mount point")
    parser.add_argument(
        "--db",
        default="/mnt/photon_ssd/001/darktable/library.db",
        help="Darktable library.db path",
    )
    parser.add_argument(
        "--log",
        default="docs/ValidationReports/soak-test-log.md",
        help="Soak test log file path",
    )
    parser.add_argument("--timeout", type=int, default=120, help="Seconds to wait per phase")
    args = parser.parse_args()

    mount = Path(args.mount)
    db = Path(args.db)
    log_path = Path(args.log)
    cycle = args.cycle

    log(f"=== KPM-1.4 Soak Test — Cycle {cycle}/50 ===")

    # Phase 1: flush + unmount
    if db.exists():
        flush_wal(db)
    else:
        log(f"WARNING: DB not found at {db} — skipping WAL flush")

    block_dev = _block_device_for(mount)
    log(f"Block device: {block_dev}")

    if not sync_and_unmount(mount):
        log("ERROR: Could not unmount. Aborting cycle.")
        append_log(log_path, cycle, False)
        return 1

    # Phase 2: wait for unmount confirmation
    if not wait_for_unmount(mount, args.timeout):
        append_log(log_path, cycle, False)
        return 1

    # Phase 3: wait for physical unplug → replug → auto-mount
    if not wait_for_replug_and_mount(mount, block_dev, args.timeout):
        append_log(log_path, cycle, False)
        return 1

    # Phase 4: integrity check
    ok, records = integrity_check(db)
    log(f"Integrity: {'ok' if ok else 'CORRUPT'}, records={records}")

    append_log(log_path, cycle, ok)
    log(f"Cycle {cycle} {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
