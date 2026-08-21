# PHOTONForge — Portable Drive Setup

How to build a **self-contained PHOTON cartridge**: a drive that runs the whole
workflow — Darktable, the `photo-workflow` CLI, and the ONNX models — on any
Windows or Linux machine with **nothing installed on the host**.

Everything network-dependent happens while *building* the drive. Once built,
the drive runs 100 % offline (NFR-2.1): nothing in `runtime/`, the launchers,
or the Lua plugin ever touches the network.

## What ends up on the drive

```
<DRIVE>/
├── !README.txt                   # points at the two launchers below
├── !START_PHOTONForge.bat        # Windows launcher (double-click)
├── !START_PHOTONForge.sh         # Linux launcher (run, or double-click)
├── PHOTONForge.ps1                # invoked by the .bat; not meant to be run directly
├── autorun.inf / PHOTONForge.ico # Windows Explorer icon + label (no execution — see below)
├── apps/darktable-win/           # bundled Windows Darktable
├── apps/darktable-linux/         # bundled Linux Darktable (pre-extracted AppImage)
├── runtime/{win,linux}/          # frozen photo-workflow + photo-cartridge
├── models/                       # ONNX models
├── dt-config/                    # Darktable's --configdir, incl. the Lua plugin
├── .photonforge/manifest.lock.json
└── ICELAND/ ...                  # your shoot folders
```

The launchers resolve every path **relative to themselves** (`$PSScriptRoot`,
`%~dp0`, `readlink -f`), and the Lua plugin locates the CLI and models from
Darktable's own `--configdir`. Nothing stores an absolute path, so the drive
letter or mount point can change between machines and nothing needs
reconfiguring.

**Why the `!` prefix.** The launchers and README are named to sort before
everything else a file manager shows — shoot folders, `models/`, `apps/` —
so they stay the first thing visible no matter how much accumulates on the
drive. `make-portable` writes them; there's nothing to configure.

**Why `autorun.inf` doesn't launch anything.** Windows disabled
`autorun.inf`'s `open=`/`shellexecute=` directives for USB drives in
Windows 7+, specifically because that was the main vector for USB-borne
malware — that restriction is still fully in effect on 10/11 today, and
building around it isn't attempted here. `icon=`/`label=` were never part of
that attack surface and still work, so the drive shows a distinct icon and
name in Explorer instead of a generic one. It is a passive visual cue, never
a substitute for double-clicking `!START_PHOTONForge.bat`.

## Prerequisites on the build machine

| | Needed for |
|---|---|
| Python 3.11+ and this repo | everything |
| A provisioned `PHOTON-XXX` cartridge | the target (`photo-cartridge provision`) |
| **innoextract with Inno Setup 6.7 support** | bundling **Windows** Darktable |
| The ability to execute a Linux ELF binary (a **Linux** host, or WSL) | bundling **Linux** Darktable |

**A Linux provisioning host builds the full dual-OS drive in one
`make-portable` run** — verified end-to-end in this repo's tests. innoextract
is a format parser, not an installer executor: it never runs the Windows
`.exe`, it only reads the Inno Setup archive layout, so a Linux-built (or
Linux-packaged) innoextract reads the Windows installer just fine. The only
step that is genuinely host-locked is the **Linux** half, because bundling it
runs the downloaded AppImage itself (`--appimage-extract`) as a subprocess —
that needs something that can execute a Linux ELF binary.

So the asymmetry runs one way:

- **From Linux:** `make-portable --os win --os linux` in a single run.
  This is also the primary target machine (the Yoga 910 runs Ubuntu 24.04),
  so the common case needs nothing special.
- **From Windows only:** you can bundle the **Windows** half (innoextract has
  native Windows builds too, via the same MSYS2 patch series used below), but
  the Linux half needs WSL to run the AppImage extraction step — **untested**
  in this repo. Without WSL, build the Linux half on a separate Linux machine
  and `make-portable --os linux` onto the same cartridge afterward
  (`make-portable` is incremental, not destructive across runs).

### The innoextract version requirement

This one bites, so it gets its own section.

Upstream ships **no portable `.zip`** for Windows Darktable — only an Inno
Setup installer. The current one (Darktable 5.6.0) is built with **Inno Setup
6.7.0**, which uses *setup-loader revision 2*.

**innoextract 1.9 cannot read it.** 1.9 is the newest *release*, and it is what
Debian stable and Ubuntu 24.04 package (`apt install innoextract`). Against a
6.7 installer it exits 2 having written nothing:

```
Warning: Unexpected setup loader revision: 2
Setup loader checksum mismatch!
Could not determine setup data version!
```

`make-portable` turns that into an explicit error rather than leaving you with
an empty `apps/darktable-win/`. To check what you have:

```bash
innoextract --version
# innoextract 1.9
# Extracts installers created by Inno Setup 1.2.10 to 6.0.5     <-- too old
```

The second line must advertise support up to at least **6.7**. If it does not,
build innoextract from upstream master with the MSYS2 patch series applied —
that series is what adds loader-revision-2 and Inno Setup 6.5–7.0 support:

