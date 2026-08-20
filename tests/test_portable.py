"""src/photo_workflow/portable.py — portable-drive plan Task 2.

Real testing where feasible (zip extraction, downloader verify pass/fail/
offline, layout builder against tmp_path, launcher template content).
appimage/innosetup extraction is dispatch-tested (subprocess mocked) since
neither tool is available in CI.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path

import pytest

from photo_workflow import portable

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "deploy" / "portable"
LUA_DIR = Path(__file__).resolve().parent.parent / "lua" / "photonforge"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# PortableManifest
# ---------------------------------------------------------------------------


def test_manifest_load_parses_both_oses(tmp_path):
    path = tmp_path / "manifest.yml"
    path.write_text(
        """
win:
  version: "5.0.0"
  url: "https://example.invalid/dt-win.zip"
  sha256: "abc123"
  archive_type: zip
  exe_relpath: "darktable/bin/darktable.exe"
linux:
  version: "5.0.0"
  url: "https://example.invalid/dt-linux.AppImage"
  sha256: "def456"
  archive_type: appimage
  apprun_relpath: "squashfs-root/AppRun"
""",
        encoding="utf-8",
    )
    manifest = portable.PortableManifest.load(path)
    assert manifest.win.version == "5.0.0"
    assert manifest.win.binary_relpath == "darktable/bin/darktable.exe"
    assert manifest.linux.archive_type == "appimage"
    assert manifest.linux.binary_relpath == "squashfs-root/AppRun"
    assert manifest.target_for("win") is manifest.win
    assert manifest.target_for("linux") is manifest.linux


def test_manifest_load_tolerates_one_os_missing(tmp_path):
    path = tmp_path / "manifest.yml"
    path.write_text(
        'win:\n  version: "5.0.0"\n  url: "https://x.invalid/a.zip"\n'
        '  sha256: "abc"\n  archive_type: zip\n  exe_relpath: "a.exe"\n',
        encoding="utf-8",
    )
    manifest = portable.PortableManifest.load(path)
    assert manifest.win is not None
    assert manifest.linux is None


def test_manifest_entry_requires_a_relpath():
    with pytest.raises(ValueError, match="relpath"):
        portable._target_from_dict(
            {"version": "1", "url": "https://x.invalid", "sha256": "a", "archive_type": "zip"}
        )


# ---------------------------------------------------------------------------
# download_verified
# ---------------------------------------------------------------------------


def test_download_verified_streams_and_checks_hash(tmp_path):
    payload = b"darktable bytes"
    digest = _sha256(payload)

    def fetch(url, dest):
        assert url == "https://example.invalid/dt.zip"
        dest.write_bytes(payload)

    cache = tmp_path / "cache"
    result = portable.download_verified(
        "https://example.invalid/dt.zip", digest, cache, fetch=fetch,
    )
    assert result == cache / digest
    assert result.read_bytes() == payload


def test_download_verified_rejects_a_hash_mismatch(tmp_path):
    def fetch(url, dest):
        dest.write_bytes(b"not what you expected")

    cache = tmp_path / "cache"
    with pytest.raises(portable.DownloadError, match="mismatch"):
        portable.download_verified(
            "https://example.invalid/dt.zip", _sha256(b"expected"), cache, fetch=fetch,
        )
    # the bad download must not be left in the cache under the expected hash
    assert not (cache / _sha256(b"expected")).exists()


def test_download_verified_reuses_a_valid_cache_hit_without_fetching(tmp_path):
    payload = b"cached bytes"
    digest = _sha256(payload)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / digest).write_bytes(payload)

    def fetch(url, dest):
        raise AssertionError("fetch should not be called on a valid cache hit")

    result = portable.download_verified(
        "https://example.invalid/dt.zip", digest, cache, fetch=fetch,
    )
    assert result.read_bytes() == payload


def test_download_verified_offline_cache_miss_raises(tmp_path):
    cache = tmp_path / "cache"
    with pytest.raises(portable.DownloadError, match="offline"):
        portable.download_verified(
            "https://example.invalid/dt.zip", "deadbeef", cache, offline=True,
            fetch=lambda *_: (_ for _ in ()).throw(AssertionError("no network under --offline")),
        )


def test_download_verified_offline_cache_hit_succeeds(tmp_path):
    payload = b"already have it"
    digest = _sha256(payload)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / digest).write_bytes(payload)

    result = portable.download_verified(
        "https://example.invalid/dt.zip", digest, cache, offline=True,
    )
    assert result.read_bytes() == payload


def test_download_verified_discards_a_corrupt_cache_entry(tmp_path):
    """A cache file that doesn't match its own filename-hash is re-fetched, not trusted."""
    digest = _sha256(b"good bytes")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / digest).write_bytes(b"corrupted leftovers from a crashed run")

    def fetch(url, dest):
        dest.write_bytes(b"good bytes")

    result = portable.download_verified(
        "https://example.invalid/dt.zip", digest, cache, fetch=fetch,
    )
    assert result.read_bytes() == b"good bytes"


