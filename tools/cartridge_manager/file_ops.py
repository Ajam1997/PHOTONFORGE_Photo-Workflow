"""Filesystem operations for photo moves and copies.

Uses a journal pattern: log intended operations before executing,
so partial failures can be recovered on next launch.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_PHOTO_EXTENSIONS = {
    ".arw", ".cr2", ".cr3", ".nef", ".orf", ".raf", ".rw2",
    ".dng", ".jpg", ".jpeg", ".tif", ".tiff", ".png",
}

_SIDECAR_EXTENSIONS = {".xmp"}


def _companion_files(photo_path: Path) -> list[Path]:
    """Return the photo file plus any sidecar files (.xmp).

    Handles both naming conventions:
      - PHOTONForge style: P001ICE0000001.xmp  (extension replaced)
      - Darktable style:   P001ICE0000001.ARW.xmp  (extension appended)
    """
    files = [photo_path]
    for ext in _SIDECAR_EXTENSIONS:
        # Convention 1: replace extension (.ARW -> .xmp)
        replaced = photo_path.with_suffix(ext)
        if replaced.exists():
            files.append(replaced)
        # Convention 2: append extension (.ARW.xmp)
        appended = photo_path.parent / (photo_path.name + ext)
        if appended.exists() and appended != replaced:
            files.append(appended)
    return files


@dataclass
class JournalEntry:
    operation: str  # "move" or "copy"
    src: str
    dst: str
    timestamp: str
    completed: bool = False


@dataclass
class OperationJournal:
    path: Path
    entries: list[JournalEntry] = field(default_factory=list)

    def add(self, op: str, src: Path, dst: Path) -> JournalEntry:
        entry = JournalEntry(
            operation=op,
            src=str(src),
            dst=str(dst),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self.entries.append(entry)
        self._flush()
        return entry

    def mark_complete(self, entry: JournalEntry) -> None:
        entry.completed = True
        self._flush()

    def _flush(self) -> None:
        data = [
            {
                "op": e.operation,
                "src": e.src,
                "dst": e.dst,
                "ts": e.timestamp,
                "done": e.completed,
            }
            for e in self.entries
        ]
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def clear(self) -> None:
        self.entries.clear()
        if self.path.exists():
            self.path.unlink()

    @classmethod
    def load(cls, path: Path) -> "OperationJournal":
        journal = cls(path=path)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            journal.entries = [
                JournalEntry(
                    operation=e["op"],
                    src=e["src"],
                    dst=e["dst"],
                    timestamp=e["ts"],
                    completed=e.get("done", False),
                )
                for e in data
            ]
        return journal

    def pending(self) -> list[JournalEntry]:
        return [e for e in self.entries if not e.completed]


def create_directory(cartridge_root: Path, folder_name: str) -> Path:
    """Create a new photo directory on the cartridge. Returns the created path."""
    new_dir = cartridge_root / folder_name
    new_dir.mkdir(parents=True, exist_ok=True)
    return new_dir


def move_photo(
    src_dir: Path,
    dst_dir: Path,
    filename: str,
    journal: OperationJournal | None = None,
) -> list[Path]:
    """Move a photo and its sidecars from src_dir to dst_dir.

    Returns the list of destination paths created.
    """
    src_photo = src_dir / filename
    if not src_photo.exists():
        raise FileNotFoundError(f"Source photo not found: {src_photo}")

    dst_dir.mkdir(parents=True, exist_ok=True)
    moved: list[Path] = []

    for src_file in _companion_files(src_photo):
        dst_file = dst_dir / src_file.name
        if dst_file.exists():
            raise FileExistsError(f"Destination already exists: {dst_file}")

        entry = journal.add("move", src_file, dst_file) if journal else None
        shutil.move(str(src_file), str(dst_file))
        moved.append(dst_file)
        if entry:
            journal.mark_complete(entry)

    return moved


def copy_photo(
    src_dir: Path,
    dst_dir: Path,
    filename: str,
    journal: OperationJournal | None = None,
) -> list[Path]:
    """Copy a photo and its sidecars from src_dir to dst_dir.

    Returns the list of destination paths created.
    """
    src_photo = src_dir / filename
    if not src_photo.exists():
        raise FileNotFoundError(f"Source photo not found: {src_photo}")

    dst_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []

    for src_file in _companion_files(src_photo):
        dst_file = dst_dir / src_file.name
        if dst_file.exists():
            raise FileExistsError(f"Destination already exists: {dst_file}")

        entry = journal.add("copy", src_file, dst_file) if journal else None
        shutil.copy2(str(src_file), str(dst_file))
        copied.append(dst_file)
        if entry:
            journal.mark_complete(entry)

    return copied


def rollback_pending(journal: OperationJournal) -> list[str]:
    """Attempt to reverse incomplete operations from a journal.

    Returns a list of human-readable descriptions of what was rolled back.
    """
    messages: list[str] = []
    for entry in journal.pending():
        dst = Path(entry.dst)
        src = Path(entry.src)
        if entry.operation == "move" and dst.exists() and not src.exists():
            shutil.move(str(dst), str(src))
            entry.completed = True
            messages.append(f"Rolled back move: {dst.name} -> {src.parent.name}/")
        elif entry.operation == "copy" and dst.exists():
            dst.unlink()
            entry.completed = True
            messages.append(f"Rolled back copy: removed {dst.name} from {dst.parent.name}/")
        else:
            messages.append(f"Cannot rollback {entry.operation}: {entry.src} -> {entry.dst}")
    journal._flush()
    return messages


def list_photos(directory: Path) -> list[str]:
    """Return sorted list of photo filenames in a directory."""
    if not directory.is_dir():
        return []
    return sorted(
        f.name
        for f in directory.iterdir()
        if f.is_file() and f.suffix.lower() in _PHOTO_EXTENSIONS
    )


# -- Scan & Rename ------------------------------------------------------------

import re
import sys


def _read_exif_timestamp(path: Path) -> str | None:
    try:
        import exifread
        with open(path, "rb") as f:
            tags = exifread.process_file(f, stop_tag="EXIF DateTimeOriginal", details=False)
        raw = tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime")
        if raw:
            return str(raw).replace(":", "-", 2)
        return None
    except Exception:
        return None


def _get_volume_label(drive_path: Path) -> str:
    if sys.platform == "win32":
        import ctypes
        root = drive_path.anchor
        if not root:
            return ""
        volume_name = ctypes.create_unicode_buffer(256)
        result = ctypes.windll.kernel32.GetVolumeInformationW(
            root, volume_name, 256, None, None, None, None, 0,
        )
        return volume_name.value if result else ""
    return ""


def extract_cartridge_id(label: str) -> str:
    m = re.search(r"-(\d+)$", label)
    if m:
        return m.group(1).zfill(3)[:3]
    return "000"


def derive_trip_code(folder_name: str) -> str:
    alpha = re.sub(r"[^A-Za-z]", "", folder_name).upper()
    if len(alpha) < 3:
        alpha = alpha.ljust(3, "X")
    return alpha[:3]


def format_photo_name(cart_id: str, trip_code: str, seq: int, ext: str) -> str:
    return f"P{cart_id}{trip_code}{seq:07d}{ext}"


def get_next_sequence(dest_dir: Path, cart_id: str, trip_code: str) -> int:
    prefix = f"P{cart_id}{trip_code}"
    max_seq = 0
    if dest_dir.exists():
        for p in dest_dir.iterdir():
            name = p.stem
            if name.startswith(prefix) and len(name) == 14:
                try:
                    seq_num = int(name[7:14])
                    max_seq = max(max_seq, seq_num)
                except ValueError:
                    pass
    return max_seq + 1


@dataclass
class ScanResult:
    total_found: int = 0
    already_named: int = 0
    renamed: int = 0
    errors: list[str] = field(default_factory=list)
    renames: list[tuple[str, str]] = field(default_factory=list)


_PHOTON_RE = re.compile(r"^P\d{3}[A-Z]{3}\d{7}\..+$")


def scan_and_rename(
    directory: Path,
    cartridge_root: Path,
    *,
    cart_id: str | None = None,
    trip_code: str | None = None,
    dry_run: bool = False,
    progress_callback=None,
) -> ScanResult:
    """Scan a directory for photos and rename them using the PHOTONForge convention.

    Files are sorted by EXIF timestamp before sequence assignment.
    Sidecars (.xmp, .ARW.xmp) are renamed alongside their photo.
    Files already matching the PHOTONForge pattern are skipped.

    Args:
        directory: Directory containing the photos
        cartridge_root: Root of the cartridge (for volume label)
        cart_id: Override cartridge ID (default: read from volume label)
        trip_code: Override trip code (default: derived from directory name)
        dry_run: If True, compute renames without executing
        progress_callback: Optional callable(current, total)

    Returns:
        ScanResult with counts and the list of (old_name, new_name) pairs.
    """
    result = ScanResult()

    if cart_id is None:
        label = _get_volume_label(cartridge_root)
        cart_id = extract_cartridge_id(label)
    if trip_code is None:
        trip_code = derive_trip_code(directory.name)

    photos = sorted(
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in _PHOTO_EXTENSIONS
    )
    result.total_found = len(photos)

    # Only skip files that already match THIS folder's cart_id + trip_code
    correct_prefix = f"P{cart_id}{trip_code}"
    to_rename: list[tuple[str | None, Path]] = []
    for p in photos:
        if _PHOTON_RE.match(p.name) and p.stem.startswith(correct_prefix):
            result.already_named += 1
            continue
        ts = _read_exif_timestamp(p)
        to_rename.append((ts or "9999", p))

    # Sort by EXIF timestamp
    to_rename.sort(key=lambda x: x[0])

    seq = get_next_sequence(directory, cart_id, trip_code)

    for i, (ts, src) in enumerate(to_rename):
        new_name = format_photo_name(cart_id, trip_code, seq, src.suffix)
        new_path = directory / new_name

        if new_path.exists():
            result.errors.append(f"{src.name}: target {new_name} already exists")
            seq += 1
            continue

        if not dry_run:
            try:
                # Rename sidecars first
                for sidecar in _companion_files(src)[1:]:  # skip the photo itself
                    if sidecar.suffix.lower() == ".xmp" and sidecar.name == src.name + ".xmp":
                        # Darktable style: old.ARW.xmp -> new.ARW.xmp
                        new_sidecar = directory / (new_name + ".xmp")
                    else:
                        # PHOTONForge style: old.xmp -> new.xmp
                        new_sidecar = new_path.with_suffix(".xmp")
                    if not new_sidecar.exists():
                        sidecar.rename(new_sidecar)

                src.rename(new_path)
            except Exception as e:
                result.errors.append(f"{src.name}: {e}")
                seq += 1
                continue

        result.renames.append((src.name, new_name))
        result.renamed += 1
        seq += 1

        if progress_callback:
            progress_callback(i + 1, len(to_rename))

    return result