```bash
sudo apt install -y build-essential cmake libboost-all-dev \
                    liblzma-dev zlib1g-dev libbz2-dev

git clone https://github.com/dscharrer/innoextract.git
git clone --filter=blob:none --sparse --depth 1 \
    https://github.com/msys2/MINGW-packages.git
(cd MINGW-packages && git sparse-checkout set mingw-w64-innoextract)

cd innoextract
# The patch series is cut against the commit MINGW-packages pins; check
# _commit in MINGW-packages/mingw-w64-innoextract/PKGBUILD and match it.
git checkout "$(grep -oP '(?<=^_commit=).*' ../MINGW-packages/mingw-w64-innoextract/PKGBUILD)"
for p in ../MINGW-packages/mingw-w64-innoextract/00*.patch; do git apply "$p"; done

cmake -B build -DCMAKE_BUILD_TYPE=Release && make -C build -j"$(nproc)"
./build/innoextract --version
# Extracts installers created by Inno Setup 1.2.10 to 7.0.2     <-- good
```

Put the resulting binary on `PATH` before running `make-portable`.

## Building the drive

```bash
# 1. Freeze the CLI for this OS (writes runtime/{linux,win}/)
bash scripts/build_portable_cli.sh          # or scripts\build_portable_cli.ps1

# 2. Assemble onto the mounted cartridge
photo-cartridge make-portable /media/alex/PHOTON-001 \
    --os linux \
    --manifest config/portable-manifest.yml \
    --models-src models \
    --cli-src runtime \
    --cache ~/.cache/photonforge-portable
```

Useful flags:

- `--os {win,linux}` — repeatable; defaults to both. Use one at a time when
  the host can only extract one of them.
- `--offline` — cache-only. Errors instead of downloading, for an air-gapped
  rebuild. Populate `--cache` on a connected machine first.
- `--id 001` — verifies the drive's volume label matches before writing.
- Omit `--manifest` to skip the Darktable bundling entirely and just refresh
  the plugin, CLI, models and launchers.

Downloads are verified against the sha256 pinned in
`config/portable-manifest.yml` and aborted on mismatch — there is no
trust-on-first-use. `.photonforge/manifest.lock.json` records what actually
landed (versions, URLs, hashes, git SHA, timestamp).

### Pinning a newer Darktable

The refresh procedure lives in the header comment of
`config/portable-manifest.yml`. The short version: download both artifacts,
compute the checksums **yourself**, confirm the binary relpaths still hold in
the extracted trees, then update the file.

## Caveats

- **exFAT has no exec bit.** The launchers `chmod +x` best-effort and never
  rely on symlinks. On Linux you may need `sh !START_PHOTONForge.sh` rather
  than `./!START_PHOTONForge.sh` depending on the mount options.
- **AppImage and FUSE.** The AppImage is *pre-extracted* to
  `squashfs-root/` at build time so launching needs no FUSE on the host.
  `!START_PHOTONForge.sh` falls back to `--appimage-extract-and-run` if that
  directory is missing, which works without FUSE but re-extracts on every
  launch.
- **Leave the plugin's path preferences blank.** `make-portable` writes a
  baseline `darktablerc` with `cli_path`, `cartridge_path` and `models_path`
  empty on purpose — that is what activates the plugin's self-location. Do not
  fill them in; Darktable rewrites `darktablerc` on exit, so a baked-in
  absolute path is both wrong on the next machine and liable to be clobbered.
- **KPM-1.4 on exFAT is not yet re-validated.** The 50-cycle safe-eject soak
  was validated on ext4. Re-run it on exFAT before trusting a cartridge.

## Verification

After building, confirm on the build machine:

```bash
DRIVE=/media/alex/PHOTON-001
"$DRIVE/apps/darktable-linux/squashfs-root/AppRun" --version   # expect: Lua ENABLED
ls "$DRIVE/dt-config/lua/photonforge/"                         # 7 .lua + .css
cat "$DRIVE/dt-config/darktablerc"                             # paths must be BLANK
cat "$DRIVE/.photonforge/manifest.lock.json"
ls "$DRIVE" | sort                                             # !README.txt and the two
                                                                 # !START_ launchers sort first
cat "$DRIVE/autorun.inf"                                        # icon=/label= only, no open=
```

`Lua -> ENABLED` matters: the PHOTONFORGE panel is a Lua plugin, and a
Darktable build without Lua support will start but never show it.

Then the real acceptance test — plug the drive into a machine that has **no**
PHOTONForge install:

1. Run `!START_PHOTONForge.sh` (Linux) or double-click `!START_PHOTONForge.bat`
   (Windows) — the file names are prefixed so they're the first thing you see.
2. Darktable opens with the **PHOTONFORGE** panel in the lighttable view.
3. Enable the `dev_mode` preference and confirm the resolved-command preview
   points at the **current** mount's `runtime/` and `models/`.
4. Run ingest → dedup → score → name → sync-tags on a few fixture photos and
   confirm tags land in the on-drive `dt-config/library.db`.

> **Status:** the Linux path is verified end-to-end — a real dual-OS build was
> assembled from the pinned manifest, and the extracted Darktable 5.6.0 runs
> with Lua 9.7.0. The **Windows** half has been assembled and its layout
> verified, but launching it on a real Windows host is **not yet verified**;
> `scripts/build_portable_cli.ps1` has likewise never been executed on
> Windows. Treat step 1 on Windows as the open item.