# ---------------------------------------------------------------------------
# extract_archive
# ---------------------------------------------------------------------------


def test_extract_archive_zip_is_real(tmp_path):
    archive = tmp_path / "dt.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("darktable/bin/darktable.exe", "not really an exe")
        zf.writestr("darktable/share/readme.txt", "hi")
    dest = tmp_path / "extracted"
    portable.extract_archive(archive, dest, "zip")
    assert (dest / "darktable" / "bin" / "darktable.exe").read_text() == "not really an exe"


def test_extract_archive_unknown_type_raises(tmp_path):
    with pytest.raises(ValueError, match="Unknown archive_type"):
        portable.extract_archive(tmp_path / "x", tmp_path / "y", "rar")


def test_extract_archive_appimage_dispatches_extract_flag(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, cwd=None, **kwargs):
        calls.append((cmd, cwd))
        # simulate what --appimage-extract would produce
        (Path(cwd) / "squashfs-root").mkdir()
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(portable.subprocess, "run", fake_run)
    archive = tmp_path / "dt.AppImage"
    archive.write_bytes(b"fake appimage")
    dest = tmp_path / "extracted"
    portable.extract_archive(archive, dest, "appimage")

    assert calls[0][0][1] == "--appimage-extract"
    assert (dest / "squashfs-root").exists()
    copied = dest / "dt.AppImage"
    assert copied.exists()


def test_extract_archive_appimage_raises_if_extract_produces_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        portable.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess([], 0),
    )

    archive = tmp_path / "dt.AppImage"
    archive.write_bytes(b"fake")
    with pytest.raises(RuntimeError, match="squashfs-root"):
        portable.extract_archive(archive, tmp_path / "extracted", "appimage")


def test_extract_archive_innosetup_dispatches_to_innoextract(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(portable.shutil, "which", lambda name: "/usr/bin/innoextract")
    monkeypatch.setattr(
        portable.subprocess, "run",
        lambda cmd, **k: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0),
    )
    archive = tmp_path / "dt-setup.exe"
    archive.write_bytes(b"fake installer")
    portable.extract_archive(archive, tmp_path / "extracted", "innosetup")
    assert calls[0][0] == "innoextract"
    assert str(archive) in calls[0]


def test_extract_archive_innosetup_requires_the_tool_on_path(tmp_path, monkeypatch):
    monkeypatch.setattr(portable.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="innoextract"):
        portable.extract_archive(tmp_path / "x.exe", tmp_path / "y", "innosetup")


def test_missing_innoextract_error_explains_the_version_requirement(tmp_path, monkeypatch):
    """The distro innoextract is too old for Inno Setup 6.7 — say so."""
    monkeypatch.setattr(portable.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError) as excinfo:
        portable.extract_archive(tmp_path / "x.exe", tmp_path / "y", "innosetup")
    assert "6.7" in str(excinfo.value)


