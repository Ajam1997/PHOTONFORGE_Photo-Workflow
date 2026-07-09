r"""Corpus labelling tool with clickable genre buttons.

Browse images in a photonforge.db folder and assign a single primary genre
label via buttons or keyboard shortcuts.  Used to build the calibration
corpus for FR-1.7.1.

Example:

    python scripts/label_corpus.py \
        --cartridge H:\ \
        --source-folder TEST_1 \
        --source-dir H:\TEST_1

Labels are appended to the JSONL output file as you commit each image.
You can stop and resume -- already-labelled filenames are skipped on restart.

Keyboard shortcuts (optional -- you can use buttons instead):
    1-9, 0, -, =, \  select genre by position
    SPACE / ENTER     commit selection and advance
    BACKSPACE         clear current selection
    TAB               skip image
    R                 mark as needs_review and advance
    LEFT              go back to previous labelled image
    ESC / Q           quit
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
from tkinter import ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from photo_workflow.genre_router import SUBJECTS, PHOTO_TYPES

WINDOW_W = 1100
WINDOW_H = 980
PREVIEW_H = 520

# Subject keys: 1-6
_SUBJECT_KEYS = ["1", "2", "3", "4", "5", "6"]
# Type keys: q, w, e, r, t, y, u, i
_TYPE_KEYS = ["q", "w", "e", "r", "t", "y", "u", "i"]

from photo_workflow.raw_loader import RAW_EXTENSIONS as RAW_EXTS

_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def slugify(name: str) -> str:
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
    p.add_argument("--filter-router-genre", default="",
                   help="Only label images whose router primary_genre matches this. "
                        "Pass '' (default) to label all images.")
    p.add_argument("--limit", type=int, default=None,
                   help="Stop after labelling N images in this session")
    p.add_argument("--include-skipped", action="store_true",
                   help="Re-prompt for images previously skipped (empty labels)")
    p.add_argument("--relabel", action="store_true",
                   help="Include already-labelled images and pre-load their existing "
                        "genres so you can review and edit.")
    p.add_argument("--labeler", default=None,
                   help="Labeler name recorded in JSONL (default: current user)")
    p.add_argument("--filter-multi-label", action="store_true",
                   help="Only re-present images with more than one genre label. "
                        "Implies --relabel.")
    return p.parse_args()


# --- DB access --------------------------------------------------------------

def load_candidates(
    db_path: Path,
    table: str,
    source_dir: Path,
    filter_router_genre: str,
) -> list[dict]:
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
                if not fname:
                    continue
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


# --- Image loading ----------------------------------------------------------

def load_image_for_preview(path: Path) -> "Image.Image":
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

# Button colors
_BG_NORMAL = "#333"
_BG_HOVER = "#444"
_BG_SUBJ_SELECTED = "#1a6b1a"
_BG_TYPE_SELECTED = "#1a4b6b"
_FG_NORMAL = "#ccc"
_FG_SELECTED = "#fff"

_SUBJECT_KEY_LABELS = ["1", "2", "3", "4", "5", "6"]
_TYPE_KEY_LABELS = ["Q", "W", "E", "R", "T", "Y", "U", "I"]


class CorpusLabeller:
    def __init__(
        self,
        candidates: list[dict],
        source_dir: Path,
        source_folder: str,
        store: LabelStore,
        include_skipped: bool,
        session_limit: int | None,
        relabel: bool = False,
        filter_multi_label: bool = False,
    ) -> None:
        self.candidates = candidates
        self.source_dir = source_dir
        self.source_folder = source_folder
        self.store = store
        self.include_skipped = include_skipped
        self.session_limit = session_limit
        self.relabel = relabel
        self.filter_multi_label = filter_multi_label

        if relabel:
            if filter_multi_label:
                self.queue = [
                    c for c in candidates
                    if (store.current_label(c["filename"]) or {}).get("subject", "general") != "general"
                    and (store.current_label(c["filename"]) or {}).get("photo_type", "general") != "general"
                ]
            else:
                self.queue = list(candidates)
        else:
            self.queue = [c for c in candidates if not store.is_labelled(c["filename"])]
        self.session_started_at = datetime.now(timezone.utc)
        self.session_committed = 0
        self.idx = 0
        self.subject_sel: str | None = None
        self.type_sel: str | None = None
        self.history: list[tuple[int, str | None, str | None, bool]] = []

        self._build_ui()
        self._load_current()

    def _build_ui(self) -> None:
        self.root = tk.Tk()
        self.root.title("PHOTONForge Corpus Labeller")
        self.root.geometry(f"{WINDOW_W}x{WINDOW_H}")
        self.root.resizable(False, False)
        self.root.configure(bg="#1a1a1a")

        # --- Image preview ---
        self.image_label = tk.Label(self.root, bg="#000")
        self.image_label.place(x=0, y=0, width=WINDOW_W, height=PREVIEW_H)

        # --- Info bar ---
        y = PREVIEW_H
        self.info_var = tk.StringVar()
        tk.Label(
            self.root, textvariable=self.info_var, fg="#ddd", bg="#333",
            anchor="w", padx=10, font=("Consolas", 10),
        ).place(x=0, y=y, width=WINDOW_W, height=32)
        y += 32

        # --- Router prediction ---
        self.router_var = tk.StringVar()
        tk.Label(
            self.root, textvariable=self.router_var, fg="#aaa", bg="#2a2a2a",
            anchor="w", padx=10, font=("Consolas", 10),
        ).place(x=0, y=y, width=WINDOW_W, height=26)
        y += 26

        # --- Subject buttons ---
        tk.Label(
            self.root, text="SUBJECT (what)", fg="#8f8", bg="#1a1a1a",
            anchor="w", padx=10, font=("Consolas", 10, "bold"),
        ).place(x=0, y=y + 4, width=WINDOW_W, height=20)
        y += 24

        subj_frame = tk.Frame(self.root, bg="#1a1a1a")
        subj_frame.place(x=10, y=y, width=WINDOW_W - 20, height=46)

        self.subject_buttons: dict[str, tk.Button] = {}
        btn_w = (WINDOW_W - 40) // len(SUBJECTS)
        btn_h = 42

        for i, subj in enumerate(SUBJECTS):
            key_hint = _SUBJECT_KEY_LABELS[i] if i < len(_SUBJECT_KEY_LABELS) else ""
            label = f"[{key_hint}] {subj}" if key_hint else subj
            btn = tk.Button(
                subj_frame, text=label,
                font=("Consolas", 10, "bold"),
                fg=_FG_NORMAL, bg=_BG_NORMAL,
                activeforeground=_FG_SELECTED, activebackground=_BG_SUBJ_SELECTED,
                relief="flat", bd=0, padx=4, pady=2,
                command=lambda s=subj: self._select_subject(s),
            )
            btn.place(x=i * btn_w, y=0, width=btn_w - 4, height=btn_h)
            self.subject_buttons[subj] = btn

        y += 50

        # --- Photo type buttons ---
        tk.Label(
            self.root, text="PHOTO TYPE (how)", fg="#8bf", bg="#1a1a1a",
            anchor="w", padx=10, font=("Consolas", 10, "bold"),
        ).place(x=0, y=y + 2, width=WINDOW_W, height=20)
        y += 22

        type_frame = tk.Frame(self.root, bg="#1a1a1a")
        type_frame.place(x=10, y=y, width=WINDOW_W - 20, height=46)

        self.type_buttons: dict[str, tk.Button] = {}
        btn_w = (WINDOW_W - 40) // len(PHOTO_TYPES)

        for i, ptype in enumerate(PHOTO_TYPES):
            key_hint = _TYPE_KEY_LABELS[i] if i < len(_TYPE_KEY_LABELS) else ""
            label = f"[{key_hint}] {ptype}" if key_hint else ptype
            btn = tk.Button(
                type_frame, text=label,
                font=("Consolas", 10, "bold"),
                fg=_FG_NORMAL, bg=_BG_NORMAL,
                activeforeground=_FG_SELECTED, activebackground=_BG_TYPE_SELECTED,
                relief="flat", bd=0, padx=4, pady=2,
                command=lambda t=ptype: self._select_type(t),
            )
            btn.place(x=i * btn_w, y=0, width=btn_w - 4, height=btn_h)
            self.type_buttons[ptype] = btn

        y += 50

        # --- Custom genre entry ---
        custom_frame = tk.Frame(self.root, bg="#1a1a1a")
        custom_frame.place(x=10, y=y, width=WINDOW_W - 20, height=34)

        tk.Label(
            custom_frame, text="Custom:", fg="#888", bg="#1a1a1a",
            font=("Consolas", 10),
        ).place(x=0, y=4, width=60, height=26)

        self.custom_entry = tk.Entry(
            custom_frame, font=("Consolas", 11), bg="#2a2a2a", fg="#fff",
            insertbackground="#fff",
        )
        self.custom_entry.place(x=65, y=4, width=250, height=26)

        tk.Button(
            custom_frame, text="Apply Subject", font=("Consolas", 10),
            fg="#ccc", bg="#444", relief="flat",
            command=self._apply_custom,
        ).place(x=325, y=4, width=110, height=26)

        self.custom_combo = ttk.Combobox(
            custom_frame, font=("Consolas", 10), state="readonly",
            values=self.store.custom_history(),
        )
        self.custom_combo.place(x=450, y=4, width=200, height=26)
        self.custom_combo.bind("<<ComboboxSelected>>", self._on_custom_combo)

        y += 40

        # --- Selection display ---
        self.selection_var = tk.StringVar()
        tk.Label(
            self.root, textvariable=self.selection_var, fg="#7df", bg="#1a1a1a",
            anchor="w", padx=10, font=("Consolas", 14, "bold"),
        ).place(x=0, y=y, width=WINDOW_W, height=36)
        y += 38

        # --- Action buttons ---
        action_frame = tk.Frame(self.root, bg="#1a1a1a")
        action_frame.place(x=10, y=y, width=WINDOW_W - 20, height=44)

        buttons = [
            ("Commit [Space]", "#1a6b1a", self._commit_current),
            ("Skip [Tab]", "#555", self._skip_current),
            ("Needs Review [R]", "#6b5b1a", self._review_current),
            ("Back [<-]", "#444", self._go_back),
            ("Quit [Esc]", "#6b1a1a", self._quit),
        ]
        btn_x = 0
        btn_widths = [160, 120, 170, 120, 100]
        for (label, bg, cmd), w in zip(buttons, btn_widths):
            tk.Button(
                action_frame, text=label, font=("Consolas", 10, "bold"),
                fg="#fff", bg=bg, activebackground=bg, relief="flat",
                command=cmd,
            ).place(x=btn_x, y=2, width=w, height=38)
            btn_x += w + 8
        y += 48

        # --- Progress bar ---
        self.progress_var = tk.StringVar()
        tk.Label(
            self.root, textvariable=self.progress_var, fg="#888", bg="#1a1a1a",
            anchor="w", padx=10, font=("Consolas", 9),
        ).place(x=0, y=y, width=WINDOW_W, height=24)

        self.root.bind("<KeyPress>", self._on_key)

    # --- Selection ---

    def _select_subject(self, subj: str) -> None:
        self.subject_sel = subj
        self._update_button_highlights()
        self._update_selection_display()

    def _select_type(self, ptype: str) -> None:
        self.type_sel = ptype
        self._update_button_highlights()
        self._update_selection_display()

    def _update_button_highlights(self) -> None:
        for s, btn in self.subject_buttons.items():
            if s == self.subject_sel:
                btn.configure(bg=_BG_SUBJ_SELECTED, fg=_FG_SELECTED)
            else:
                btn.configure(bg=_BG_NORMAL, fg=_FG_NORMAL)
        for t, btn in self.type_buttons.items():
            if t == self.type_sel:
                btn.configure(bg=_BG_TYPE_SELECTED, fg=_FG_SELECTED)
            else:
                btn.configure(bg=_BG_NORMAL, fg=_FG_NORMAL)

    def _update_selection_display(self) -> None:
        parts = []
        if self.subject_sel:
            parts.append(f"Subject: {self.subject_sel}")
        if self.type_sel:
            parts.append(f"Type: {self.type_sel}")
        if parts:
            self.selection_var.set("  |  ".join(parts))
        else:
            self.selection_var.set("(no selection)")

    def _apply_custom(self) -> None:
        typed = self.custom_entry.get().strip()
        if typed:
            slug = slugify(typed)
            if slug:
                self.store.record_custom(slug)
                self.custom_combo["values"] = self.store.custom_history()
                self.subject_sel = slug
                self.custom_entry.delete(0, "end")
                self._update_button_highlights()
                self._update_selection_display()

    def _on_custom_combo(self, _evt: object = None) -> None:
        val = self.custom_combo.get()
        if val:
            self.subject_sel = val
            self._update_button_highlights()
            self._update_selection_display()

    # --- State ---

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
            self.image_label.configure(
                text=f"<could not load {path.name}: {e}>", image="", fg="#f88",
            )
            self._render_info()
            return

        from PIL import ImageTk

        img.thumbnail((WINDOW_W, PREVIEW_H))
        self.tk_img = ImageTk.PhotoImage(img)
        self.image_label.configure(image=self.tk_img, text="")

        existing = self.store.current_label(cur["filename"])
        if self.relabel and existing:
            self.subject_sel = existing.get("subject")
            self.type_sel = existing.get("photo_type")
            if self.subject_sel == "general":
                self.subject_sel = None
            if self.type_sel == "general":
                self.type_sel = None
        else:
            self.subject_sel = None
            self.type_sel = None
        self._update_button_highlights()
        self._update_selection_display()
        self._render_info()

    def _render_info(self) -> None:
        cur = self._current()
        if cur is None:
            return
        path = self.source_dir / cur["filename"]
        exif = read_exif_summary(path)
        self.info_var.set(f"{cur['filename']}    {exif}")

        try:
            genre_data = json.loads(cur["genres"]) if cur["genres"] else {}
        except (TypeError, json.JSONDecodeError):
            genre_data = {}

        if isinstance(genre_data, dict) and "subject" in genre_data:
            router_summary = (
                f"subj={genre_data.get('subject', '?')} "
                f"({genre_data.get('subject_confidence', 0):.2f})  "
                f"type={genre_data.get('photo_type', '?')} "
                f"({genre_data.get('type_confidence', 0):.2f})"
            )
        elif isinstance(genre_data, list):
            router_summary = ", ".join(
                f"{g.get('g', '?')}({g.get('c', 0):.2f})" for g in genre_data
            ) or "(no genres)"
        else:
            router_summary = cur.get("primary_genre") or "(none)"

        nr = " * needs_review" if cur["needs_review"] else ""
        prev = ""
        if self.relabel:
            existing = self.store.current_label(cur["filename"])
            if existing:
                ps = existing.get("subject") or "general"
                pt = existing.get("photo_type") or "general"
                prev = f"    previous: {ps}/{pt}"
        self.router_var.set(f"router: {router_summary}{nr}{prev}")

        done = self.session_committed
        total_session = self.session_limit or len(self.queue)
        remaining = max(0, total_session - done)
        elapsed = (datetime.now(timezone.utc) - self.session_started_at).total_seconds()
        per_item = (elapsed / done) if done else 0.0
        eta = f"{(per_item * remaining) / 60:.1f} min" if per_item > 0 else "-"
        self.progress_var.set(
            f"{done}/{total_session} this session    "
            f"avg {per_item:.1f}s/img    eta {eta}    "
            f"queue position {self.idx + 1}/{len(self.queue)}"
        )

    # --- Key handler ---

    def _on_key(self, event: tk.Event) -> None:
        if self.custom_entry == self.root.focus_get():
            if event.keysym == "Return":
                self._apply_custom()
            return

        cur = self._current()
        if cur is None:
            return

        key = event.keysym.lower()

        if key in ("escape",):
            self._quit()
            return
        if key == "tab":
            self._skip_current()
            return
        if key == "r":
            self._review_current()
            return
        if key in ("space", "return"):
            self._commit_current()
            return
        if key == "backspace":
            self.subject_sel = None
            self.type_sel = None
            self._update_button_highlights()
            self._update_selection_display()
            return
        if key == "left":
            self._go_back()
            return

        # Number keys 1-6 select subject
        if key in _SUBJECT_KEYS:
            idx = _SUBJECT_KEYS.index(key)
            if idx < len(SUBJECTS):
                self._select_subject(SUBJECTS[idx])
            return

        # Letter keys q,w,e,r,t,y,u,i select photo type
        if key in _TYPE_KEYS:
            idx = _TYPE_KEYS.index(key)
            if idx < len(PHOTO_TYPES):
                self._select_type(PHOTO_TYPES[idx])
            return

    # --- Actions ---

    def _commit_current(self) -> None:
        if not self.subject_sel:
            return
        cur = self._current()
        if cur is None:
            return
        self.history.append((self.idx, self.subject_sel, self.type_sel, False))
        self.store.commit(
            filename=cur["filename"],
            subject=self.subject_sel,
            photo_type=self.type_sel or "general",
            source_folder=self.source_folder,
            needs_review=False,
        )
        self.session_committed += 1
        if self.session_limit and self.session_committed >= self.session_limit:
            self._finish()
            return
        self.idx += 1
        self._load_current()

    def _skip_current(self) -> None:
        cur = self._current()
        if cur is None:
            return
        self.history.append((self.idx, self.subject_sel, self.type_sel, False))
        self.store.commit(
            filename=cur["filename"],
            subject="",
            photo_type="",
            source_folder=self.source_folder,
            needs_review=False,
        )
        self.session_committed += 1
        if self.session_limit and self.session_committed >= self.session_limit:
            self._finish()
            return
        self.idx += 1
        self._load_current()

    def _review_current(self) -> None:
        cur = self._current()
        if cur is None:
            return
        self.history.append((self.idx, self.subject_sel, self.type_sel, True))
        self.store.commit(
            filename=cur["filename"],
            subject=self.subject_sel or "",
            photo_type=self.type_sel or "",
            source_folder=self.source_folder,
            needs_review=True,
        )
        self.session_committed += 1
        if self.session_limit and self.session_committed >= self.session_limit:
            self._finish()
            return
        self.idx += 1
        self._load_current()

    def _go_back(self) -> None:
        if self.idx == 0 or not self.history:
            return
        prev_idx, prev_subj, prev_type, _ = self.history.pop()
        self._rewind_label(self.queue[prev_idx]["filename"])
        self.idx = prev_idx
        self.subject_sel = prev_subj
        self.type_sel = prev_type
        self._update_button_highlights()
        self._update_selection_display()
        self._load_current()

    def _rewind_label(self, filename: str) -> None:
        if not self.store.path.exists():
            return
        lines = self.store.path.read_text(encoding="utf-8").splitlines()
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

    def _quit(self) -> None:
        self.root.destroy()

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
            print("Nothing to label -- all candidates are already in the labels file.")
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

    do_relabel = args.relabel or args.filter_multi_label

    unlabelled = sum(1 for c in candidates if not store.is_labelled(c["filename"]))
    print(f"Loaded {len(candidates)} candidates from [{args.source_folder}], "
          f"{unlabelled} unlabelled, "
          f"{len(candidates) - unlabelled} already labelled.")
    print(f"Existing labels in {args.output}: {len(store._labelled)}")
    if args.filter_router_genre:
        print(f"Filtering to router primary_genre = {args.filter_router_genre!r}")
    if do_relabel:
        print("--relabel: already-labelled images will be re-presented.")
    if args.filter_multi_label:
        multi = sum(
            1 for c in candidates
            if (store.current_label(c["filename"]) or {}).get("subject", "general") != "general"
            and (store.current_label(c["filename"]) or {}).get("photo_type", "general") != "general"
        )
        print(f"--filter-multi-label: {multi} image(s) with both axes set to review.")
    history = store.custom_history()
    if history:
        print(f"Custom genres in use: {', '.join(history)}")

    app = CorpusLabeller(
        candidates=candidates,
        source_dir=args.source_dir,
        source_folder=args.source_folder,
        store=store,
        include_skipped=args.include_skipped,
        session_limit=args.limit,
        relabel=do_relabel,
        filter_multi_label=args.filter_multi_label,
    )
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
