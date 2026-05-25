r"""Keyboard-driven corpus labelling tool.

Tab through images in a photonforge.db folder and assign multi-genre labels
via single keystrokes. Used to build the calibration corpus for FR-1.7.1.

Example (filter to images the router called "general", since those are the
ones we most need to relabel):

    python scripts/label_corpus.py \
        --cartridge H:\ \
        --source-folder TEST_1 \
        --source-dir H:\TEST_1 \
        --output corpus/genre_labels.jsonl

Labels are appended to the JSONL output file as you commit each image.
You can stop and resume — already-labelled filenames are skipped on restart.

Key bindings inside the window:
    w wildlife    l landscape   p portrait   s street
    a architecture   m macro    e event      g general
    c custom genre (free text)
    SPACE / ENTER  commit selection and advance
    BACKSPACE      clear current selection
    TAB            skip image (records empty label)
    R              mark as needs_review and advance
    LEFT           go back to previous labelled image
    ESC / Q        quit (already-committed images are saved)
"""

from __future__ import annotations

import argparse
import getpass
import json
import re
import sqlite3
import sys
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import simpledialog
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

# Allow running as a standalone script from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


WINDOW_W = 1000
WINDOW_H = 900
PREVIEW_H = 600

BUILTIN_GENRES = {
    "w": "wildlife",
    "l": "landscape",
    "p": "portrait",
    "s": "street",
    "a": "architecture",
    "m": "macro",
    "e": "event",
    "g": "general",
}

RAW_EXTS = {".arw", ".cr2", ".cr3", ".nef", ".dng", ".raf", ".rw2", ".orf",
            ".pef", ".srw", ".3fr", ".mef"}

_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def slugify(name: str) -> str:
    """Coerce a free-text genre name into a-z0-9- only."""
    s = name.strip().lower().replace(" ", "-")
    s = _SLUG_RE.sub("-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--cartridge", required=True, type=Path,
                   help="Cartridge root containing photonforge.db")
    p.add_argument("--source-folder", required=True,
                   help="Folder/table name (e.g. TEST_1)")
    p.add_argument("--source-dir", required=True, type=Path,
                   help="Directory containing the actual photo files")
    p.add_argument("--output", default="corpus/genre_labels.jsonl", type=Path,
                   help="JSONL labels file (default: corpus/genre_labels.jsonl)")
    p.add_argument("--filter-router-genre", default="general",
                   help="Only label images whose router primary_genre matches this "
                        "(default: 'general' — the most error-prone bucket). "
                        "Pass '' to label all images.")
    p.add_argument("--limit", type=int, default=None,
                   help="Stop after labelling N images in this session")
    p.add_argument("--include-skipped", action="store_true",
                   help="Re-prompt for images previously skipped (empty labels)")
    p.add_argument("--labeler", default=None,
                   help="Labeler name recorded in JSONL (default: current user)")
    return p.parse_args()


# --- DB access --------------------------------------------------------------

def load_candidates(
    db_path: Path,
    table: str,
    source_dir: Path,
    filter_router_genre: str,
) -> list[dict]:
    """Read candidate rows from the photonforge.db folder table.

    Returns a list of dicts with filename, original_name, primary_genre,
    genre_confidence, exif_timestamp — for each row whose file exists on disk
    and matches the --filter-router-genre constraint.
    """
    if not db_path.exists():
        raise SystemExit(f"photonforge.db not found at {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"SELECT filename, original_name, primary_genre, genre_confidence, "
        f"genres, needs_review, exif_timestamp FROM [{table}]"
    ).fetchall()
    conn.close()

    out: list[dict] = []
    for r in rows:
        if not (source_dir / r["filename"]).is_file():
            continue
        if filter_router_genre and (r["primary_genre"] or "") != filter_router_genre:
            continue
        out.append(dict(r))
    return out


# --- Persistence ------------------------------------------------------------