def test_extractor_failure_becomes_a_runtime_error_carrying_the_tools_output(tmp_path,
                                                                             monkeypatch):
    """A failing extractor must not escape as a bare CalledProcessError.

    innoextract 1.9 exits 2 on an Inno Setup 6.7 installer having written
    nothing. CalledProcessError is not a RuntimeError, so the make-portable
    CLI's handler would let it through as a traceback, and its message
    ("returned non-zero exit status 2") hides the tool's real complaint.
    """
    monkeypatch.setattr(portable.shutil, "which", lambda name: "/usr/bin/innoextract")

    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(
            2, cmd, output="", stderr="Could not determine setup data version!"
        )

    monkeypatch.setattr(portable.subprocess, "run", fake_run)
    archive = tmp_path / "dt-setup.exe"
    archive.write_bytes(b"fake installer")

    with pytest.raises(RuntimeError) as excinfo:
        portable.extract_archive(archive, tmp_path / "extracted", "innosetup")
    message = str(excinfo.value)
    assert not isinstance(excinfo.value, subprocess.CalledProcessError)
    assert "Could not determine setup data version!" in message   # the tool's own words
    assert "exit 2" in message
    assert "6.7" in message                                        # the actionable hint


# ---------------------------------------------------------------------------
# _deploy_plugin / write_baseline_darktablerc
# ---------------------------------------------------------------------------


def test_deploy_plugin_copies_all_lua_files_and_css(tmp_path):
    dt_config = tmp_path / "dt-config"
    result = portable._deploy_plugin(dt_config, LUA_DIR)
    dst = dt_config / "lua" / "photonforge"
    for name in portable.LUA_FILES:
        assert (dst / name).exists(), name
    assert (dst / portable.CSS_FILE).exists()
    assert set(result["copied"]) >= set(portable.LUA_FILES)
    assert (dt_config / "luarc").read_text(encoding="utf-8").count(portable.REQUIRE_LINE) == 1


def test_deploy_plugin_is_idempotent_across_two_runs(tmp_path):
    dt_config = tmp_path / "dt-config"
    portable._deploy_plugin(dt_config, LUA_DIR)
    second = portable._deploy_plugin(dt_config, LUA_DIR)
    assert second["copied"] == []
    assert set(second["up_to_date"]) >= set(portable.LUA_FILES)
    # luarc still has exactly one require line, not duplicated
    assert (dt_config / "luarc").read_text(encoding="utf-8").count(portable.REQUIRE_LINE) == 1


def test_deploy_plugin_preserves_an_existing_luarc_without_the_require_line(tmp_path):
    dt_config = tmp_path / "dt-config"
    dt_config.mkdir(parents=True)
    (dt_config / "luarc").write_text("require \"darktable/some_other_script\"", encoding="utf-8")
    portable._deploy_plugin(dt_config, LUA_DIR)
    content = (dt_config / "luarc").read_text(encoding="utf-8")
    assert "some_other_script" in content
    assert portable.REQUIRE_LINE in content


def test_deploy_plugin_missing_source_raises(tmp_path):
    empty_lua_dir = tmp_path / "not-lua"
    empty_lua_dir.mkdir()
    with pytest.raises(FileNotFoundError):
        portable._deploy_plugin(tmp_path / "dt-config", empty_lua_dir)


def test_write_baseline_darktablerc_leaves_paths_blank(tmp_path):
    dt_config = tmp_path / "dt-config"
    rc = portable.write_baseline_darktablerc(dt_config)
    content = rc.read_text(encoding="utf-8")
    assert "lua/photonforge/cli_path=\n" in content
    assert "lua/photonforge/cartridge_path=\n" in content
    assert "lua/photonforge/models_path=\n" in content


def test_write_baseline_darktablerc_does_not_clobber_an_existing_one(tmp_path):
    dt_config = tmp_path / "dt-config"
    dt_config.mkdir(parents=True)
    (dt_config / "darktablerc").write_text("some/other/pref=1\n", encoding="utf-8")
    rc = portable.write_baseline_darktablerc(dt_config)
    assert rc.read_text(encoding="utf-8") == "some/other/pref=1\n"


# ---------------------------------------------------------------------------
# render_launchers — no absolute host path may leak in
# ---------------------------------------------------------------------------

_ABSOLUTE_HOST_PATH = re.compile(r"(/home/\w+|/root|[A-Za-z]:\\Users\\)")


