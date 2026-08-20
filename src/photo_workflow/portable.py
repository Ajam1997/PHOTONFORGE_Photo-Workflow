"""Portable-drive assembly: Task 2 of the portable-drive plan.

Turns an already-provisioned PHOTON cartridge (see `provision.py`) into a
fully self-contained drive: a bundled Darktable, the frozen `photo-workflow`
CLI, ONNX models, the Lua plugin, and drive-relative launchers — nothing
installed on the host. See
`dev-docs/superpowers/plans/2026-07-17-portable-drive-plan.md`.

Runs on the provisioning machine only (`photo-cartridge make-portable`, an
unfrozen entry point). Nothing here may be imported by the pipeline
(NFR-2.1) — like `backup.py`, this is a maintenance-time operation, and the
only network calls in the whole system happen in `download_verified()`.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .backup import sha256_file, tool_version, utcnow

logger = logging.getLogger(__name__)

LUA_FILES = (
    "applicator.lua",
    "config.lua",
    "json.lua",
    "main.lua",
    "panel.lua",
    "runner.lua",
    "tag_manager.lua",
)
CSS_FILE = "photonforge.css"
REQUIRE_LINE = 'require "photonforge/main"'
MANIFEST_LOCK_NAME = "manifest.lock.json"
LOCK_SCHEMA_VERSION = 1

LAUNCHER_TEMPLATES = (
    ("PHOTONForge.ps1.tmpl", "PHOTONForge.ps1"),
    ("PHOTONForge.bat.tmpl", "PHOTONForge.bat"),
    ("PHOTONForge.sh.tmpl", "PHOTONForge.sh"),
)


class DownloadError(RuntimeError):
    """Cache miss under --offline, or a downloaded file that failed sha256."""


# ---------------------------------------------------------------------------
# Manifest (config/portable-manifest.yml — Task 7's deliverable; Task 2 only
# defines and consumes the schema so make-portable isn't blocked on Task 7)
# ---------------------------------------------------------------------------


@dataclass
class DarktableTarget:
    """One OS's pinned Darktable download, from the provisioning manifest."""

    version: str
    url: str
    sha256: str
    archive_type: str  # "zip" | "appimage" | "innosetup"
    binary_relpath: str  # relative to the extracted apps/darktable-<os>/ dir


@dataclass
class PortableManifest:
    win: DarktableTarget | None = None
    linux: DarktableTarget | None = None

    @classmethod
    def load(cls, path: Path) -> PortableManifest:
        import yaml

        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(
            win=_target_from_dict(data["win"]) if data.get("win") else None,
            linux=_target_from_dict(data["linux"]) if data.get("linux") else None,
        )

    def target_for(self, os_name: str) -> DarktableTarget | None:
        return getattr(self, os_name, None)


def _target_from_dict(d: dict) -> DarktableTarget:
    binary_relpath = d.get("exe_relpath") or d.get("apprun_relpath")
    if not binary_relpath:
        raise ValueError("manifest entry needs exe_relpath or apprun_relpath")
    return DarktableTarget(
        version=d["version"],
        url=d["url"],
        sha256=d["sha256"],
        archive_type=d["archive_type"],
        binary_relpath=binary_relpath,
    )


# ---------------------------------------------------------------------------
# Downloader — sha256-verified, no TOFU, --offline is cache-only
# ---------------------------------------------------------------------------


