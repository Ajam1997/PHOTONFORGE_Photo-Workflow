"""Genre labeler tab — two-axis corpus labeling integrated into the Cartridge Manager.

Provides image preview with subject/photo-type button grids, keyboard shortcuts,
custom genre entry, and JSONL corpus output. Reuses the same corpus format as
scripts/label_corpus.py so corpora are interchangeable.

Keyboard shortcuts:
    Subject row 1:  1,2,3,4,5,6,7,8
    Subject row 2:  A,S,D,F,G,H,J,K
    Photo type:     Q,W,E,R,T,Y,U,I,O,P,Z,X
    Space/Enter     commit label and advance
    Backspace       clear selection
    Tab             skip image (not written to corpus)
    Ctrl+R          mark needs_review and advance
    Left            go back one image
    Escape          stop session early
"""

from __future__ import annotations

import getpass
import json
import re
import sqlite3
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from photo_workflow.genre_router import SUBJECTS, PHOTO_TYPES

from .app import TabPlugin

# -- Constants ----------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9-]+")

RAW_EXTS = {
    ".arw", ".cr2", ".cr3", ".nef", ".dng", ".raf", ".rw2", ".orf",
    ".pef", ".srw", ".3fr", ".mef",
}

IMAGE_EXTS = RAW_EXTS | {".jpg", ".jpeg", ".tif", ".tiff", ".png"}

_SUBJECT_KEYS_ROW1 = ["1", "2", "3", "4", "5", "6", "7", "8"]
_SUBJECT_KEYS_ROW2 = ["a", "s", "d", "f", "g", "h", "j", "k"]
_SUBJECT_KEYS = _SUBJECT_KEYS_ROW1 + _SUBJECT_KEYS_ROW2
_SUBJECT_KEY_LABELS = ["1", "2", "3", "4", "5", "6", "7", "8",
                        "A", "S", "D", "F", "G", "H", "J", "K"]
_TYPE_KEYS = ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p", "z", "x"]
_TYPE_KEY_LABELS = ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P", "Z", "X"]

_BG_NORMAL = "#333"
_BG_SUBJ_SELECTED = "#1a6b1a"
_BG_TYPE_SELECTED = "#1a4b6b"
_FG_NORMAL = "#ccc"
_FG_SELECTED = "#fff"