class LabelStore:
    """Append-only JSONL store for genre labels."""

    def __init__(self, path: Path, labeler: str) -> None:
        self.path = path
        self.labeler = labeler
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._labelled: set[str] = set()
        self._load_existing()

    def _load_existing(self) -> None:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "filename" in rec:
                    self._labelled.add(rec["filename"])

    def is_labelled(self, filename: str) -> bool:
        return filename in self._labelled

    def commit(
        self,
        filename: str,
        genres: list[str],
        source_folder: str,
        needs_review: bool,
    ) -> None:
        rec = {
            "filename": filename,
            "genres": genres,
            "source_folder": source_folder,
            "needs_review": needs_review,
            "labeled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "labeler": self.labeler,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        self._labelled.add(filename)


# --- Image loading ----------------------------------------------------------

def load_image_for_preview(path: Path) -> "Image.Image":
    """Decode a photo file to a Pillow Image at half size for RAW formats."""
    from PIL import Image

    if path.suffix.lower() in RAW_EXTS:
        import rawpy
        with rawpy.imread(str(path)) as raw:
            arr = raw.postprocess(
                half_size=True,
                no_auto_bright=False,
                use_camera_wb=True,
                output_bps=8,
            )
        return Image.fromarray(arr)

    return Image.open(path)


def read_exif_summary(path: Path) -> str:
    """Read a short EXIF summary string for the info bar."""
    try:
        import exifread

        with open(path, "rb") as f:
            tags = exifread.process_file(f, details=False)
    except Exception:
        return ""

    parts: list[str] = []
    fl = tags.get("EXIF FocalLength")
    if fl:
        v = fl.values[0]
        mm = float(v.num) / float(v.den) if v.den else float(v.num)
        parts.append(f"{mm:.0f}mm")
    fn = tags.get("EXIF FNumber")
    if fn:
        v = fn.values[0]
        fnum = float(v.num) / float(v.den) if v.den else float(v.num)
        parts.append(f"f/{fnum:.1f}")
    et = tags.get("EXIF ExposureTime")
    if et:
        parts.append(f"{et}s")
    iso = tags.get("EXIF ISOSpeedRatings")
    if iso:
        parts.append(f"ISO {iso}")
    return "  ".join(parts)


# --- Tk UI ------------------------------------------------------------------

class CorpusLabeller:
    def __init__(
        self,
        candidates: list[dict],
        source_dir: Path,
        source_folder: str,
        store: LabelStore,
        include_skipped: bool,
        session_limit: int | None,
    ) -> None:
        self.candidates = candidates
        self.source_dir = source_dir
        self.source_folder = source_folder
        self.store = store
        self.include_skipped = include_skipped
        self.session_limit = session_limit

        self.queue: list[dict] = [
            c for c in candidates if not store.is_labelled(c["filename"])
        ]
        self.session_started_at = datetime.now(timezone.utc)
        self.session_committed = 0
        self.idx = 0
        self.selection: set[str] = set()
        self.history: list[tuple[int, set[str], bool]] = []  # for LEFT undo

        self._build_ui()
        self._load_current()

    # --- UI ----------------------------------------------------------------

    def _build_ui(self) -> None:
        self.root = tk.Tk()
        self.root.title("PHOTONForge Corpus Labeller")
        self.root.geometry(f"{WINDOW_W}x{WINDOW_H}")
        self.root.resizable(False, False)
        self.root.configure(bg="#222")

        self.image_label = tk.Label(self.root, bg="#000")
        self.image_label.place(x=0, y=0, width=WINDOW_W, height=PREVIEW_H)

        self.info_var = tk.StringVar()
        info = tk.Label(
            self.root, textvariable=self.info_var, fg="#ddd", bg="#333",
            anchor="w", padx=10, font=("Consolas", 10),
        )
        info.place(x=0, y=PREVIEW_H, width=WINDOW_W, height=40)

        self.router_var = tk.StringVar()
        router = tk.Label(
            self.root, textvariable=self.router_var, fg="#aaa", bg="#2a2a2a",
            anchor="w", padx=10, font=("Consolas", 10),
        )
        router.place(x=0, y=PREVIEW_H + 40, width=WINDOW_W, height=30)

        self.selection_var = tk.StringVar()
        sel = tk.Label(
            self.root, textvariable=self.selection_var, fg="#7df", bg="#1a1a1a",
            anchor="w", padx=10, font=("Consolas", 14, "bold"),
        )
        sel.place(x=0, y=PREVIEW_H + 70, width=WINDOW_W, height=44)

        self.progress_var = tk.StringVar()
        prog = tk.Label(
            self.root, textvariable=self.progress_var, fg="#888", bg="#1a1a1a",
            anchor="w", padx=10, font=("Consolas", 10),
        )
        prog.place(x=0, y=PREVIEW_H + 114, width=WINDOW_W, height=26)

        legend = (
            "w wildlife   l landscape   p portrait   s street   "
            "a architecture   m macro   e event   g general\n"
            "c custom    SPACE commit    BACKSPACE clear    "
            "TAB skip    R needs_review    LEFT back    ESC quit"
        )
        legend_lbl = tk.Label(
            self.root, text=legend, fg="#888", bg="#222",
            anchor="w", padx=10, justify="left", font=("Consolas", 9),
        )
        legend_lbl.place(x=0, y=PREVIEW_H + 140, width=WINDOW_W,
                         height=WINDOW_H - PREVIEW_H - 140)

        self.root.bind("<KeyPress>", self._on_key)

    # --- State -------------------------------------------------------------

    def _current(self) -> dict | None:
        if self.idx >= len(self.queue):
            return None
        return self.queue[self.idx]

    def _load_current(self) -> None:
        cur = self._current()
        if cur is None:
            self._finish()
            return

        path = self.source_dir / cur["filename"]
        try:
            img = load_image_for_preview(path)
        except Exception as e:
            self.image_label.configure(text=f"<could not load {path.name}: {e}>",
                                       image="", fg="#f88")
            self._render_info_and_progress()
            return

        from PIL import ImageTk

        img.thumbnail((WINDOW_W, PREVIEW_H))
        self.tk_img = ImageTk.PhotoImage(img)
        self.image_label.configure(image=self.tk_img, text="")

        self.selection = set()
        self._render_info_and_progress()

    def _render_info_and_progress(self) -> None:
        cur = self._current()
        if cur is None:
            return
        path = self.source_dir / cur["filename"]
        exif = read_exif_summary(path)
        self.info_var.set(f"{cur['filename']}    {exif}")

        try:
            router_genres = json.loads(cur["genres"]) if cur["genres"] else []
        except (TypeError, json.JSONDecodeError):
            router_genres = []
        router_summary = ", ".join(
            f"{e['g']} ({e['c']:.2f})" for e in router_genres
        ) or (cur["primary_genre"] or "(none)")
        nr = " · needs_review" if cur["needs_review"] else ""
        self.router_var.set(f"router said: {router_summary}{nr}")

        sel_str = "  ".join(f"[{g}]" for g in sorted(self.selection)) or "(none selected)"
        self.selection_var.set(sel_str)

        done = self.session_committed
        total_session = self.session_limit or len(self.queue)
        remaining = max(0, total_session - done)
        elapsed = (datetime.now(timezone.utc) - self.session_started_at).total_seconds()
        per_item = (elapsed / done) if done else 0.0
        eta = f"{(per_item * remaining) / 60:.1f} min" if per_item > 0 else "—"
        self.progress_var.set(
            f"{done}/{total_session} this session   "
            f"avg {per_item:.1f}s/img   eta {eta}   "
            f"queue position {self.idx + 1}/{len(self.queue)}"
        )

    # --- Key handlers ------------------------------------------------------

    def _on_key(self, event: tk.Event) -> None:
        cur = self._current()
        if cur is None:
            return

        key = event.keysym.lower()

        if key in ("escape", "q"):
            self.root.destroy()
            return

        if key == "tab":
            self._commit(genres=[], needs_review=False, skipped=True)
            return

        if key == "r":
            self._commit(genres=sorted(self.selection), needs_review=True, skipped=False)
            return

        if key in ("space", "return"):
            if not self.selection:
                # Refuse empty commit unless TAB or R
                return
            self._commit(genres=sorted(self.selection), needs_review=False, skipped=False)
            return

        if key == "backspace":
            self.selection.clear()
            self._render_info_and_progress()
            return

        if key == "left":
            self._go_back()
            return

        if key == "c":
            self._prompt_custom_genre()
            return

        if key in BUILTIN_GENRES:
            g = BUILTIN_GENRES[key]
            if g in self.selection:
                self.selection.remove(g)
            else:
                self.selection.add(g)
            self._render_info_and_progress()

    def _prompt_custom_genre(self) -> None:
        raw = simpledialog.askstring(
            "Custom genre",
            "Genre name (a-z, 0-9, dashes):",
            parent=self.root,
        )
        if not raw:
            return
        g = slugify(raw)
        if not g:
            return
        self.selection.add(g)
        self._render_info_and_progress()

    def _commit(self, genres: list[str], needs_review: bool, skipped: bool) -> None:
        cur = self._current()
        if cur is None:
            return
        self.history.append((self.idx, set(self.selection), needs_review))
        self.store.commit(
            filename=cur["filename"],
            genres=list(genres),
            source_folder=self.source_folder,
            needs_review=needs_review,
        )
        if not skipped or self.include_skipped is False:
            # Both committed-with-genres and skipped count toward session progress.
            self.session_committed += 1
        if self.session_limit and self.session_committed >= self.session_limit:
            self._finish()
            return
        self.idx += 1
        self._load_current()

    def _go_back(self) -> None:
        if self.idx == 0 or not self.history:
            return
        # Remove the most recent label from the JSONL by rewriting (uncommon path)
        prev_idx, prev_sel, _ = self.history.pop()
        self._rewind_label(self.queue[prev_idx]["filename"])
        self.idx = prev_idx
        self.selection = prev_sel
        self._load_current()

    def _rewind_label(self, filename: str) -> None:
        """Remove the most recent JSONL entry for filename so it can be re-labeled."""
        if not self.store.path.exists():
            return
        lines = self.store.path.read_text(encoding="utf-8").splitlines()
        # Drop the LAST line matching this filename
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i].strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("filename") == filename:
                lines.pop(i)
                break
        self.store.path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        self.store._labelled.discard(filename)
        self.session_committed = max(0, self.session_committed - 1)

    # --- Lifecycle ---------------------------------------------------------

    def _finish(self) -> None:
        elapsed = (datetime.now(timezone.utc) - self.session_started_at).total_seconds()
        print(f"\nLabelled {self.session_committed} images in this session "
              f"({elapsed/60:.1f} min, "
              f"{elapsed/max(1, self.session_committed):.1f}s/img avg)")
        print(f"Labels file: {self.store.path}  "
              f"(total labelled: {len(self.store._labelled)})")
        self.root.destroy()

    def run(self) -> None:
        if not self.queue:
            print("Nothing to label — all candidates are already in the labels file.")
            return
        self.root.mainloop()


def main() -> int:
    args = parse_args()

    db_path = args.cartridge / "photonforge.db"
    candidates = load_candidates(
        db_path=db_path,
        table=args.source_folder,
        source_dir=args.source_dir,
        filter_router_genre=args.filter_router_genre,
    )

    if not candidates:
        print(f"No candidates found in [{args.source_folder}] "
              f"with primary_genre='{args.filter_router_genre}' "
              f"and files present in {args.source_dir}.")
        return 0

    labeler = args.labeler or getpass.getuser() or "anon"
    store = LabelStore(args.output, labeler=labeler)

    print(f"Loaded {len(candidates)} candidates from [{args.source_folder}], "
          f"{sum(1 for c in candidates if not store.is_labelled(c['filename']))} unlabelled.")
    print(f"Existing labels in {args.output}: {len(store._labelled)}")
    if args.filter_router_genre:
        print(f"Filtering to router primary_genre = {args.filter_router_genre!r}")

    app = CorpusLabeller(
        candidates=candidates,
        source_dir=args.source_dir,
        source_folder=args.source_folder,
        store=store,
        include_skipped=args.include_skipped,
        session_limit=args.limit,
    )
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