def download_verified(
    url: str,
    sha256: str,
    cache_dir: Path,
    *,
    offline: bool = False,
    fetch: Callable[[str, Path], None] | None = None,
) -> Path:
    """Stream `url` into a content-addressed cache entry, verified by sha256.

    The cache key is the expected hash, not the URL: two URLs for the same
    bytes share one cache entry, and a URL rename doesn't orphan an old one.
    A cache hit still gets re-hashed before being trusted — a previous run
    crashing mid-write must not be mistaken for a good download.

    `fetch(url, dest)` is injectable so tests never touch the network; it
    defaults to a plain streaming urllib fetch. Raises DownloadError on a
    cache miss under --offline, or a sha256 mismatch (no trust-on-first-use:
    a corrupt or tampered download is deleted, never silently accepted).
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / sha256

    if dest.exists():
        if sha256_file(dest) == sha256:
            return dest
        dest.unlink()  # corrupt cache entry from an interrupted prior run

    if offline:
        raise DownloadError(
            f"{sha256} not in cache under {cache_dir} and --offline is set (url={url})"
        )

    (fetch or _urllib_fetch)(url, dest)
    digest = sha256_file(dest)
    if digest != sha256:
        dest.unlink(missing_ok=True)
        raise DownloadError(f"sha256 mismatch for {url}: expected {sha256}, got {digest}")
    return dest


def _urllib_fetch(url: str, dest: Path) -> None:
    import urllib.request

    tmp = dest.with_name(dest.name + ".part")
    # url/sha256 come from the version-controlled manifest and are verified
    # against a pinned hash immediately below — not arbitrary user input.
    with urllib.request.urlopen(url) as resp, open(tmp, "wb") as out:
        shutil.copyfileobj(resp, out)
    tmp.replace(dest)


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


def extract_archive(archive_path: Path, dest_dir: Path, archive_type: str) -> None:
    """Extract a downloaded Darktable archive into dest_dir.

    zip: stdlib zipfile — fully supported everywhere, no external tool.
    appimage: copied in place, best-effort chmod +x, then
      `--appimage-extract` into dest_dir/squashfs-root (Linux only; avoids
      needing FUSE at launch time on an arbitrary host).
    innosetup: dispatched to the external `innoextract` tool — Inno Setup's
      format is not something to hand-roll.
    """
    archive_path, dest_dir = Path(archive_path), Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    if archive_type == "zip":
        import zipfile

        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(dest_dir)
    elif archive_type == "appimage":
        _extract_appimage(archive_path, dest_dir)
    elif archive_type == "innosetup":
        _extract_innosetup(archive_path, dest_dir)
    else:
        raise ValueError(f"Unknown archive_type: {archive_type!r}")


def _extract_appimage(archive_path: Path, dest_dir: Path) -> None:
    target = dest_dir / archive_path.name
    shutil.copy2(archive_path, target)
    try:
        target.chmod(target.stat().st_mode | 0o111)
    except OSError:
        pass  # best-effort exec bit; exFAT has none anyway
    subprocess.run(
        [str(target), "--appimage-extract"],
        cwd=dest_dir, check=True, capture_output=True,
    )
    extracted = dest_dir / "squashfs-root"
    if not extracted.exists():
        raise RuntimeError(f"--appimage-extract did not produce {extracted}")


def _extract_innosetup(archive_path: Path, dest_dir: Path) -> None:
    if shutil.which("innoextract") is None:
        raise RuntimeError(
            "innoextract not found on PATH — required for archive_type=innosetup"
        )
    subprocess.run(
        ["innoextract", "-d", str(dest_dir), str(archive_path)],
        check=True, capture_output=True,
    )


# ---------------------------------------------------------------------------
# Plugin deploy — cross-platform equivalent of scripts/deploy_lua.ps1
# ---------------------------------------------------------------------------


def _deploy_plugin(dt_config: Path, repo_lua_dir: Path) -> dict[str, list[str]]:
    """Copy lua/photonforge/*.lua + .css into dt_config/lua/photonforge/.

    Mirrors scripts/deploy_lua.ps1: skip a file whose destination already has
    identical bytes (idempotent, no needless rewrite), and append the
    `require "photonforge/main"` line to luarc only if it isn't already
    there. Unlike deploy_lua.ps1, this never bakes cli_path/cartridge_path —
    see write_baseline_darktablerc for why.
    """
    dt_config, repo_lua_dir = Path(dt_config), Path(repo_lua_dir)
    dst_dir = dt_config / "lua" / "photonforge"
    dst_dir.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    up_to_date: list[str] = []
    for name in (*LUA_FILES, CSS_FILE):
        src = repo_lua_dir / name
        if not src.exists():
            if name == CSS_FILE:
                continue  # optional polish, not required
            raise FileNotFoundError(f"Missing plugin file: {src}")
        dst = dst_dir / name
        if dst.exists() and dst.read_bytes() == src.read_bytes():
            up_to_date.append(name)
            continue
        shutil.copy2(src, dst)
        copied.append(name)

    luarc = dt_config / "luarc"
    existing = luarc.read_text(encoding="utf-8") if luarc.exists() else ""
    if REQUIRE_LINE not in existing:
        with open(luarc, "a", encoding="utf-8") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            fh.write(REQUIRE_LINE + "\n")

    return {"copied": copied, "up_to_date": up_to_date}


def write_baseline_darktablerc(dt_config: Path) -> Path:
    """Write a darktablerc with cli_path/cartridge_path/models_path BLANK.

    Deliberately the opposite of deploy_lua.ps1's auto-bake: a portable
    drive's mount point/drive letter changes between machines, so baking an
    absolute path here would be wrong on the very next host. Leaving these
    blank is what makes Task 1's self-location logic (runner.lua's cli() /
    models_dir(), which probe <root>/runtime and <root>/models) activate.

    Idempotent by not overwriting an existing darktablerc — after a first
    real Darktable run it holds unrelated user preferences.
    """
    dt_config = Path(dt_config)
    dt_config.mkdir(parents=True, exist_ok=True)
    rc = dt_config / "darktablerc"
    if rc.exists():
        return rc
    lines = [
        "lua/photonforge/cli_path=",
        "lua/photonforge/cartridge_path=",
        "lua/photonforge/models_path=",
    ]
    rc.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rc


# ---------------------------------------------------------------------------
# Launcher templating
# ---------------------------------------------------------------------------


def render_launchers(templates_dir: Path, drive_root: Path) -> list[Path]:
    """Copy deploy/portable/PHOTONForge.{ps1,bat,sh}.tmpl onto the drive root.

    The templates carry no substitution tokens — they resolve their own root
    at runtime ($PSScriptRoot / %~dp0 / readlink -f) — so this is a straight
    copy plus a best-effort exec bit on the .sh, kept as its own function
    because the plan requires a regex check that no absolute host path leaks
    into what lands on the drive.
    """
    templates_dir, drive_root = Path(templates_dir), Path(drive_root)
    drive_root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for tmpl_name, out_name in LAUNCHER_TEMPLATES:
        src = templates_dir / tmpl_name
        if not src.exists():
            raise FileNotFoundError(f"Missing launcher template: {src}")
        dst = drive_root / out_name
        shutil.copy2(src, dst)
        if out_name.endswith(".sh"):
            try:
                dst.chmod(dst.stat().st_mode | 0o111)
            except OSError:
                pass
        written.append(dst)
    return written


# ---------------------------------------------------------------------------
# Layout builder — the make-portable orchestrator
# ---------------------------------------------------------------------------


@dataclass
class PortableBuildResult:
    drive_root: Path
    dt_config: Path
    plugin: dict[str, list[str]]
    apps: dict[str, Path]
    runtimes: dict[str, Path]
    models_copied: bool
    launchers: list[Path]
    manifest_lock: Path


def _copy_runtime(cli_src: Path, drive_root: Path, os_name: str) -> Path | None:
    src = Path(cli_src) / os_name
    if not src.exists():
        return None
    dst = drive_root / "runtime" / os_name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return dst


def _copy_models(models_src: Path, drive_root: Path,
                  progress: Callable[[str], None] | None) -> Path:
    models_src = Path(models_src)
    dst = drive_root / "models"
    dst.mkdir(parents=True, exist_ok=True)
    files = [p for p in models_src.rglob("*") if p.is_file()]
    for i, src in enumerate(files, start=1):
        rel = src.relative_to(models_src)
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
        if progress is not None and (i % 25 == 0 or i == len(files)):
            progress(f"models: {i}/{len(files)} files")
    return dst


def _git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None  # best-effort provenance; never blocks the build


def _write_manifest_lock(
    drive_root: Path, oses: list[str], manifest: PortableManifest | None,
    apps: dict[str, Path],
) -> Path:
    darktable_entries: dict[str, dict] = {}
    for os_name in apps:
        target = manifest.target_for(os_name) if manifest else None
        if target is None:
            continue
        darktable_entries[os_name] = {
            "version": target.version,
            "url": target.url,
            "sha256": target.sha256,
            "archive_type": target.archive_type,
            "binary_relpath": target.binary_relpath,
        }
    body = {
        "schema": LOCK_SCHEMA_VERSION,
        "tool_version": tool_version(),
        "created_at": utcnow(),
        "git_sha": _git_sha(),
        "oses": oses,
        "darktable": darktable_entries,
    }
    dot_dir = Path(drive_root) / ".photonforge"
    dot_dir.mkdir(parents=True, exist_ok=True)
    path = dot_dir / MANIFEST_LOCK_NAME
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    return path


def build_portable_layout(
    drive_root: Path,
    *,
    oses: list[str],
    manifest: PortableManifest | None,
    templates_dir: Path,
    repo_lua_dir: Path,
    models_src: Path | None = None,
    cli_src: Path | None = None,
    cache_dir: Path | None = None,
    offline: bool = False,
    fetch: Callable[[str, Path], None] | None = None,
    progress: Callable[[str], None] | None = None,
) -> PortableBuildResult:
    """Assemble the full portable-drive tree onto an already-provisioned drive.

    `manifest` is optional: config/portable-manifest.yml (Task 7) may not
    exist yet, and a caller with a frozen CLI + models but no Darktable
    downloads pinned should still be able to build everything else. When
    `manifest` is None (or has no target for a requested OS), the Darktable
    app step for that OS is skipped rather than blocking the whole build.
    """
    drive_root = Path(drive_root)
    dt_config = drive_root / "dt-config"
    _progress = progress or (lambda _msg: None)

    _progress("plugin: deploying lua/photonforge")
    plugin = _deploy_plugin(dt_config, repo_lua_dir)
    write_baseline_darktablerc(dt_config)

    apps: dict[str, Path] = {}
    for os_name in oses:
        target = manifest.target_for(os_name) if manifest else None
        if target is None:
            logger.info("No manifest target for %s — skipping Darktable app step", os_name)
            continue
        if cache_dir is None:
            raise ValueError("cache_dir is required when the manifest has Darktable targets")
        _progress(f"darktable-{os_name}: downloading {target.version}")
        cached = download_verified(
            target.url, target.sha256, cache_dir, offline=offline, fetch=fetch,
        )
        app_dir = drive_root / "apps" / f"darktable-{os_name}"
        _progress(f"darktable-{os_name}: extracting")
        extract_archive(cached, app_dir, target.archive_type)
        apps[os_name] = app_dir

    runtimes: dict[str, Path] = {}
    if cli_src is not None:
        for os_name in oses:
            _progress(f"runtime/{os_name}: copying frozen CLI")
            dst = _copy_runtime(cli_src, drive_root, os_name)
            if dst is not None:
                runtimes[os_name] = dst

    models_copied = False
    if models_src is not None:
        _progress("models: copying")
        _copy_models(models_src, drive_root, _progress)
        models_copied = True

    _progress("launchers: writing")
    launchers = render_launchers(templates_dir, drive_root)

    _progress("manifest.lock.json: writing")
    manifest_lock = _write_manifest_lock(drive_root, oses, manifest, apps)

    return PortableBuildResult(
        drive_root=drive_root,
        dt_config=dt_config,
        plugin=plugin,
        apps=apps,
        runtimes=runtimes,
        models_copied=models_copied,
        launchers=launchers,
        manifest_lock=manifest_lock,
    )
