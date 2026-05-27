"""Reusable Tkinter widgets for the Cartridge Manager."""

from __future__ import annotations

import sqlite3
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from typing import Callable


class FolderTreeView(ttk.Frame):
    """Treeview showing cartridge directories with photo counts."""

    def __init__(self, parent: tk.Widget, on_select: Callable[[str], None] | None = None):
        super().__init__(parent)
        self._on_select = on_select

        self.tree = ttk.Treeview(
            self,
            columns=("photos", "scored", "named"),
            show="tree headings",
            selectmode="browse",
        )
        self.tree.heading("#0", text="Folder")
        self.tree.heading("photos", text="Photos")
        self.tree.heading("scored", text="Scored")
        self.tree.heading("named", text="Named")

        self.tree.column("#0", width=200, minwidth=120)
        self.tree.column("photos", width=70, anchor="center")
        self.tree.column("scored", width=70, anchor="center")
        self.tree.column("named", width=70, anchor="center")

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self._handle_select)

    def _handle_select(self, event: tk.Event) -> None:
        if self._on_select:
            sel = self.tree.selection()
            if sel:
                self._on_select(self.tree.item(sel[0], "text"))

    def populate(self, table_infos: list) -> None:
        """Populate with TableInfo objects from db_ops."""
        self.tree.delete(*self.tree.get_children())
        for info in table_infos:
            self.tree.insert(
                "",
                "end",
                text=info.name,
                values=(info.photo_count, info.has_scored, info.has_named),
            )

    def selected_folder(self) -> str | None:
        sel = self.tree.selection()
        if sel:
            return self.tree.item(sel[0], "text")
        return None


class PhotoListView(ttk.Frame):
    """Sortable table of photos in a folder."""

    COLUMNS = ("filename", "genre", "master_score", "sharpness", "stages")

    def __init__(self, parent: tk.Widget):
        super().__init__(parent)

        self.tree = ttk.Treeview(
            self,
            columns=self.COLUMNS,
            show="headings",
            selectmode="extended",
        )

        col_widths = {
            "filename": 220,
            "genre": 100,
            "master_score": 90,
            "sharpness": 80,
            "stages": 150,
        }
        col_labels = {
            "filename": "Filename",
            "genre": "Genre",
            "master_score": "Score",
            "sharpness": "Sharp",
            "stages": "Stages",
        }

        for col in self.COLUMNS:
            self.tree.heading(
                col,
                text=col_labels.get(col, col),
                command=lambda c=col: self._sort_column(c),
            )
            self.tree.column(
                col,
                width=col_widths.get(col, 100),
                anchor="w" if col == "filename" else "center",
            )

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._sort_reverse: dict[str, bool] = {}

    def _sort_column(self, col: str) -> None:
        items = [
            (self.tree.set(iid, col), iid)
            for iid in self.tree.get_children("")
        ]
        reverse = self._sort_reverse.get(col, False)
        try:
            items.sort(key=lambda t: float(t[0]) if t[0] else 0.0, reverse=reverse)
        except ValueError:
            items.sort(key=lambda t: t[0].lower(), reverse=reverse)

        for idx, (_, iid) in enumerate(items):
            self.tree.move(iid, "", idx)

        self._sort_reverse[col] = not reverse

    def populate(self, rows: list[sqlite3.Row]) -> None:
        self.tree.delete(*self.tree.get_children())
        for row in rows:
            values = []
            for col in self.COLUMNS:
                val = row[col] if col in row.keys() else ""
                if isinstance(val, float):
                    val = f"{val:.3f}"
                values.append(val or "")
            self.tree.insert("", "end", values=values)

    def selected_filenames(self) -> list[str]:
        return [
            self.tree.item(iid, "values")[0]
            for iid in self.tree.selection()
        ]

    def select_all(self) -> None:
        children = self.tree.get_children("")
        self.tree.selection_set(children)

    def clear_selection(self) -> None:
        self.tree.selection_remove(*self.tree.selection())


class StatusBar(ttk.Frame):
    """Bottom status bar with progress and log."""

    def __init__(self, parent: tk.Widget):
        super().__init__(parent, relief="sunken")

        self._label = ttk.Label(self, text="Ready", anchor="w")
        self._label.pack(side="left", fill="x", expand=True, padx=4)

        self._progress = ttk.Progressbar(self, length=200, mode="determinate")
        self._progress.pack(side="right", padx=4, pady=2)

    def set_status(self, text: str) -> None:
        self._label.configure(text=text)
        self._label.update_idletasks()

    def set_progress(self, value: float, maximum: float = 100.0) -> None:
        self._progress.configure(value=value, maximum=maximum)
        self._progress.update_idletasks()

    def reset(self) -> None:
        self._label.configure(text="Ready")
        self._progress.configure(value=0)


class CartridgeSelector(ttk.Frame):
    """Top bar for selecting the cartridge root path."""

    def __init__(
        self,
        parent: tk.Widget,
        on_change: Callable[[Path], None] | None = None,
    ):
        super().__init__(parent)
        self._on_change = on_change

        ttk.Label(self, text="Cartridge:").pack(side="left", padx=(4, 2))

        self._path_var = tk.StringVar()
        self._entry = ttk.Entry(self, textvariable=self._path_var, width=50)
        self._entry.pack(side="left", fill="x", expand=True, padx=2)

        self._browse_btn = ttk.Button(self, text="Browse", command=self._browse)
        self._browse_btn.pack(side="left", padx=2)

        self._entry.bind("<Return>", lambda e: self._apply())

    def _browse(self) -> None:
        from tkinter import filedialog

        path = filedialog.askdirectory(title="Select Cartridge Root")
        if path:
            self._path_var.set(path)
            self._apply()

    def _apply(self) -> None:
        path = self._path_var.get().strip()
        if path and self._on_change:
            self._on_change(Path(path))

    def get_path(self) -> Path | None:
        val = self._path_var.get().strip()
        return Path(val) if val else None

    def set_path(self, path: Path) -> None:
        self._path_var.set(str(path))


class ConfirmDialog(tk.Toplevel):
    """Modal confirmation dialog with details."""

    def __init__(
        self,
        parent: tk.Widget,
        title: str,
        message: str,
        details: str = "",
    ):
        super().__init__(parent)
        self.title(title)
        self.result = False

        self.transient(parent)
        self.grab_set()

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text=message, wraplength=400).pack(pady=(0, 8))

        if details:
            detail_text = tk.Text(frame, height=6, width=50, wrap="word")
            detail_text.insert("1.0", details)
            detail_text.configure(state="disabled")
            detail_text.pack(fill="x", pady=(0, 8))

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x")
        ttk.Button(btn_frame, text="Cancel", command=self._cancel).pack(side="right", padx=4)
        ttk.Button(btn_frame, text="Confirm", command=self._confirm).pack(side="right", padx=4)

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.geometry("450x250")
        self.wait_window()

    def _confirm(self) -> None:
        self.result = True
        self.destroy()

    def _cancel(self) -> None:
        self.result = False
        self.destroy()