def test_render_launchers_copies_all_three_and_sets_exec_bit(tmp_path):
    drive = tmp_path / "drive"
    written = portable.render_launchers(TEMPLATES_DIR, drive)
    names = {p.name for p in written}
    assert names == {"PHOTONForge.ps1", "PHOTONForge.bat", "PHOTONForge.sh"}
    sh = drive / "PHOTONForge.sh"
    assert sh.stat().st_mode & 0o111


def test_render_launchers_contain_no_absolute_host_path(tmp_path):
    drive = tmp_path / "drive"
    written = portable.render_launchers(TEMPLATES_DIR, drive)
    for path in written:
        text = path.read_text(encoding="utf-8")
        assert not _ABSOLUTE_HOST_PATH.search(text), f"{path.name} leaked a host path"


def test_render_launchers_use_drive_relative_resolution():
    ps1 = (TEMPLATES_DIR / "PHOTONForge.ps1.tmpl").read_text(encoding="utf-8")
    bat = (TEMPLATES_DIR / "PHOTONForge.bat.tmpl").read_text(encoding="utf-8")
    sh = (TEMPLATES_DIR / "PHOTONForge.sh.tmpl").read_text(encoding="utf-8")
    assert "$PSScriptRoot" in ps1
    assert "%~dp0" in bat
    assert "readlink -f" in sh
    assert "appimage-extract-and-run" in sh  # FUSE-less fallback present


def test_windows_launcher_resolves_binary_under_the_app_dir():
    """binary_relpath is relative to apps/darktable-win/, not to the drive root.

    The lockfile records e.g. "app/bin/darktable.exe"; joining that straight
    onto $PSScriptRoot yields <DRIVE>\\app\\bin\\darktable.exe, which does not
    exist. Verified against a real extracted darktable 5.6.0 tree.
    """
    ps1 = (TEMPLATES_DIR / "PHOTONForge.ps1.tmpl").read_text(encoding="utf-8")
    assert "apps\\darktable-win" in ps1
    sh = (TEMPLATES_DIR / "PHOTONForge.sh.tmpl").read_text(encoding="utf-8")
    assert "apps/darktable-linux" in sh


def test_render_launchers_missing_template_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        portable.render_launchers(tmp_path / "no-templates-here", tmp_path / "drive")


# ---------------------------------------------------------------------------
# build_portable_layout — the orchestrator
# ---------------------------------------------------------------------------


def _fake_runtime_tree(root: Path) -> None:
    for os_name, exe in (("win", "photo-workflow.exe"), ("linux", "photo-workflow")):
        d = root / os_name
        d.mkdir(parents=True)
        (d / exe).write_bytes(b"frozen cli")
        (d / "_internal").mkdir()
        (d / "_internal" / "lib.bin").write_bytes(b"native lib")


def test_build_portable_layout_without_manifest_skips_darktable_app(tmp_path):
    drive = tmp_path / "drive"
    drive.mkdir()
    cli_src = tmp_path / "runtime"
    _fake_runtime_tree(cli_src)
    models_src = tmp_path / "models"
    models_src.mkdir()
    (models_src / "florence2_int8").mkdir()
    (models_src / "florence2_int8" / "model.onnx").write_bytes(b"onnx bytes")

    result = portable.build_portable_layout(
        drive, oses=["win", "linux"], manifest=None,
        templates_dir=TEMPLATES_DIR, repo_lua_dir=LUA_DIR,
        models_src=models_src, cli_src=cli_src,
    )

    assert result.apps == {}
    assert set(result.runtimes) == {"win", "linux"}
    assert (drive / "runtime" / "win" / "photo-workflow.exe").exists()
    assert (drive / "runtime" / "linux" / "_internal" / "lib.bin").exists()
    assert result.models_copied
    assert (drive / "models" / "florence2_int8" / "model.onnx").exists()
    assert (drive / "dt-config" / "lua" / "photonforge" / "main.lua").exists()
    assert (drive / "dt-config" / "darktablerc").exists()
    assert (drive / "PHOTONForge.sh").exists()

    lock = json.loads(result.manifest_lock.read_text(encoding="utf-8"))
    assert lock["schema"] == 1
    assert lock["oses"] == ["win", "linux"]
    assert lock["darktable"] == {}
    assert "tool_version" in lock and "created_at" in lock


