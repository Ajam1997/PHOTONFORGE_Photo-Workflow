# PHOTONForge — Linux Install & Provisioning Guide (Yoga 910)

Covers a from-scratch install on the target machine (UN-003): Lenovo Yoga
910-13IKB Glass — i7-7500U (AVX2), 8 GB RAM — running **Ubuntu 24.04** (Debian
stable also works; the container OS matches). The Windows dev-box counterpart
is `dev-docs/dev-machine-setup.md`.

Everything network-dependent happens in **provisioning only**. After step 3
the pipeline runs 100 % offline (NFR-2.1) — never call the provisioning
scripts from pipeline code or cron.

## 1. OS packages

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv git zenity udisks2 sqlite3 darktable
```

Notes:
- `zenity` is used for operator dialogs (NFR-2.4 path) and the plugin's folder
  browser on Linux.
- `udisks2` is normally preinstalled on desktop Ubuntu; cartridge detection
  relies on its auto-mount plus polling (see
  `dev-docs/architecture/adr/ADR-003-udisks2-polling-over-udev.md`).
- Darktable 5.x from the distro/OBS repo is fine; the bridge understands the
  split `library.db`/`data.db` layout. (A containerized Darktable is also
  available — `deploy/README-darktable.md` — but the native install is the
  R1 path.)

## 2. Python environment

```bash
git clone https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow.git
cd PHOTONFORGE_Photo-Workflow
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -m "not slow"     # expect: all green
```

The editable install provides two console scripts: `photo-workflow` (staged
pipeline CLI) and `photo-cartridge` (cartridge init). The Darktable plugin
shells out to `photo-workflow`, so the venv's `bin` must be on the PATH of
the environment Darktable is launched from (simplest: launch Darktable from a
shell with the venv activated, or symlink the entry points into `~/.local/bin`).

## 3. Model provisioning (one-time, online)

Both scripts download from the internet, quantize to INT8 ONNX, and write
under `models/`. Re-runs are idempotent; `--force` re-downloads.

```bash
# Extra packages used only at provisioning time:
pip install huggingface_hub transformers torch

# Florence-2-base-ft (semantic naming) -> models/florence2_int8/
# + the legacy genre-prototype matrix if the CLIP text encoder is present
bash scripts/provision_models.sh

