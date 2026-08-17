# Cartridge Backup & Archive Implementation Plan

> **SUPERSEDED (2026-08-17, PR #144):** see [`../../../superpowers/plans/2026-08-17-cartridge-backup-archive-plan.md`](../../../superpowers/plans/2026-08-17-cartridge-backup-archive-plan.md).
> Never implemented. Its restic tier survives as Tier 3 of the reconciled plan, which
> merges this design with Task 4a of the portable-drive plan (a second, conflicting
> backup design written 2026-07-31 without sight of this document). Do not implement
> from this file.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the disaster-recovery gap ([issue #131](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/131)) by implementing the stubbed `photo-cartridge` backup subcommands in two tiers: fast local catalog snapshots and full-cartridge archives to local or cloud storage with deduplication + compression.

**Architecture:** Two independent tiers.
- **Tier 1 — catalog snapshot** (offline, instant, free): `VACUUM INTO` each SQLite DB on the cartridge to a rotating N-deep local snapshot directory. Protects the expensive-to-recompute derived work (scoring, naming, stage state) even when no external repo/network is available. Can be hooked into `safe_eject.sh`.
- **Tier 2 — full-cartridge archive** (dedup + compress, local or cloud): a thin wrapper over **restic** (the tool the existing panel/runner wiring already assumes). Content-defined chunking stores the unchanged RAWs once across all snapshots; zstd compression wins on the DBs/sidecars; always-on encryption covers the cloud case. Consumer cloud drives (Google Drive/OneDrive/Dropbox) are reached via restic's native **rclone** backend.

The `photo-cartridge` CLI grows `snapshot`, `archive`, `restore`, `verify`, and `forget` subcommands. The restic/rclone/sqlite logic lives in a new, unit-testable `backup.py`; `cartridge.py` keeps only the thin click layer. The Lua single `CARTRIDGE_CMDS_IMPLEMENTED` flag is replaced by per-command gating so enabling the built commands does not expose the still-stubbed `provision` button.

**Tech Stack:** Python 3.11, sqlite3 (`VACUUM INTO`), click, pytest, subprocess. External binaries: **restic** (≥ 0.16, repo format v2 for compression) and optionally **rclone** — both resolved at runtime via `shutil.which` or a configured path, never bundled. Darktable Lua panel buttons.

## Global Constraints

- **NFR-2.1 (100% offline at runtime):** backup is a *maintenance* operation, not a pipeline operation — it never runs during ingest/score/name. Tier 1 is fully offline. Tier 2 may use the network (same category as provisioning). The pipeline code path must not call any backup function. State this in the ADR.
- **NFR-2.3 (DB + config on the external SSD):** the cartridge root is the parent of the plugin's destination folder (`photonforge.db`, `training_weights.db` at root; `darktable/` beneath). Backup reads the SSD; snapshots default to a hidden dir *on the same cartridge* unless a target is given.
- **Cross-platform:** commands run from Windows (panel launches `Start-Process cmd`) *and* the Debian/Ubuntu runtime. No bash-only constructs in Python; resolve binaries per-OS.
- **Encryption posture:** local Tier-1 snapshots are unencrypted (matches the accepted local stance in `data-security-posture.md`). Tier-2 archives are always encrypted (restic default) because data may leave the device — key comes from the existing `backup_pwfile` pref / `--password-file`.
- **Exclusions (Tier 2):** never archive regenerable or foreign bulk — `models/` (vendored, ~GB, reproducible from provisioning), `.photon-snapshots/` (Tier-1 output), `*__preview.jpg` and `*.mcp.json` (DarktableMCP litter), `*.tmp`.
- **Issue #131 acceptance (must all land):** an ADR (ADR-005), a test proving restore round-trips, and `data-security-posture.md` updated from **open** to the chosen mitigation.
- PRs that change code must update affected docs (docs-impact matrix in `dev-docs/architecture/doc-maintenance-protocol.md`).

## Cartridge layout (the contract every task shares)

```
<root>/                         # cartridge root = parent of the plugin dest folder
  photonforge.db                # analysis catalog (scores, names, stages, embeddings)
  training_weights.db           # genre prototypes / adapter / aesthetic_weights (may be absent)
  darktable/
    library.db                  # DT catalog: user ratings, tags, groups
    data.db                     # DT tag definitions
  photos/                       # RAW + JPEG originals (the bulk; near-incompressible)
  models/                       # vendored ONNX (EXCLUDED from archive)
  .photon-snapshots/            # Tier-1 output (created by this feature; EXCLUDED from archive)
    2026-07-11T14-03-22/
      photonforge.db  training_weights.db  library.db  data.db  MANIFEST.json
```

`backup.cartridge_layout(root)` returns the concrete set of DB paths that exist, so snapshot/archive never hard-code a DB that a given cartridge lacks.

---

### Task 1: cartridge layout + snapshot core (Tier 1, pure Python)

**Files:**
- Create: `src/photo_workflow/backup.py`
- Test: `tests/test_backup_snapshot.py`

**Interfaces:**
- Produces:
  - `@dataclass CartridgeLayout: root: Path; dbs: dict[str, Path]` (keys: `photonforge`, `training_weights`, `dt_library`, `dt_data` — only those that exist on disk)
  - `cartridge_layout(root: Path) -> CartridgeLayout`
  - `snapshot_databases(root: Path, dest_dir: Path) -> Path` — `VACUUM INTO` every present DB into `dest_dir`, write `MANIFEST.json` (timestamp, source paths, byte sizes), return `dest_dir`. Raises `FileNotFoundError` if no DBs found.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_backup_snapshot.py
import json
import sqlite3
from pathlib import Path
import pytest
from photo_workflow.backup import cartridge_layout, snapshot_databases


def _make_cartridge(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "darktable").mkdir(exist_ok=True)
    for rel in ("photonforge.db", "training_weights.db",
                "darktable/library.db", "darktable/data.db"):
        conn = sqlite3.connect(root / rel)
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit(); conn.close()
    return root


def test_layout_finds_present_dbs(tmp_path):
    root = _make_cartridge(tmp_path / "cart")
    layout = cartridge_layout(root)
    assert set(layout.dbs) == {"photonforge", "training_weights", "dt_library", "dt_data"}


def test_layout_omits_absent_dbs(tmp_path):
    root = tmp_path / "cart"; root.mkdir()
    sqlite3.connect(root / "photonforge.db").close()
    layout = cartridge_layout(root)
    assert set(layout.dbs) == {"photonforge"}


def test_snapshot_copies_and_manifests(tmp_path):
    root = _make_cartridge(tmp_path / "cart")
    dest = tmp_path / "snap"
    result = snapshot_databases(root, dest)
    assert result == dest
    assert (dest / "photonforge.db").exists()
    assert (dest / "library.db").exists()          # basename, not the darktable/ path
    # snapshot is a valid, queryable DB (VACUUM INTO produces a clean copy)
    conn = sqlite3.connect(dest / "photonforge.db")
    assert conn.execute("SELECT x FROM t").fetchone()[0] == 1
    conn.close()
    manifest = json.loads((dest / "MANIFEST.json").read_text())
    assert manifest["dbs"]["photonforge"]["bytes"] > 0
    assert "created_at" in manifest


def test_snapshot_raises_when_no_dbs(tmp_path):
    empty = tmp_path / "empty"; empty.mkdir()
    with pytest.raises(FileNotFoundError):
        snapshot_databases(empty, tmp_path / "snap")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_backup_snapshot.py -v`
Expected: FAIL with ModuleNotFoundError (`photo_workflow.backup`)

- [ ] **Step 3: Implement**

```python
# src/photo_workflow/backup.py
"""Cartridge backup: Tier 1 (local SQLite snapshots) + Tier 2 (restic archive).

Tier 1 is pure-Python and fully offline. Tier 2 wraps the restic binary
(resolved at runtime, never bundled). See ADR-005 and the 2026-07-11
cartridge-backup plan.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# key -> path relative to the cartridge root
_DB_LAYOUT = {
    "photonforge": "photonforge.db",
    "training_weights": "training_weights.db",
    "dt_library": "darktable/library.db",
    "dt_data": "darktable/data.db",
}


@dataclass
class CartridgeLayout:
    root: Path
    dbs: dict[str, Path]


def cartridge_layout(root: Path) -> CartridgeLayout:
    """The DBs that actually exist on this cartridge."""
    root = Path(root)
    dbs = {k: root / rel for k, rel in _DB_LAYOUT.items() if (root / rel).exists()}
    return CartridgeLayout(root=root, dbs=dbs)


def snapshot_databases(root: Path, dest_dir: Path) -> Path:
    """VACUUM INTO every present DB under dest_dir + a MANIFEST.json.

    VACUUM INTO writes a defragmented, self-contained copy while readers stay
    live (a plain file copy of a DB mid-write can be torn). Snapshot filenames
    are basenames, so library.db/data.db land flat next to photonforge.db.
    """
    layout = cartridge_layout(root)
    if not layout.dbs:
        raise FileNotFoundError(f"No PHOTONForge/Darktable DBs found under {root}")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict = {"created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "source_root": str(root), "dbs": {}}
    for key, src in layout.dbs.items():
        out = dest_dir / src.name
        conn = sqlite3.connect(str(src))
        try:
            # Parameters are not allowed in VACUUM INTO; quote the path safely.
            conn.execute(f"VACUUM INTO '{str(out).replace(chr(39), chr(39) * 2)}'")
        finally:
            conn.close()
        manifest["dbs"][key] = {"source": str(src), "snapshot": out.name,
                                "bytes": out.stat().st_size}
    (dest_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("Snapshotted %d DBs into %s", len(layout.dbs), dest_dir)
    return dest_dir
```

- [ ] **Step 4: Run tests, commit**

Run: `pytest tests/test_backup_snapshot.py -v` — Expected: PASS

```bash
git add src/photo_workflow/backup.py tests/test_backup_snapshot.py
git commit -m "feat(backup): cartridge layout + Tier-1 SQLite snapshot core"
```

---

### Task 2: `photo-cartridge snapshot` command + rotation

**Files:**
- Modify: `src/photo_workflow/backup.py` (add `rotate_snapshots`)
- Modify: `src/photo_workflow/cartridge.py` (new `snapshot` subcommand)
- Test: `tests/test_backup_snapshot.py`, `tests/test_cartridge_cli.py`

**Interfaces:**
- Produces:
  - `rotate_snapshots(snapshots_root: Path, keep: int) -> list[Path]` — delete oldest timestamped dirs beyond `keep`; return the deleted paths.
  - CLI: `photo-cartridge snapshot <root> [--dest DIR] [--keep N] [--json]`. Default `--dest` is `<root>/.photon-snapshots`; default `--keep 7`. Each run creates `<dest>/<UTC timestamp>/`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_backup_snapshot.py (append)
from photo_workflow.backup import rotate_snapshots


def test_rotate_keeps_newest_n(tmp_path):
    snaproot = tmp_path / ".photon-snapshots"; snaproot.mkdir()
    # names sort lexicographically == chronologically (UTC ISO-ish, colon-free)
    for name in ["2026-07-01T00-00-00", "2026-07-02T00-00-00",
                 "2026-07-03T00-00-00", "2026-07-04T00-00-00"]:
        (snaproot / name).mkdir()
    deleted = rotate_snapshots(snaproot, keep=2)
    remaining = sorted(p.name for p in snaproot.iterdir())
    assert remaining == ["2026-07-03T00-00-00", "2026-07-04T00-00-00"]
    assert len(deleted) == 2
```

```python
# tests/test_cartridge_cli.py
import sqlite3
from pathlib import Path
from click.testing import CliRunner
from photo_workflow.cartridge import main


def _cartridge(tmp_path):
    root = tmp_path / "cart"; root.mkdir()
    c = sqlite3.connect(root / "photonforge.db")
    c.execute("CREATE TABLE t (x)"); c.commit(); c.close()
    return root


def test_snapshot_command_creates_timestamped_dir(tmp_path):
    root = _cartridge(tmp_path)
    result = CliRunner().invoke(main, ["snapshot", str(root), "--keep", "3"])
    assert result.exit_code == 0, result.output
    snaps = list((root / ".photon-snapshots").iterdir())
    assert len(snaps) == 1
    assert (snaps[0] / "photonforge.db").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_backup_snapshot.py::test_rotate_keeps_newest_n tests/test_cartridge_cli.py -v`
Expected: FAIL (ImportError, then "no such command 'snapshot'")

- [ ] **Step 3: Implement**

```python
# backup.py (append)
def rotate_snapshots(snapshots_root: Path, keep: int) -> list[Path]:
    """Keep the newest `keep` timestamped snapshot dirs; delete the rest."""
    import shutil
    snapshots_root = Path(snapshots_root)
    if not snapshots_root.exists():
        return []
    dirs = sorted((p for p in snapshots_root.iterdir() if p.is_dir()), key=lambda p: p.name)
    to_delete = dirs[:-keep] if keep > 0 else []
    for d in to_delete:
        shutil.rmtree(d, ignore_errors=True)
    return to_delete


def snapshot_timestamp() -> str:
    """Colon-free UTC stamp so it sorts chronologically and is filename-safe."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
```

```python
# cartridge.py (add subcommand to the existing `main` group)
@main.command("snapshot")
@click.argument("root", type=click.Path(exists=True, path_type=Path))
@click.option("--dest", type=click.Path(path_type=Path), default=None,
              help="Snapshot dir (default: <root>/.photon-snapshots)")
@click.option("--keep", default=7, show_default=True, help="Rotating snapshots to retain")
@click.option("--json", "as_json", is_flag=True)
def snapshot_cmd(root, dest, keep, as_json):
    """Tier 1: VACUUM-copy the cartridge DBs into a rotating local snapshot."""
    import json as _json
    from .backup import snapshot_databases, rotate_snapshots, snapshot_timestamp
    snaproot = Path(dest) if dest else root / ".photon-snapshots"
    target = snaproot / snapshot_timestamp()
    snapshot_databases(root, target)
    deleted = rotate_snapshots(snaproot, keep)
    if as_json:
        click.echo(_json.dumps({"step": "snapshot", "status": "ok",
                                "path": str(target), "pruned": len(deleted)}))
    else:
        click.echo(f"Snapshot written to {target} (pruned {len(deleted)} old).")
```

- [ ] **Step 4: Run tests, full suite, commit**

Run: `pytest tests/test_backup_snapshot.py tests/test_cartridge_cli.py -v && pytest -m "not slow" -q`
Expected: PASS

```bash
git add src/photo_workflow/backup.py src/photo_workflow/cartridge.py tests/test_backup_snapshot.py tests/test_cartridge_cli.py
git commit -m "feat(backup): photo-cartridge snapshot with rotation (Tier 1)"
```

---

### Task 3: restic command builders (pure, no binary needed)

**Files:**
- Modify: `src/photo_workflow/backup.py` (restic arg/env builders + repo helpers)
- Test: `tests/test_backup_restic.py`

**Interfaces:**
- Produces:
  - `resolve_restic(configured: str | None = None) -> str` — configured path, else `shutil.which("restic")`, else raise `RuntimeError` with an install hint.
  - `restic_env(password_file: Path | None) -> dict[str, str]` — os.environ copy plus `RESTIC_PASSWORD_FILE` when given.
  - `write_exclude_file(dest: Path) -> Path` — the standard exclude patterns.
  - `build_backup_args(repo: str, root: Path, exclude_file: Path, compression: str = "auto") -> list[str]`
  - `build_init_args(repo: str) -> list[str]` (`init --repository-version 2`)
  - `build_restore_args(repo: str, target: Path, snapshot: str = "latest") -> list[str]`
  - `build_forget_args(repo: str, keep_last: int) -> list[str]` (`forget --keep-last N --prune`)
  - `normalize_repo(repo: str, rclone_remote: str | None) -> str` — prefix `rclone:<remote>:` when a remote is named and the repo isn't already a URL.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_backup_restic.py
from pathlib import Path
import pytest
from photo_workflow import backup


def test_exclude_file_has_regenerable_patterns(tmp_path):
    ex = backup.write_exclude_file(tmp_path / "ex.txt")
    text = ex.read_text()
    for pat in ("models/", ".photon-snapshots/", "*__preview.jpg", "*.mcp.json"):
        assert pat in text


def test_build_backup_args_local(tmp_path):
    args = backup.build_backup_args("/mnt/repo", tmp_path, tmp_path / "ex.txt")
    assert args[:2] == ["-r", "/mnt/repo"]
    assert "backup" in args
    assert str(tmp_path) in args
    assert "--compression" in args and "auto" in args
    assert "--exclude-file" in args


def test_normalize_repo_rclone_bridge():
    assert backup.normalize_repo("mydrive:photon", "gdrive") == "rclone:gdrive:mydrive:photon"
    # already a restic URL / local path: unchanged
    assert backup.normalize_repo("/mnt/repo", None) == "/mnt/repo"
    assert backup.normalize_repo("s3:s3.amazonaws.com/bucket", None) == "s3:s3.amazonaws.com/bucket"


def test_resolve_restic_missing(monkeypatch):
    monkeypatch.setattr(backup.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="restic"):
        backup.resolve_restic(None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_backup_restic.py -v`
Expected: FAIL (AttributeError on the new functions)

- [ ] **Step 3: Implement**

```python
# backup.py (append)
import os
import shutil

_EXCLUDE_PATTERNS = [
    "models/", ".photon-snapshots/", "*__preview.jpg", "*.mcp.json", "*.tmp",
]


def resolve_restic(configured: str | None = None) -> str:
    if configured:
        return configured
    found = shutil.which("restic")
    if not found:
        raise RuntimeError(
            "restic not found. Install it (https://restic.net) or set the "
            "restic path in the plugin's Lua options.")
    return found


def restic_env(password_file: Path | None) -> dict[str, str]:
    env = dict(os.environ)
    if password_file:
        env["RESTIC_PASSWORD_FILE"] = str(password_file)
    return env


def write_exclude_file(dest: Path) -> Path:
    dest = Path(dest)
    dest.write_text("\n".join(_EXCLUDE_PATTERNS) + "\n", encoding="utf-8")
    return dest


def normalize_repo(repo: str, rclone_remote: str | None) -> str:
    """Prefix rclone:<remote>: when a consumer-cloud remote is named."""
    if rclone_remote and not repo.startswith(("rclone:", "s3:", "b2:", "sftp:",
                                              "azure:", "gs:", "rest:")):
        return f"rclone:{rclone_remote}:{repo}"
    return repo


def build_init_args(repo: str) -> list[str]:
    return ["-r", repo, "init", "--repository-version", "2"]


def build_backup_args(repo: str, root: Path, exclude_file: Path,
                      compression: str = "auto") -> list[str]:
    return ["-r", repo, "backup", str(root),
            "--exclude-file", str(exclude_file),
            "--compression", compression]


def build_restore_args(repo: str, target: Path, snapshot: str = "latest") -> list[str]:
    return ["-r", repo, "restore", snapshot, "--target", str(target)]


def build_forget_args(repo: str, keep_last: int) -> list[str]:
    return ["-r", repo, "forget", "--keep-last", str(keep_last), "--prune"]
```

- [ ] **Step 4: Run tests, commit**

Run: `pytest tests/test_backup_restic.py -v` — Expected: PASS

```bash
git add src/photo_workflow/backup.py tests/test_backup_restic.py
git commit -m "feat(backup): restic command/env builders + rclone repo normalization"
```

---

### Task 4: archive / restore / verify / forget commands + round-trip test

**Files:**
- Modify: `src/photo_workflow/backup.py` (`run_restic`, `repo_exists`, high-level `archive`/`restore`/`verify`/`forget`)
- Modify: `src/photo_workflow/cartridge.py` (four subcommands)
- Test: `tests/test_backup_restic.py` (round-trip, gated on restic present)

**Interfaces:**
- Consumes: Task 3 builders.
- Produces:
  - `run_restic(restic: str, args: list[str], env: dict, echo=print) -> int` — stream output, return exit code.
  - `repo_exists(restic: str, repo: str, env: dict) -> bool` — `restic -r REPO cat config` exit 0.
  - `archive(root, repo, *, password_file=None, restic_path=None, rclone_remote=None, init=False, echo=print) -> int`
  - `restore(repo, target, *, snapshot="latest", password_file=None, restic_path=None, rclone_remote=None, echo=print) -> int`
  - `verify(...)` → `restic check`; `forget(..., keep_last)` → prune.
  - CLI: `photo-cartridge archive <root> -r REPO [--password-file P] [--restic-path X] [--rclone-remote NAME] [--init] [--keep-last N]`; `restore -r REPO --to <root> [--snapshot ID] ...`; `verify -r REPO ...`; `forget -r REPO --keep-last N ...`.

- [ ] **Step 1: Write the failing round-trip test**

```python
# tests/test_backup_restic.py (append)
import shutil as _shutil
import subprocess
import sqlite3
from pathlib import Path
import pytest
from photo_workflow import backup

restic_missing = _shutil.which("restic") is None


@pytest.mark.skipif(restic_missing, reason="restic binary not installed")
def test_archive_restore_round_trip(tmp_path):
    # cartridge with a DB, a photo, and an EXCLUDED models/ blob
    cart = tmp_path / "cart"; (cart / "photos").mkdir(parents=True)
    (cart / "models").mkdir()
    c = sqlite3.connect(cart / "photonforge.db")
    c.execute("CREATE TABLE t (x)"); c.execute("INSERT INTO t VALUES (42)")
    c.commit(); c.close()
    (cart / "photos" / "IMG_1.ARW").write_bytes(b"rawdata" * 1000)
    (cart / "models" / "big.onnx").write_bytes(b"0" * 5000)

    repo = tmp_path / "repo"
    pw = tmp_path / "pw.txt"; pw.write_text("test-password")

    rc = backup.archive(cart, str(repo), password_file=pw, init=True)
    assert rc == 0

    dest = tmp_path / "restored"
    rc = backup.restore(str(repo), dest, password_file=pw)
    assert rc == 0

    # restic restores under the absolute source path inside --target
    restored_db = dest / str(cart).lstrip("/\\").replace(":", "") / "photonforge.db"
    # Path reconstruction differs per-OS; find the DB robustly instead:
    found = list(dest.rglob("photonforge.db"))
    assert found, "photonforge.db not restored"
    conn = sqlite3.connect(found[0])
    assert conn.execute("SELECT x FROM t").fetchone()[0] == 42
    conn.close()
    # models/ was excluded
    assert not list(dest.rglob("big.onnx"))
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_backup_restic.py::test_archive_restore_round_trip -v`
Expected: FAIL (AttributeError `archive`) — or SKIP if restic absent. If skipped locally, the CI image must install restic; add `restic` to the CI backup job (note in Task 7).

- [ ] **Step 3: Implement**

```python
# backup.py (append)
import subprocess


def run_restic(restic: str, args: list[str], env: dict, echo=print) -> int:
    proc = subprocess.Popen([restic, *args], env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    assert proc.stdout is not None
    for line in proc.stdout:
        echo(line.rstrip())
    return proc.wait()


def repo_exists(restic: str, repo: str, env: dict) -> bool:
    return subprocess.run([restic, "-r", repo, "cat", "config"], env=env,
                          capture_output=True, text=True).returncode == 0


def archive(root, repo, *, password_file=None, restic_path=None,
            rclone_remote=None, init=False, keep_last=None, echo=print) -> int:
    restic = resolve_restic(restic_path)
    repo = normalize_repo(repo, rclone_remote)
    env = restic_env(password_file)
    if init and not repo_exists(restic, repo, env):
        rc = run_restic(restic, build_init_args(repo), env, echo)
        if rc != 0:
            return rc
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        ex = write_exclude_file(Path(td) / "exclude.txt")
        rc = run_restic(restic, build_backup_args(repo, Path(root), ex), env, echo)
    if rc == 0 and keep_last:
        rc = run_restic(restic, build_forget_args(repo, keep_last), env, echo)
    return rc


def restore(repo, target, *, snapshot="latest", password_file=None,
            restic_path=None, rclone_remote=None, echo=print) -> int:
    restic = resolve_restic(restic_path)
    repo = normalize_repo(repo, rclone_remote)
    Path(target).mkdir(parents=True, exist_ok=True)
    return run_restic(restic, build_restore_args(repo, Path(target), snapshot),
                      restic_env(password_file), echo)


def verify(repo, *, password_file=None, restic_path=None, rclone_remote=None, echo=print) -> int:
    restic = resolve_restic(restic_path)
    return run_restic(restic, ["-r", normalize_repo(repo, rclone_remote), "check"],
                      restic_env(password_file), echo)


def forget(repo, keep_last, *, password_file=None, restic_path=None,
           rclone_remote=None, echo=print) -> int:
    restic = resolve_restic(restic_path)
    return run_restic(restic, build_forget_args(normalize_repo(repo, rclone_remote), keep_last),
                      restic_env(password_file), echo)
```

```python
# cartridge.py — four subcommands. Shared options factored into a decorator.
def _repo_opts(f):
    f = click.option("--password-file", type=click.Path(path_type=Path), default=None)(f)
    f = click.option("--restic-path", default=None)(f)
    f = click.option("--rclone-remote", default=None)(f)
    return f


@main.command("archive")
@click.argument("root", type=click.Path(exists=True, path_type=Path))
@click.option("-r", "--repo", required=True)
@click.option("--init", is_flag=True, help="Create the repo if it does not exist")
@click.option("--keep-last", default=None, type=int, help="Prune to N snapshots after backup")
@_repo_opts
def archive_cmd(root, repo, init, keep_last, password_file, restic_path, rclone_remote):
    """Tier 2: dedup+compress the whole cartridge to a restic repo (local or cloud)."""
    from . import backup
    rc = backup.archive(root, repo, password_file=password_file, restic_path=restic_path,
                        rclone_remote=rclone_remote, init=init, keep_last=keep_last,
                        echo=click.echo)
    raise SystemExit(rc)


@main.command("restore")
@click.option("-r", "--repo", required=True)
@click.option("--to", "target", required=True, type=click.Path(path_type=Path))
@click.option("--snapshot", default="latest")
@_repo_opts
def restore_cmd(repo, target, snapshot, password_file, restic_path, rclone_remote):
    """Restore a cartridge archive into --to (DB + photos)."""
    from . import backup
    raise SystemExit(backup.restore(repo, target, snapshot=snapshot,
                     password_file=password_file, restic_path=restic_path,
                     rclone_remote=rclone_remote, echo=click.echo))


@main.command("verify")
@click.option("-r", "--repo", required=True)
@_repo_opts
def verify_cmd(repo, password_file, restic_path, rclone_remote):
    """Check repository integrity (restic check)."""
    from . import backup
    raise SystemExit(backup.verify(repo, password_file=password_file,
                     restic_path=restic_path, rclone_remote=rclone_remote, echo=click.echo))


@main.command("forget")
@click.option("-r", "--repo", required=True)
@click.option("--keep-last", required=True, type=int)
@_repo_opts
def forget_cmd(repo, keep_last, password_file, restic_path, rclone_remote):
    """Prune old snapshots, keeping the newest N."""
    from . import backup
    raise SystemExit(backup.forget(repo, keep_last, password_file=password_file,
                     restic_path=restic_path, rclone_remote=rclone_remote, echo=click.echo))
```

- [ ] **Step 4: Run tests (with restic installed locally), full suite, commit**

Run: `pytest tests/test_backup_restic.py -v && pytest -m "not slow" -q`
Expected: PASS (round-trip PASS if restic present; SKIP otherwise)

```bash
git add src/photo_workflow/backup.py src/photo_workflow/cartridge.py tests/test_backup_restic.py
git commit -m "feat(backup): archive/restore/verify/forget via restic + round-trip test"
```

---

### Task 5: Lua per-command gating + panel Snapshot/Verify wiring

**Files:**
- Modify: `lua/photonforge/runner.lua` (replace `CARTRIDGE_CMDS_IMPLEMENTED` with a per-command table; add `launch_snapshot`, `launch_verify`; fix archive/restore inner commands to the real CLI; add `restic_path`/`rclone_remote`/`snapshot_keep` reads)
- Modify: `lua/photonforge/panel.lua` (Cartridge strip: add "Snapshot" + "Verify" buttons)

**Interfaces:**
- Consumes: the CLI from Tasks 2 and 4. The archive/restore commands' flag shapes changed slightly (`--repo` vs `-r`, `--to`, `--restic-path`, `--rclone-remote`) — the runner strings must match exactly.

- [ ] **Step 1: Replace the single flag with per-command gating**

In `runner.lua`, delete `CARTRIDGE_CMDS_IMPLEMENTED` and `cartridge_cmd_unavailable`'s single-boolean form; replace with:

```lua
-- Which photo-cartridge subcommands are implemented. provision is still stubbed.
local CARTRIDGE_IMPLEMENTED = {
  snapshot = true, archive = true, restore = true, verify = true,
  provision = false,
}

local function cartridge_cmd_unavailable(name, log_fn)
  if CARTRIDGE_IMPLEMENTED[name] then return false end
  log_fn(string.format("[%s] photo-cartridge %s is not implemented yet.", name, name))
  dt.print("PHOTONForge: cartridge " .. name .. " is not available yet")
  return true
end
```

- [ ] **Step 2: Fix archive/restore inner commands + add snapshot/verify**

Update `backup_flags()` to also pass restic path and rclone remote, and correct the archive/restore command strings to the new CLI:

```lua
local function backup_flags()
  local repo = config.read("backup_repo")
  if repo == "" then return nil end
  local f = " --repo " .. shell_quote(repo)
  local pw = config.read("backup_pwfile")
  if pw ~= "" then f = f .. " --password-file " .. shell_quote(pw) end
  local rp = config.read("restic_path")
  if rp ~= "" then f = f .. " --restic-path " .. shell_quote(rp) end
  local remote = config.read("rclone_remote")
  if remote ~= "" then f = f .. " --rclone-remote " .. shell_quote(remote) end
  return f
end

function M.launch_snapshot(log_fn)
  if cartridge_cmd_unavailable("snapshot", log_fn) then return end
  local root = get_drive_root(config.read("dest_path"))
  local keep = config.read("snapshot_keep")
  local keepflag = (keep ~= "" and (" --keep " .. tostring(keep))) or ""
  local inner = "photo-cartridge snapshot " .. shell_quote(root) .. keepflag
  log_fn(string.format("[%s] Snapshotting catalog DBs (local, offline)...", os.date("%H:%M:%S")))
  launch_terminal(inner, false)
end

function M.launch_verify(log_fn)
  if cartridge_cmd_unavailable("verify", log_fn) then return end
  local flags = backup_flags()
  if not flags then log_fn("[verify] Set 'Backup repo' first.") return end
  launch_terminal("photo-cartridge verify" .. flags, false)
end
```

Update `launch_archive` inner to: `"photo-cartridge archive " .. shell_quote(drive) .. flags .. " --init"` (note `flags` now supplies `--repo`). Update `launch_restore` inner to: `"photo-cartridge restore" .. flags .. " --to " .. shell_quote(drive)` and set `elevated=false` (restore writes to the mounted cartridge; it does not need elevation — only provision does).

- [ ] **Step 3: Panel buttons**

In `panel.lua`'s cartridge strip (the `provision_btn`/`archive_btn`/`restore_btn` row, ~line 627–678), add:

```lua
local snapshot_btn = dt.new_widget("button") {
  label = "\u{1F4F8} Snapshot",
  tooltip = "Fast local snapshot of the catalog DBs (offline, no repo needed). "
         .. "Rotating; keeps the last few.",
  clicked_callback = function()
    local ok, err = pcall(function() save_entries(); runner.launch_snapshot(append_log) end)
    if not ok then append_log("[ERROR] snapshot: " .. tostring(err)) end
  end,
}
set_name(snapshot_btn, "pf_cartridge_btn")

local verify_btn = dt.new_widget("button") {
  label = "\u{2714} Verify",
  tooltip = "Check the backup repository's integrity (restic check).",
  clicked_callback = function()
    local ok, err = pcall(function() save_entries(); runner.launch_verify(append_log) end)
    if not ok then append_log("[ERROR] verify: " .. tostring(err)) end
  end,
}
set_name(verify_btn, "pf_cartridge_btn")
```

Add both to the cartridge strip's horizontal box and to `cartridge_btns` (so they disable mid-run). Snapshot is safe to leave enabled during a run if desired, but keep it consistent and disable with the rest.

- [ ] **Step 4: Manual verification**

Dev panel: confirm the Provision button now says "not implemented" while Snapshot/Archive/Restore/Verify resolve real commands ("Show resolved command" if exposed, or run them against a test cartridge). Run Snapshot → confirm `.photon-snapshots/<ts>/` appears with the DBs. Run Archive to a local `--repo` folder, then Restore `--to` a scratch dir.

- [ ] **Step 5: Commit**

```bash
git add lua/photonforge/runner.lua lua/photonforge/panel.lua
git commit -m "feat(panel): Snapshot/Verify buttons; per-command cartridge gating"
```

---

### Task 6: ADR + docs + security-posture close-out

**Files:**
- Create: `dev-docs/architecture/adr/ADR-005-cartridge-backup-restic.md`
- Modify: `dev-docs/architecture/data-security-posture.md` (flip the "No backup of the catalog" row)
- Create: `dev-docs/backup-and-restore-guide.md` (runbook)
- Modify: `dev-docs/getting-started.md` (link the guide)

**Interfaces:** documentation only — closes the issue #131 acceptance items.

- [ ] **Step 1: Write ADR-005**

Record, following the format of `dev-docs/architecture/adr/ADR-004-*.md`:
- **Context:** issue #131 gap; the payload is mostly incompressible RAW so **dedup across snapshots** is the primary lever, compression secondary; cross-platform (Windows panel + Linux runtime); the existing wiring already assumed restic.
- **Decision:** two tiers — Tier 1 `VACUUM INTO` local snapshots (offline, closes the DR gap even with no repo), Tier 2 restic archive (dedup + zstd, encrypted, local or cloud via rclone).
- **Alternatives considered:** Kopia (better UX/web UI, but would require reworking the restic-shaped prefs/flags — rejected for churn), Borg (no native cloud, no Windows — rejected), plain tar+zstd (no dedup — rejected for repeated snapshots), rclone-sync-only (no versioning/dedup — rejected).
- **Consequences:** requires an external restic binary (resolved at runtime, install step in the guide); `models/` excluded so restores need a re-provision of models (documented); NFR-2.1 unaffected (maintenance-time only).

- [ ] **Step 2: Update data-security-posture.md**

Change the "No backup of the catalog" row's *Where it's handled* from **Open — no automated backup today; tracked in issue #131** to reference the two-tier feature: Tier-1 local snapshots (`photo-cartridge snapshot`) + Tier-2 restic archive (`photo-cartridge archive`), see ADR-005 and `dev-docs/backup-and-restore-guide.md`.

- [ ] **Step 3: Write the runbook** (`backup-and-restore-guide.md`)

Exact commands for: installing restic (+ optional rclone and `rclone config` for a Google Drive/OneDrive remote); a **local external drive** archive (the primary supported target) — `photo-cartridge archive E:\ --repo F:\photon-repo --password-file ... --init`; scheduling/regular cadence; the restore drill (`restore --to` a fresh cartridge, then re-provision `models/` since it's excluded); `verify` and `forget` cadence; and the rclone cloud variant as a second section. Include the "restore round-trips" proof from the Task 4 test as the acceptance the user can re-run.

- [ ] **Step 4: Commit**

```bash
git add dev-docs/architecture/adr/ADR-005-cartridge-backup-restic.md dev-docs/architecture/data-security-posture.md dev-docs/backup-and-restore-guide.md dev-docs/getting-started.md
git commit -m "docs(backup): ADR-005, close issue #131 posture row, backup/restore runbook"
```

- [ ] **Step 5: Close issue #131**

Reference the PR in the issue; the three acceptance boxes (ADR, restore round-trip test, posture row) are now satisfied.

---

## Self-Review Notes

- **Scope vs issue #131:** the issue asked only about the catalog DB; this plan delivers that (Tier 1) *and* the whole-cartridge archive the panel buttons promise (Tier 2). Both, per the 2026-07-11 decision.
- **Primary target is the local external/second drive** — every Task-4 test and the runbook's first section use a local repo path; cloud (rclone) and S3 are documented as variants, not the tested-first path.
- **restic is an external dependency.** Round-trip tests SKIP when it's absent; CI's backup job must `apt-get install restic` (or download the binary) for the round-trip to actually run — call this out in the CI change if the backup tests are added to `tests.yml`.
- **Encryption split is deliberate:** Tier-1 local snapshots unencrypted (matches the accepted local posture), Tier-2 always encrypted (data may leave the device). Do not "simplify" by encrypting Tier 1 — it would need a key present at safe-eject time, defeating the offline/instant property.
- **`provision` stays stubbed** — the per-command gate (Task 5) means flipping on archive/restore/verify/snapshot does not expose the still-unimplemented provision button. Implementing `provision` (volume-label set, elevated) is a separate small follow-up.
- **Restore path reconstruction** differs across OSes (restic restores under the absolute source path inside `--target`); the round-trip test locates the DB with `rglob` rather than assuming the reconstructed path, so it passes on both Windows and Linux.