def _slugify(name: str) -> str:
    s = name.strip().lower().replace(" ", "-")
    s = _SLUG_RE.sub("-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


# -- Label persistence (same JSONL format as scripts/label_corpus.py) ---------


class LabelStore:
    """Read/write corpus labels in JSONL format, compatible with label_corpus.py."""

    def __init__(self, path: Path, labeler: str) -> None:
        self.path = path
        self.labeler = labeler
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._labelled: set[str] = set()
        self._current: dict[str, dict] = {}
        self._custom_history: list[str] = []
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
                fname = rec.get("filename")
                if fname:
                    self._labelled.add(fname)
                    self._current[fname] = rec

    def is_labelled(self, filename: str) -> bool:
        return filename in self._labelled

    def current_label(self, filename: str) -> dict | None:
        return self._current.get(filename)

    def custom_history(self) -> list[str]:
        return list(self._custom_history)

    def record_custom(self, genre: str) -> None:
        if genre in self._custom_history:
            self._custom_history.remove(genre)
        self._custom_history.insert(0, genre)

    def commit(
        self,
        filename: str,
        subject: str,
        photo_type: str,
        source_folder: str,
        needs_review: bool,
    ) -> None:
        rec = {
            "filename": filename,
            "subject": subject,
            "photo_type": photo_type,
            "source_folder": source_folder,
            "needs_review": needs_review,
            "labeled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "labeler": self.labeler,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        self._labelled.add(filename)
        self._current[filename] = rec

    def rewind(self, filename: str) -> None:
        """Remove the last label for filename from the JSONL file."""
        if not self.path.exists():
            return
        lines = self.path.read_text(encoding="utf-8").splitlines()
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
        self.path.write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
        )
        self._labelled.discard(filename)
        self._current.pop(filename, None)


# -- Image loading ------------------------------------------------------------


def _load_image_for_preview(path: Path, max_height: int = 400):
    """Load a photo for Tk display. Returns a PIL Image or None."""
    try:
        from PIL import Image

        if path.suffix.lower() in RAW_EXTS:
            import rawpy
            with rawpy.imread(str(path)) as raw:
                arr = raw.postprocess(
                    half_size=True, no_auto_bright=False,
                    use_camera_wb=True, output_bps=8,
                )
            img = Image.fromarray(arr)
        else:
            img = Image.open(path)

        img.thumbnail((img.width, max_height))
        return img
    except Exception:
        return None


def _read_exif_summary(path: Path) -> str:
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


# -- Labeler Tab --------------------------------------------------------------


class LabelerTab(TabPlugin):
    """Genre labeling tab — browse photos and assign subject/photo_type labels."""

    label = "Labeler"

    def __init__(self, parent: tk.Widget, app):
        super().__init__(parent, app)
        self._conn: sqlite3.Connection | None = None
        self._store: LabelStore | None = None
        self._candidates: list[dict] = []
        self._queue: list[dict] = []
        self._idx = 0
        self._subject_sel: str | None = None
        self._type_sel: str | None = None
        self._history: list[tuple[int, str | None, str | None]] = []
        self._session_committed = 0
        self._session_skipped = 0
        self._session_start = datetime.now(timezone.utc)
        self._tk_img = None  # prevent GC

        self._build_ui()

    def _build_ui(self) -> None:
        # ttk.Frame uses styles, not bg — apply a dark style
        style = ttk.Style()
        style.configure("Dark.TFrame", background="#1a1a1a")
        self.configure(style="Dark.TFrame")

        # ── Config bar ──
        config = ttk.LabelFrame(self, text="Labeler Config")
        config.pack(fill="x", padx=4, pady=4)

        row0 = ttk.Frame(config)
        row0.pack(fill="x", padx=4, pady=2)

        ttk.Label(row0, text="Folder:").pack(side="left")
        self._folder_var = tk.StringVar()
        self._folder_combo = ttk.Combobox(
            row0, textvariable=self._folder_var, width=20, state="readonly"
        )
        self._folder_combo.pack(side="left", padx=4)

        ttk.Label(row0, text="Corpus:").pack(side="left", padx=(12, 0))
        self._corpus_var = tk.StringVar(value="corpus/genre_labels.jsonl")
        ttk.Entry(row0, textvariable=self._corpus_var, width=30).pack(
            side="left", padx=4
        )
        ttk.Button(row0, text="...", width=3, command=self._browse_corpus).pack(
            side="left"
        )

        ttk.Label(row0, text="Labeler:").pack(side="left", padx=(12, 0))
        self._labeler_var = tk.StringVar(value=getpass.getuser() or "anon")
        ttk.Entry(row0, textvariable=self._labeler_var, width=12).pack(
            side="left", padx=4
        )

        row1 = ttk.Frame(config)
        row1.pack(fill="x", padx=4, pady=2)

        self._relabel_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row1, text="Re-label existing", variable=self._relabel_var).pack(
            side="left"
        )

        self._skip_dupes_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row1, text="Skip duplicates", variable=self._skip_dupes_var).pack(
            side="left", padx=12
        )

        self._filter_genre_var = tk.StringVar(value="")
        ttk.Label(row1, text="Filter genre:").pack(side="left", padx=(12, 0))
        ttk.Entry(row1, textvariable=self._filter_genre_var, width=12).pack(
            side="left", padx=4
        )

        ttk.Button(row1, text="Start Labeling", command=self._start_session).pack(
            side="right", padx=4
        )

        # ── Image preview ──
        self._preview_frame = tk.Frame(self, bg="#000")
        self._preview_frame.pack(fill="both", expand=True, padx=4, pady=2)

        self._image_label = tk.Label(self._preview_frame, bg="#000", anchor="center")
        self._image_label.pack(fill="both", expand=True)

        # ── Info bar ──
        self._info_var = tk.StringVar(value="Select a folder and click Start Labeling")
        tk.Label(
            self, textvariable=self._info_var, fg="#ddd", bg="#333",
            anchor="w", padx=10, font=("Consolas", 10),
        ).pack(fill="x")

        self._router_var = tk.StringVar()
        tk.Label(
            self, textvariable=self._router_var, fg="#aaa", bg="#2a2a2a",
            anchor="w", padx=10, font=("Consolas", 10),
        ).pack(fill="x")

        # ── Subject buttons (two rows of 8) ──
        tk.Label(
            self, text="SUBJECT (what)", fg="#8f8", bg="#1a1a1a",
            anchor="w", padx=10, font=("Consolas", 10, "bold"),
        ).pack(fill="x")

        self._subject_buttons: dict[str, tk.Button] = {}
        per_row = 8
        for row_start in range(0, len(SUBJECTS), per_row):
            row_frame = tk.Frame(self, bg="#1a1a1a")
            row_frame.pack(fill="x", padx=8, pady=1)
            for i in range(row_start, min(row_start + per_row, len(SUBJECTS))):
                subj = SUBJECTS[i]
                key = _SUBJECT_KEY_LABELS[i] if i < len(_SUBJECT_KEY_LABELS) else ""
                text = f"[{key}] {subj}" if key else subj
                btn = tk.Button(
                    row_frame, text=text, font=("Consolas", 9, "bold"),
                    fg=_FG_NORMAL, bg=_BG_NORMAL,
                    activeforeground=_FG_SELECTED, activebackground=_BG_SUBJ_SELECTED,
                    relief="flat", bd=0, padx=4, pady=3,
                    command=lambda s=subj: self._select_subject(s),
                )
                btn.pack(side="left", expand=True, fill="x", padx=1)
                self._subject_buttons[subj] = btn

        # ── Photo type buttons (two rows of 6) ──
        tk.Label(
            self, text="PHOTO TYPE (how)", fg="#8bf", bg="#1a1a1a",
            anchor="w", padx=10, font=("Consolas", 10, "bold"),
        ).pack(fill="x")

        self._type_buttons: dict[str, tk.Button] = {}
        type_per_row = 6
        for row_start in range(0, len(PHOTO_TYPES), type_per_row):
            row_frame = tk.Frame(self, bg="#1a1a1a")
            row_frame.pack(fill="x", padx=8, pady=1)
            for i in range(row_start, min(row_start + type_per_row, len(PHOTO_TYPES))):
                ptype = PHOTO_TYPES[i]
                key = _TYPE_KEY_LABELS[i] if i < len(_TYPE_KEY_LABELS) else ""
                text = f"[{key}] {ptype}" if key else ptype
                btn = tk.Button(
                    row_frame, text=text, font=("Consolas", 9, "bold"),
                    fg=_FG_NORMAL, bg=_BG_NORMAL,
                    activeforeground=_FG_SELECTED, activebackground=_BG_TYPE_SELECTED,
                    relief="flat", bd=0, padx=4, pady=3,
                    command=lambda t=ptype: self._select_type(t),
                )
                btn.pack(side="left", expand=True, fill="x", padx=1)
                self._type_buttons[ptype] = btn

        # ── Custom genre entry ──
        custom_frame = tk.Frame(self, bg="#1a1a1a")
        custom_frame.pack(fill="x", padx=8, pady=2)

        tk.Label(custom_frame, text="Custom:", fg="#888", bg="#1a1a1a",
                 font=("Consolas", 10)).pack(side="left")
        self._custom_entry = tk.Entry(
            custom_frame, font=("Consolas", 11), bg="#2a2a2a", fg="#fff",
            insertbackground="#fff", width=20,
        )
        self._custom_entry.pack(side="left", padx=4)
        tk.Button(
            custom_frame, text="Apply Subject", font=("Consolas", 10),
            fg="#ccc", bg="#444", relief="flat", command=self._apply_custom,
        ).pack(side="left", padx=2)

        self._custom_combo = ttk.Combobox(
            custom_frame, font=("Consolas", 10), state="readonly", width=16,
        )
        self._custom_combo.pack(side="left", padx=4)
        self._custom_combo.bind("<<ComboboxSelected>>", self._on_custom_combo)

        # ── Selection display ──
        self._selection_var = tk.StringVar(value="(no selection)")
        tk.Label(
            self, textvariable=self._selection_var, fg="#7df", bg="#1a1a1a",
            anchor="w", padx=10, font=("Consolas", 12, "bold"),
        ).pack(fill="x")

        # ── Action buttons ──
        action_frame = tk.Frame(self, bg="#1a1a1a")
        action_frame.pack(fill="x", padx=8, pady=4)

        for text, bg, cmd in [
            ("Commit [Space]", "#1a6b1a", self._commit),
            ("Skip [Tab]", "#555", self._skip),
            ("Review [Ctrl+R]", "#6b5b1a", self._review),
            ("Back [<-]", "#444", self._go_back),
            ("Stop [Esc]", "#6b1a1a", self._stop_session),
        ]:
            tk.Button(
                action_frame, text=text, font=("Consolas", 10, "bold"),
                fg="#fff", bg=bg, activebackground=bg, relief="flat",
                padx=8, pady=4, command=cmd,
            ).pack(side="left", padx=2)

        # ── Progress ──
        self._progress_var = tk.StringVar()
        tk.Label(
            self, textvariable=self._progress_var, fg="#888", bg="#1a1a1a",
            anchor="w", padx=10, font=("Consolas", 9),
        ).pack(fill="x")

    # ── Cartridge changed ──

    def on_cartridge_changed(self, root: Path) -> None:
        if self._conn:
            self._conn.close()
        try:
            db_path = root / "photonforge.db"
            self._conn = sqlite3.connect(str(db_path))
            self._conn.row_factory = sqlite3.Row
            tables = [
                r[0] for r in self._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
            self._folder_combo.configure(values=tables)
            if tables:
                self._folder_var.set(tables[0])
        except Exception as e:
            messagebox.showerror("DB Error", str(e))

    def on_activated(self) -> None:
        self.focus_set()
        self.bind_all("<KeyPress>", self._on_key)

    def _browse_corpus(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Corpus JSONL file",
            defaultextension=".jsonl",
            filetypes=[("JSONL", "*.jsonl"), ("All", "*.*")],
        )
        if path:
            self._corpus_var.set(path)

    # ── Session management ──

    def _start_session(self) -> None:
        root = self.app.cartridge_root
        if not root or not self._conn:
            messagebox.showwarning("No Cartridge", "Select a cartridge first.")
            return

        folder = self._folder_var.get()
        if not folder:
            messagebox.showwarning("No Folder", "Select a source folder.")
            return

        corpus_path = Path(self._corpus_var.get())
        if not corpus_path.is_absolute():
            corpus_path = Path(__file__).resolve().parent.parent.parent / corpus_path

        self._store = LabelStore(corpus_path, labeler=self._labeler_var.get())
        self._custom_combo.configure(values=self._store.custom_history())

        source_dir = root / folder
        filter_genre = self._filter_genre_var.get().strip()

        try:
            rows = self._conn.execute(
                f"SELECT filename, original_name, primary_genre, genre_confidence, "
                f"genres, needs_review, exif_timestamp, is_duplicate "
                f"FROM [{folder}]"
            ).fetchall()
        except sqlite3.OperationalError as e:
            messagebox.showerror("Query Error", str(e))
            return

        self._candidates = []
        for r in rows:
            if not (source_dir / r["filename"]).is_file():
                continue
            if self._skip_dupes_var.get() and r["is_duplicate"]:
                continue
            if filter_genre and (r["primary_genre"] or "") != filter_genre:
                continue
            self._candidates.append(dict(r))

        relabel = self._relabel_var.get()
        if relabel:
            self._queue = list(self._candidates)
        else:
            self._queue = [
                c for c in self._candidates
                if not self._store.is_labelled(c["filename"])
            ]

        if not self._queue:
            messagebox.showinfo(
                "Nothing to Label",
                f"All {len(self._candidates)} photos in '{folder}' are already labelled.\n"
                "Enable 'Re-label existing' to review them.",
            )
            return

        self._idx = 0
        self._history.clear()
        self._session_committed = 0
        self._session_skipped = 0
        self._session_start = datetime.now(timezone.utc)
        self._source_dir = source_dir
        self._source_folder = folder

        self.app.status.set_status(
            f"Labeling {len(self._queue)} photos from '{folder}'"
        )
        self._load_current()

    # ── Navigation ──

    def _current_item(self) -> dict | None:
        if 0 <= self._idx < len(self._queue):
            return self._queue[self._idx]
        return None

    def _load_current(self) -> None:
        cur = self._current_item()
        if cur is None:
            self._finish_session()
            return

        path = self._source_dir / cur["filename"]
        img = _load_image_for_preview(path, max_height=400)

        if img is not None:
            try:
                from PIL import ImageTk
                self._tk_img = ImageTk.PhotoImage(img)
                self._image_label.configure(image=self._tk_img, text="")
            except Exception:
                self._image_label.configure(
                    image="", text=f"<preview failed: {path.name}>", fg="#f88"
                )
        else:
            self._image_label.configure(
                image="", text=f"<could not load: {path.name}>", fg="#f88"
            )

        # Pre-load existing label if re-labeling
        if self._relabel_var.get() and self._store:
            existing = self._store.current_label(cur["filename"])
            if existing:
                self._subject_sel = existing.get("subject")
                self._type_sel = existing.get("photo_type")
                if self._subject_sel == "general":
                    self._subject_sel = None
                if self._type_sel == "general":
                    self._type_sel = None
            else:
                self._subject_sel = None
                self._type_sel = None
        else:
            self._subject_sel = None
            self._type_sel = None

        self._update_highlights()
        self._update_selection()
        self._render_info()

    def _render_info(self) -> None:
        cur = self._current_item()
        if cur is None:
            return

        path = self._source_dir / cur["filename"]
        exif = _read_exif_summary(path)
        self._info_var.set(f"{cur['filename']}    {exif}")

        # Router prediction
        try:
            genre_data = json.loads(cur["genres"]) if cur["genres"] else {}
        except (TypeError, json.JSONDecodeError):
            genre_data = {}

        if isinstance(genre_data, dict) and "subject" in genre_data:
            router = (
                f"subj={genre_data.get('subject', '?')} "
                f"({genre_data.get('subject_confidence', 0):.2f})  "
                f"type={genre_data.get('photo_type', '?')} "
                f"({genre_data.get('type_confidence', 0):.2f})"
            )
        else:
            router = cur.get("primary_genre") or "(none)"

        nr = " * needs_review" if cur.get("needs_review") else ""
        prev = ""
        if self._relabel_var.get() and self._store:
            existing = self._store.current_label(cur["filename"])
            if existing:
                ps = existing.get("subject") or "general"
                pt = existing.get("photo_type") or "general"
                prev = f"    previous: {ps}/{pt}"

        self._router_var.set(f"router: {router}{nr}{prev}")

        # Progress
        done = self._session_committed
        skipped = self._session_skipped
        total = len(self._queue)
        elapsed = (datetime.now(timezone.utc) - self._session_start).total_seconds()
        processed = done + skipped
        per_item = (elapsed / processed) if processed else 0.0
        remaining = max(0, total - self._idx)
        eta = f"{(per_item * remaining) / 60:.1f}min" if per_item > 0 else "-"
        self._progress_var.set(
            f"{done} labelled  {skipped} skipped  |  "
            f"avg {per_item:.1f}s/img  eta {eta}  |  "
            f"position {self._idx + 1}/{total}"
        )

    # ── Selection ──

    def _select_subject(self, subj: str) -> None:
        self._subject_sel = subj
        self._update_highlights()
        self._update_selection()

    def _select_type(self, ptype: str) -> None:
        self._type_sel = ptype
        self._update_highlights()
        self._update_selection()

    def _update_highlights(self) -> None:
        for s, btn in self._subject_buttons.items():
            if s == self._subject_sel:
                btn.configure(bg=_BG_SUBJ_SELECTED, fg=_FG_SELECTED)
            else:
                btn.configure(bg=_BG_NORMAL, fg=_FG_NORMAL)
        for t, btn in self._type_buttons.items():
            if t == self._type_sel:
                btn.configure(bg=_BG_TYPE_SELECTED, fg=_FG_SELECTED)
            else:
                btn.configure(bg=_BG_NORMAL, fg=_FG_NORMAL)

    def _update_selection(self) -> None:
        parts = []
        if self._subject_sel:
            parts.append(f"Subject: {self._subject_sel}")
        if self._type_sel:
            parts.append(f"Type: {self._type_sel}")
        self._selection_var.set("  |  ".join(parts) if parts else "(no selection)")

    def _apply_custom(self) -> None:
        typed = self._custom_entry.get().strip()
        if typed and self._store:
            slug = _slugify(typed)
            if slug:
                self._store.record_custom(slug)
                self._custom_combo.configure(values=self._store.custom_history())
                self._subject_sel = slug
                self._custom_entry.delete(0, "end")
                self._update_highlights()
                self._update_selection()

    def _on_custom_combo(self, _evt=None) -> None:
        val = self._custom_combo.get()
        if val:
            self._subject_sel = val
            self._update_highlights()
            self._update_selection()

    # ── Keyboard ──

    def _on_key(self, event: tk.Event) -> None:
        # Don't intercept when typing in entry widgets
        focus = self.winfo_toplevel().focus_get()
        if isinstance(focus, (tk.Entry, ttk.Entry, ttk.Combobox)):
            if event.keysym == "Return" and focus == self._custom_entry:
                self._apply_custom()
            return

        if not self._queue or self._current_item() is None:
            return

        key = event.keysym.lower()

        if key == "escape":
            self._stop_session()
            return "break"
        if key == "tab":
            self._skip()
            return "break"
        if key == "r" and (event.state & 0x4):  # Ctrl+R
            self._review()
            return "break"
        if key in ("space", "return"):
            self._commit()
            return "break"
        if key == "backspace":
            self._subject_sel = None
            self._type_sel = None
            self._update_highlights()
            self._update_selection()
            return "break"
        if key == "left":
            self._go_back()
            return "break"

        if key in _SUBJECT_KEYS:
            idx = _SUBJECT_KEYS.index(key)
            if idx < len(SUBJECTS):
                self._select_subject(SUBJECTS[idx])
            return "break"

        if key in _TYPE_KEYS:
            idx = _TYPE_KEYS.index(key)
            if idx < len(PHOTO_TYPES):
                self._select_type(PHOTO_TYPES[idx])
            return "break"

    # ── Actions ──

    def _commit(self) -> None:
        if not self._subject_sel or not self._store:
            return
        cur = self._current_item()
        if cur is None:
            return

        self._history.append((self._idx, self._subject_sel, self._type_sel))
        self._store.commit(
            filename=cur["filename"],
            subject=self._subject_sel,
            photo_type=self._type_sel or "general",
            source_folder=self._source_folder,
            needs_review=False,
        )
        self._session_committed += 1
        self._idx += 1
        self._load_current()

    def _skip(self) -> None:
        """Advance to the next photo without writing anything to the corpus."""
        if not self._store:
            return
        cur = self._current_item()
        if cur is None:
            return

        self._history.append((self._idx, self._subject_sel, self._type_sel))
        self._session_skipped += 1
        self._idx += 1
        self._load_current()

    def _review(self) -> None:
        if not self._store:
            return
        cur = self._current_item()
        if cur is None:
            return

        self._history.append((self._idx, self._subject_sel, self._type_sel))
        self._store.commit(
            filename=cur["filename"],
            subject=self._subject_sel or "",
            photo_type=self._type_sel or "",
            source_folder=self._source_folder,
            needs_review=True,
        )
        self._session_committed += 1
        self._idx += 1
        self._load_current()

    def _go_back(self) -> None:
        if not self._history or not self._store:
            return
        prev_idx, prev_subj, prev_type = self._history.pop()
        prev_filename = self._queue[prev_idx]["filename"]
        # Only rewind from corpus if the photo was actually committed (not skipped)
        if self._store.is_labelled(prev_filename):
            self._store.rewind(prev_filename)
            self._session_committed = max(0, self._session_committed - 1)
        else:
            self._session_skipped = max(0, self._session_skipped - 1)
        self._idx = prev_idx
        self._subject_sel = prev_subj
        self._type_sel = prev_type
        self._update_highlights()
        self._update_selection()
        self._load_current()

    def _stop_session(self) -> None:
        """Stop labeling early — corpus keeps only photos actually labeled."""
        if not self._queue:
            return
        remaining = len(self._queue) - self._idx
        if remaining > 0:
            if not messagebox.askyesno(
                "Stop Session",
                f"Stop labeling? {self._session_committed} labeled, "
                f"{self._session_skipped} skipped, {remaining} remaining.\n\n"
                f"The corpus will contain only the {self._session_committed} "
                f"photos you labeled.",
            ):
                return
        self._finish_session()

    def _finish_session(self) -> None:
        elapsed = (datetime.now(timezone.utc) - self._session_start).total_seconds()
        avg = elapsed / max(1, self._session_committed)
        self._image_label.configure(image="", text="Session complete", fg="#8f8")
        self._info_var.set(
            f"Labelled {self._session_committed}, skipped {self._session_skipped} "
            f"in {elapsed/60:.1f}min ({avg:.1f}s/img)"
        )
        self._router_var.set("")
        self._progress_var.set("")
        self.app.status.set_status(
            f"Labeling complete: {self._session_committed} labeled, "
            f"{self._session_skipped} skipped"
        )
        if self._store:
            corpus_path = self._store.path
            total = len(self._store._labelled)
            messagebox.showinfo(
                "Session Complete",
                f"Labelled {self._session_committed} images.\n"
                f"Skipped {self._session_skipped} images (not in corpus).\n"
                f"Total in corpus: {total}\n"
                f"Corpus file: {corpus_path}",
            )
        self._queue = []