# Scoring models: RMBG-1.4, YuNet, YOLOv8n, MobileCLIP-S2
python scripts/provision_scoring_models.py
```

The CLIP aesthetic head (`clip_aesthetic_head/aesthetic_mlp.onnx`) is trained
separately by `scripts/train_aesthetic_head.py`; if it is missing or
degenerate the pipeline detects that, disables it, and renormalizes the
scoring weights — scoring still works.

**Offline check (NFR-2.1):** after provisioning, the pipeline makes no
network calls. You can verify by scoring a folder with networking disabled.

## 4. Privileged disk operations (one-time)

Cartridge provisioning (partition/format/label) needs root for a fixed set of
tools. Install the scoped sudoers rule once:

```bash
sudo bash scripts/install_polkit.sh
# validates with visudo; test: sudo -n mkfs.ext4 --help
```

This grants passwordless sudo for `parted`, `wipefs`, `mkfs.ext4`, `udevadm`,
and `umount` only. The Darktable plugin's Provision/Restore buttons elevate
via `pkexec` in a visible terminal.

## 5. Darktable Lua plugin

There is no Linux deploy script yet (the Windows one is
`scripts/deploy_lua.ps1`); the equivalent by hand:

```bash
DT_CONFIG=~/.config/darktable          # or wherever --configdir points
mkdir -p "$DT_CONFIG/lua/photonforge"
cp lua/photonforge/*.lua lua/photonforge/photonforge.css "$DT_CONFIG/lua/photonforge/"
grep -qxF 'require "photonforge/main"' "$DT_CONFIG/luarc" 2>/dev/null \
  || echo 'require "photonforge/main"' >> "$DT_CONFIG/luarc"
```

Restart Darktable. The **PHOTONFORGE** panel appears in the lighttable view.
Re-copy the files after every plugin change. Optional polish: paste
`lua/photonforge/photonforge.css` into Preferences → user.css (the panel is
fully functional without it).

Plugin preferences (Preferences → Lua options) worth setting up front:
- **Models dir** — absolute path to the repo's `models/` directory (required
  for a non-editable install; recommended always). On a **portable cartridge**
  leave it blank: the plugin locates `<drive>/models` from Darktable's own
  `--configdir`, so nothing has to be reconfigured when the drive letter or
  mount point changes. The same applies to the two CLI paths.
- **Cartridge ID** (e.g. `003`) — used by Provision.
- **Backup dest** (also in the panel's Configuration section, with a folder
  browser) — a second drive to hold verified cartridge mirrors,
  e.g. `/media/alex/BACKUP`. Required by the Backup and Verify buttons.
- **Catalog snapshots to keep** (default 7) and **Cartridge mirrors to keep**
  (default 10) — retention for the two backup tiers.
- **Backup repo / password file** — restic target. The restic tier is **not
  implemented yet**; these prefs do nothing today.
- SD card path, destination path, TZ offset, run mode, file type — also
  editable in the panel itself.

### Backing up a cartridge

The panel's CARTRIDGE strip has two rows. The first is implemented:

| Button | What it does | Needs |
|---|---|---|
| **Snapshot** | Copies just the catalog databases (scores, names, stage state) into a rotating `.photon-snapshots/` folder **on the cartridge itself**. Seconds, offline, no second drive. Does *not* copy photos. | nothing |
| **Backup** | Full verified mirror of the cartridge — databases *and* photos — to the Backup destination, checksummed as it copies. Run this before migrating or reformatting a drive. | Backup destination |
| **Verify** | Re-checksums the newest mirror of this cartridge against its manifest. | Backup destination |

The second row (**Provision / Archive / Restore**) is not implemented yet and
each button says so when pressed rather than opening a terminal that fails.

Snapshot protects the expensive-to-recompute work but not the photos; Backup
protects everything. They complement each other — a snapshot before each eject,
a full backup on a cadence you choose.

Two things worth knowing:

- **Repeat mirrors reuse unchanged files via hardlinks where the filesystem
  supports it.** exFAT and FAT32 do not, so on those destinations every mirror
  is a full copy. The manifest records `"hardlinks": false` when that happens.
- **Because unchanged files are shared between mirrors, one corrupted file
  affects every mirror holding it.** N mirrors is not N independent copies —
  that is what **Verify** is for. Run it periodically.

To restore, use the CLI (there is deliberately no restore button — it needs an
explicit snapshot path, and guessing at a destructive operation is worse than
typing it):

```bash
photo-cartridge verify-backup /media/alex/BACKUP/PHOTON-001/<timestamp>
photo-cartridge restore-backup /media/alex/BACKUP/PHOTON-001/<timestamp> \
    --to /media/alex/PHOTON-001
```

Optional: set `PHOTONFORGE_SNAPSHOT_ON_EJECT=1` to make `scripts/safe_eject.sh`
take a catalog snapshot before unmounting. A snapshot failure only warns — it
never blocks the eject.

## 6. Cartridge expectations

A PHOTON cartridge is an external SSD with a **GPT + single ext4 partition
labeled `PHOTON-XXX`** (e.g. `PHOTON-001`). Provisioning
(`photo-cartridge` / `src/photo_workflow/provision.py`, or the plugin's
Provision button) creates that layout; udisks2 then auto-mounts it (typically
`/media/$USER/PHOTON-001`).

Data layout — the shoot folder's **parent (the cartridge root)** holds the
state, so the library travels with the drive (NFR-2.3):

```
/media/alex/PHOTON-001/
├── photonforge.db            # pipeline state DB (photos table per folder)
├── training_weights.db       # calibrated prototypes/adapter/weights (optional)
├── genre_labels.jsonl        # training corpus (grows via Collect Corrections)
├── secondary_feedback.jsonl  # type-tag feedback log
└── ICELAND/                  # a shoot folder = the plugin's "Destination"
    ├── 001_00123.ARW ...
```

The plugin derives the DB path from the Destination automatically and passes
`--training-db` whenever `training_weights.db` exists on the cartridge.

## 7. SD ingest flow (Release-1 happy path)

1. Connect the PHOTON cartridge; insert the SD card (both auto-mount).
2. Darktable → PHOTONFORGE panel: set **SD card path** and **Destination**
   (a folder on the cartridge, e.g. `/media/alex/PHOTON-001/ICELAND`).
3. **Run** with the desired steps: ingest (SD→SSD copy with cartridge-prefix
   renaming) → import (into the DT library) → dedup → score → name.
4. Review in Darktable: stars, color labels (blue = 5★, green = 4★,
   yellow = 1★, red = duplicate, reject flag = technically broken; purple is
   yours), `photon|subject|*` / `photon|type|*` tags, captions in the
   description field.
5. Improve the model via the Training tab — see
   `dev-docs/training-loop-guide.md`.
6. Safe eject when done: `bash scripts/safe_eject.sh <mount_point>
   [library.db path]` (flushes the SQLite WAL, syncs, `udisksctl unmount`).

## 8. Verification checklist

- [ ] `python -m pytest -m "not slow"` green in the venv
- [ ] `photo-workflow --help` lists the staged commands (ingest, scan, dedup,
      score, name, status, sync-tags, suggest-training-set, refresh-review,
      training …)
- [ ] `models/florence2_int8/` and the four scoring model dirs contain `.onnx`
      files; `models/genre_prototypes.npy` present
- [ ] `sudo -n parted --version` works without a password prompt
- [ ] Darktable shows the PHOTONFORGE panel in lighttable view, state IDLE
- [ ] Cartridge auto-mounts with a `PHOTON-XXX` label (`lsblk -o LABEL,MOUNTPOINT`)
- [ ] A test Run on a small folder produces stars/tags in Darktable and rows
      in `photonforge.db` (`photo-workflow status --db … --folder …`)
