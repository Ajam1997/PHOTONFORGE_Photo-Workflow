"""Photo scoring/previewing tab.

Browse photos on a cartridge, view thumbnails (including RAW via rawpy),
and inspect the full scoring breakdown for each photo (master score,
per-axis sub-scores, sharpness/composition/exposure, genre distribution,
hard-reject gates, star rating, color label).

Used for calibration: developers can spot-check what the pipeline assigned
to a given image vs. what the image visually looks like.
"""

from __future__ import annotations

import json
import sqlite3
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from . import db_ops
from .app import TabPlugin


_RAW_EXTS = {
    ".arw", ".cr2", ".cr3", ".nef", ".dng", ".raf", ".rw2", ".orf",
    ".pef", ".srw", ".3fr", ".mef",
}


def _load_image_for_preview(path: Path, max_height: int = 400):
    """Load a photo for Tk display. Returns a PIL Image or None.

    Handles RAW files via rawpy; falls back to PIL for everything else.
    """
    try:
        from PIL import Image
        if path.suffix.lower() in _RAW_EXTS:
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


# Columns shown in the photo list (left pane).
_LIST_COLUMNS = (
    "filename",
    "master_score",
    "primary_genre",
    "genre_confidence",
    "sharpness",
    "composition",
    "exposure",
    "needs_review",
    "is_duplicate",
)
_LIST_LABELS = {
    "filename": "Filename",
    "master_score": "Score",
    "primary_genre": "Genre",
    "genre_confidence": "Conf",
    "sharpness": "Sharp",
    "composition": "Comp",
    "exposure": "Expo",
    "needs_review": "Rev",
    "is_duplicate": "Dup",
}
_LIST_WIDTHS = {
    "filename": 200,
    "master_score": 60,
    "primary_genre": 100,
    "genre_confidence": 55,
    "sharpness": 60,
    "composition": 60,
    "exposure": 60,
    "needs_review": 40,
    "is_duplicate": 40,
}


def _fmt_float(val, places: int = 3) -> str:
    if val is None or val == "":
        return ""
    try:
        return f"{float(val):.{places}f}"
    except (TypeError, ValueError):
        return str(val)


def _parse_json(text) -> dict | list | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None


def format_scoring_report(row: sqlite3.Row) -> str:
    """Format a photonforge.db row into a human-readable scoring report."""
    out: list[str] = []

    out.append(f"FILE:  {row['filename']}")
    if row["original_name"] and row["original_name"] != row["filename"]:
        out.append(f"       (was: {row['original_name']})")
    if row["exif_timestamp"]:
        out.append(f"WHEN:  {row['exif_timestamp']}")
    if row["session_id"]:
        out.append(f"SESS:  {row['session_id']}")
    out.append("")

    out.append("=== MASTER ===")
    out.append(f"  score          {_fmt_float(row['master_score'], 4)}")
    out.append(f"  needs_review   {bool(row['needs_review'])}")
    out.append(f"  is_duplicate   {bool(row['is_duplicate'])}")
    if row["dhash"]:
        out.append(f"  dhash          {row['dhash']}")
    out.append("")

    out.append("=== GENRE ===")
    out.append(f"  primary        {row['primary_genre'] or '(none)'}")
    out.append(f"  confidence     {_fmt_float(row['genre_confidence'])}")
    if row["genre"] and row["genre"] != row["primary_genre"]:
        out.append(f"  (legacy genre) {row['genre']}")

    genres = _parse_json(row["genres"])
    if isinstance(genres, dict):
        out.append("")
        if "subject" in genres or "photo_type" in genres:
            out.append(
                f"  subject        {genres.get('subject', '?')} "
                f"({_fmt_float(genres.get('subject_confidence'))})"
            )
            out.append(
                f"  photo_type     {genres.get('photo_type', '?')} "
                f"({_fmt_float(genres.get('type_confidence'))})"
            )
        dist = genres.get("distribution") or genres.get("genres")
        if isinstance(dist, dict):
            out.append("  distribution:")
            for g, p in sorted(dist.items(), key=lambda kv: -float(kv[1] or 0))[:8]:
                out.append(f"    {g:<24} {_fmt_float(p)}")
    elif isinstance(genres, list):
        out.append("  multi-genre:")
        for g in genres[:8]:
            if isinstance(g, dict):
                out.append(f"    {g.get('name', '?'):<24} {_fmt_float(g.get('confidence'))}")
            else:
                out.append(f"    {g}")
    out.append("")

    out.append("=== SUB-SCORES ===")
    out.append(f"  sharpness      {_fmt_float(row['sharpness'])}")
    out.append(f"  composition    {_fmt_float(row['composition'])}")
    out.append(f"  exposure       {_fmt_float(row['exposure'])}")
    subs = _parse_json(row["sub_scores"])
    if isinstance(subs, dict) and subs:
        for k, v in sorted(subs.items()):
            if k in {"sharpness", "composition", "exposure"}:
                continue
            out.append(f"  {k:<14} {_fmt_float(v)}")
    out.append("")

    if row["semantic_name"]:
        out.append("=== NAMING ===")
        out.append(f"  semantic       {row['semantic_name']}")
        out.append("")

    out.append("=== PIPELINE ===")
    out.append(f"  stages         {row['stages'] or '(none)'}")
    if row["error"]:
        out.append(f"  error          {row['error']}")

    return "\n".join(out)