def test_build_portable_layout_with_manifest_downloads_and_extracts(tmp_path):
    drive = tmp_path / "drive"
    drive.mkdir()

    win_zip = tmp_path / "src-dt-win.zip"
    with zipfile.ZipFile(win_zip, "w") as zf:
        zf.writestr("darktable/bin/darktable.exe", "fake windows darktable")
    win_bytes = win_zip.read_bytes()
    win_digest = _sha256(win_bytes)

    manifest_path = tmp_path / "manifest.yml"
    manifest_path.write_text(
        f"""
win:
  version: "5.0.0"
  url: "https://example.invalid/dt-win.zip"
  sha256: "{win_digest}"
  archive_type: zip
  exe_relpath: "darktable/bin/darktable.exe"
""",
        encoding="utf-8",
    )
    manifest = portable.PortableManifest.load(manifest_path)

    def fetch(url, dest):
        dest.write_bytes(win_bytes)

    result = portable.build_portable_layout(
        drive, oses=["win"], manifest=manifest,
        templates_dir=TEMPLATES_DIR, repo_lua_dir=LUA_DIR,
        cache_dir=tmp_path / "cache", fetch=fetch,
    )

    assert set(result.apps) == {"win"}
    assert (drive / "apps" / "darktable-win" / "darktable" / "bin" / "darktable.exe").exists()
    lock = json.loads(result.manifest_lock.read_text(encoding="utf-8"))
    assert lock["darktable"]["win"]["sha256"] == win_digest
    assert lock["darktable"]["win"]["binary_relpath"] == "darktable/bin/darktable.exe"


def test_build_portable_layout_requires_cache_dir_when_manifest_has_targets(tmp_path):
    drive = tmp_path / "drive"
    drive.mkdir()
    manifest = portable.PortableManifest(
        win=portable.DarktableTarget(
            version="5.0.0", url="https://x.invalid/a.zip", sha256="deadbeef",
            archive_type="zip", binary_relpath="a.exe",
        )
    )
    with pytest.raises(ValueError, match="cache_dir"):
        portable.build_portable_layout(
            drive, oses=["win"], manifest=manifest,
            templates_dir=TEMPLATES_DIR, repo_lua_dir=LUA_DIR,
        )


def test_build_portable_layout_progress_callback_is_invoked(tmp_path):
    drive = tmp_path / "drive"
    drive.mkdir()
    messages = []
    portable.build_portable_layout(
        drive, oses=[], manifest=None,
        templates_dir=TEMPLATES_DIR, repo_lua_dir=LUA_DIR,
        progress=messages.append,
    )
    assert any("plugin" in m for m in messages)
    assert any("launchers" in m for m in messages)


# ---------------------------------------------------------------------------
# config/portable-manifest.yml — the shipped provisioning pins (Task 7)
# ---------------------------------------------------------------------------

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "config" / "portable-manifest.yml"


def test_shipped_manifest_exists_and_loads():
    assert MANIFEST_PATH.exists(), f"missing {MANIFEST_PATH}"
    manifest = portable.PortableManifest.load(MANIFEST_PATH)
    assert manifest.win is not None
    assert manifest.linux is not None


@pytest.mark.parametrize("os_name", ["win", "linux"])
def test_shipped_manifest_entries_are_well_formed(os_name):
    """A malformed pin fails at provisioning time on the operator's machine,
    after a multi-hundred-MB download — cheap to catch here instead."""
    target = portable.PortableManifest.load(MANIFEST_PATH).target_for(os_name)
    assert re.fullmatch(r"[0-9a-f]{64}", target.sha256), "sha256 must be 64 lowercase hex"
    assert target.url.startswith("https://"), "downloads must be over https"
    assert target.archive_type in {"zip", "appimage", "innosetup"}
    assert target.binary_relpath and not target.binary_relpath.startswith("/")
    assert target.version


def test_shipped_manifest_linux_is_an_appimage_with_a_squashfs_apprun():
    """PHOTONForge.sh looks for squashfs-root/AppRun specifically."""
    target = portable.PortableManifest.load(MANIFEST_PATH).target_for("linux")
    assert target.archive_type == "appimage"
    assert target.binary_relpath == "squashfs-root/AppRun"