class PreviewTab(TabPlugin):
    """Browse photos with thumbnail + formatted scoring report."""

    label = "Preview"

    def __init__(self, parent: tk.Widget, app):
        super().__init__(parent, app)
        self._conn: sqlite3.Connection | None = None
        self._current_table: str | None = None
        self._rows_by_filename: dict[str, sqlite3.Row] = {}
        self._sort_reverse: dict[str, bool] = {}
        self._tk_img = None  # prevent GC
        self._build_ui()

    # ── UI ──

    def _build_ui(self) -> None:
        # Top bar: folder selector + filters
        top = ttk.Frame(self)
        top.pack(fill="x", padx=4, pady=4)

        ttk.Label(top, text="Folder:").pack(side="left")
        self._folder_var = tk.StringVar()
        self._folder_combo = ttk.Combobox(
            top, textvariable=self._folder_var, width=24, state="readonly",
        )
        self._folder_combo.pack(side="left", padx=4)
        self._folder_combo.bind("<<ComboboxSelected>>", lambda e: self._load_folder())

        ttk.Label(top, text="Genre:").pack(side="left", padx=(12, 2))
        self._filter_genre_var = tk.StringVar(value="(all)")
        self._filter_genre = ttk.Combobox(
            top, textvariable=self._filter_genre_var, width=18, state="readonly",
        )
        self._filter_genre.pack(side="left")
        self._filter_genre.bind("<<ComboboxSelected>>", lambda e: self._apply_filters())

        ttk.Label(top, text="Min score:").pack(side="left", padx=(12, 2))
        self._min_score_var = tk.DoubleVar(value=0.0)
        ttk.Spinbox(
            top, from_=0.0, to=1.0, increment=0.05, width=6,
            textvariable=self._min_score_var,
            command=self._apply_filters,
        ).pack(side="left")

        self._hide_dupes_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            top, text="Hide duplicates", variable=self._hide_dupes_var,
            command=self._apply_filters,
        ).pack(side="left", padx=(12, 4))

        self._only_review_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            top, text="Needs-review only", variable=self._only_review_var,
            command=self._apply_filters,
        ).pack(side="left", padx=4)

        ttk.Button(top, text="Refresh", command=self._load_folder).pack(side="right", padx=4)

        # Body: paned window — list (left) | preview+report (right)
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        # -- Left: photo list --
        left = ttk.Frame(paned)
        paned.add(left, weight=2)

        self._tree = ttk.Treeview(
            left, columns=_LIST_COLUMNS, show="headings", selectmode="browse",
        )
        for col in _LIST_COLUMNS:
            self._tree.heading(
                col, text=_LIST_LABELS[col],
                command=lambda c=col: self._sort_column(c),
            )
            self._tree.column(
                col,
                width=_LIST_WIDTHS[col],
                anchor="w" if col == "filename" else "center",
            )

        vsb = ttk.Scrollbar(left, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        self._count_var = tk.StringVar(value="0 photos")
        ttk.Label(left, textvariable=self._count_var, anchor="w").pack(
            side="bottom", fill="x", padx=4, pady=(2, 0),
        )

        # -- Right: preview + report --
        right = ttk.PanedWindow(paned, orient="vertical")
        paned.add(right, weight=3)

        preview_frame = tk.Frame(right, bg="#000")
        right.add(preview_frame, weight=2)

        self._image_label = tk.Label(
            preview_frame, bg="#000", fg="#888",
            text="Select a photo to preview",
            anchor="center",
        )
        self._image_label.pack(fill="both", expand=True)
        # Re-render on resize so RAW thumbs use available height
        self._preview_frame = preview_frame
        preview_frame.bind("<Configure>", self._on_preview_resize)

        report_frame = ttk.LabelFrame(right, text="Scoring report", padding=4)
        right.add(report_frame, weight=2)

        self._report_text = tk.Text(
            report_frame, wrap="none", state="disabled",
            font=("Consolas", 9), bg="#1e1e1e", fg="#ddd",
            insertbackground="#fff",
        )
        rsb_y = ttk.Scrollbar(report_frame, orient="vertical", command=self._report_text.yview)
        rsb_x = ttk.Scrollbar(report_frame, orient="horizontal", command=self._report_text.xview)
        self._report_text.configure(yscrollcommand=rsb_y.set, xscrollcommand=rsb_x.set)
        rsb_y.pack(side="right", fill="y")
        rsb_x.pack(side="bottom", fill="x")
        self._report_text.pack(fill="both", expand=True)

        self._info_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self._info_var, anchor="w").pack(
            side="bottom", fill="x", padx=8, pady=(0, 4),
        )

    # ── Cartridge lifecycle ──

    def on_cartridge_changed(self, root: Path) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
        try:
            self._conn = db_ops.open_photondb(root)
        except Exception as e:
            messagebox.showerror("DB Error", f"Could not open photonforge.db:\n{e}")
            return
        tables = db_ops.list_tables(self._conn)
        self._folder_combo.configure(values=tables)
        if tables:
            self._folder_var.set(tables[0])
            self._load_folder()
        else:
            self._folder_var.set("")
            self._clear()

    # ── Data loading ──

    def _load_folder(self) -> None:
        if not self._conn:
            return
        folder = self._folder_var.get()
        if not folder:
            return
        self._current_table = folder
        try:
            rows = db_ops.get_all_rows(self._conn, folder)
        except sqlite3.OperationalError as e:
            messagebox.showerror("Query Error", str(e))
            return

        self._rows_by_filename = {r["filename"]: r for r in rows}

        # Populate genre filter dropdown from this folder's data.
        genres = sorted({
            (r["primary_genre"] or "").strip()
            for r in rows
            if (r["primary_genre"] or "").strip()
        })
        self._filter_genre.configure(values=["(all)"] + genres)
        if self._filter_genre_var.get() not in {"(all)", *genres}:
            self._filter_genre_var.set("(all)")

        self._apply_filters()

    def _apply_filters(self) -> None:
        rows = list(self._rows_by_filename.values())

        genre = self._filter_genre_var.get()
        if genre and genre != "(all)":
            rows = [r for r in rows if (r["primary_genre"] or "") == genre]

        try:
            min_score = float(self._min_score_var.get())
        except (TypeError, ValueError):
            min_score = 0.0
        if min_score > 0:
            rows = [r for r in rows if (r["master_score"] or 0.0) >= min_score]

        if self._hide_dupes_var.get():
            rows = [r for r in rows if not r["is_duplicate"]]
        if self._only_review_var.get():
            rows = [r for r in rows if r["needs_review"]]

        # Default sort: master_score desc
        rows.sort(key=lambda r: -(r["master_score"] or 0.0))

        self._tree.delete(*self._tree.get_children())
        for r in rows:
            values = [
                r["filename"],
                _fmt_float(r["master_score"], 3),
                r["primary_genre"] or "",
                _fmt_float(r["genre_confidence"], 2),
                _fmt_float(r["sharpness"], 3),
                _fmt_float(r["composition"], 3),
                _fmt_float(r["exposure"], 3),
                "Y" if r["needs_review"] else "",
                "Y" if r["is_duplicate"] else "",
            ]
            self._tree.insert("", "end", iid=r["filename"], values=values)

        self._count_var.set(
            f"{len(rows)} of {len(self._rows_by_filename)} photos"
        )
        self._clear_preview("Select a photo to preview")

    def _sort_column(self, col: str) -> None:
        reverse = self._sort_reverse.get(col, False)
        items = [(self._tree.set(iid, col), iid) for iid in self._tree.get_children("")]
        try:
            items.sort(key=lambda t: float(t[0]) if t[0] else 0.0, reverse=reverse)
        except ValueError:
            items.sort(key=lambda t: t[0].lower(), reverse=reverse)
        for idx, (_, iid) in enumerate(items):
            self._tree.move(iid, "", idx)
        self._sort_reverse[col] = not reverse

    # ── Selection / preview ──

    def _on_select(self, _event=None) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        filename = sel[0]
        row = self._rows_by_filename.get(filename)
        if row is None:
            return
        self._render_report(row)
        self._render_preview(filename)

    def _render_report(self, row: sqlite3.Row) -> None:
        report = format_scoring_report(row)
        self._report_text.configure(state="normal")
        self._report_text.delete("1.0", "end")
        self._report_text.insert("1.0", report)
        self._report_text.configure(state="disabled")

    def _render_preview(self, filename: str) -> None:
        root = self.app.cartridge_root
        if not root or not self._current_table:
            return
        path = root / self._current_table / filename
        if not path.is_file():
            self._clear_preview(f"<file not found: {path.name}>")
            return

        max_h = max(200, self._preview_frame.winfo_height() - 8)
        img = _load_image_for_preview(path, max_height=max_h)
        if img is None:
            self._clear_preview(f"<could not load: {path.name}>")
            return

        try:
            from PIL import ImageTk
            self._tk_img = ImageTk.PhotoImage(img)
            self._image_label.configure(image=self._tk_img, text="")
        except Exception as e:
            self._clear_preview(f"<preview failed: {e}>")
            return

        self._info_var.set(f"{filename}    {_read_exif_summary(path)}")

    def _on_preview_resize(self, _event=None) -> None:
        # Re-render the currently selected photo at the new max height.
        sel = self._tree.selection()
        if sel:
            self._render_preview(sel[0])

    def _clear_preview(self, message: str) -> None:
        self._tk_img = None
        self._image_label.configure(image="", text=message, fg="#888")
        self._info_var.set("")

    def _clear(self) -> None:
        self._rows_by_filename = {}
        self._tree.delete(*self._tree.get_children())
        self._count_var.set("0 photos")
        self._report_text.configure(state="normal")
        self._report_text.delete("1.0", "end")
        self._report_text.configure(state="disabled")
        self._clear_preview("Select a cartridge to begin")
