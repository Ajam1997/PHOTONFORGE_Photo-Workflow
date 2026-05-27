"""PHOTONForge Cartridge Manager — main application shell.

Tab-based Tkinter GUI for cartridge restructuring, test data generation,
and training data import/export.

Usage:
    python -m tools.cartridge_manager.app
    python -m tools.cartridge_manager.app H:\\
"""

from __future__ import annotations

import sqlite3
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from pathlib import Path
from typing import Type

from . import db_ops, file_ops, sampler, training_io
from .ui_widgets import (
    CartridgeSelector,
    ConfirmDialog,
    FolderTreeView,
    PhotoListView,
    StatusBar,
)


class TabPlugin(ttk.Frame):
    """Base class for tab plugins."""

    label: str = "Tab"

    def __init__(self, parent: tk.Widget, app: "CartridgeManagerApp"):
        super().__init__(parent)
        self.app = app

    def on_cartridge_changed(self, root: Path) -> None:
        pass

    def on_activated(self) -> None:
        pass


# ── Organize Tab ─────────────────────────────────────────


class OrganizeTab(TabPlugin):
    label = "Organize"

    def __init__(self, parent: tk.Widget, app: "CartridgeManagerApp"):
        super().__init__(parent, app)
        self._conn: sqlite3.Connection | None = None
        self._current_table: str | None = None

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=4, pady=4)

        left = ttk.Frame(paned)
        paned.add(left, weight=1)

        btn_bar = ttk.Frame(left)
        btn_bar.pack(fill="x", pady=(0, 4))
        ttk.Button(btn_bar, text="New Folder", command=self._new_folder).pack(side="left", padx=2)
        ttk.Button(btn_bar, text="Delete Folder", command=self._delete_folder).pack(side="left", padx=2)
        ttk.Button(btn_bar, text="Scan & Rename", command=self._scan_rename).pack(side="left", padx=2)
        ttk.Button(btn_bar, text="Refresh", command=self._refresh_tree).pack(side="left", padx=2)

        self.folder_tree = FolderTreeView(left, on_select=self._on_folder_select)
        self.folder_tree.pack(fill="both", expand=True)

        right = ttk.Frame(paned)
        paned.add(right, weight=2)

        photo_bar = ttk.Frame(right)
        photo_bar.pack(fill="x", pady=(0, 4))
        ttk.Button(photo_bar, text="Move Selected", command=self._move_selected).pack(side="left", padx=2)
        ttk.Button(photo_bar, text="Select All", command=lambda: self.photo_list.select_all()).pack(side="left", padx=2)
        ttk.Button(photo_bar, text="Clear Selection", command=lambda: self.photo_list.clear_selection()).pack(side="left", padx=2)

        self.photo_list = PhotoListView(right)
        self.photo_list.pack(fill="both", expand=True)

    def on_cartridge_changed(self, root: Path) -> None:
        if self._conn:
            self._conn.close()
        self._conn = db_ops.open_photondb(root)
        self._refresh_tree()

    def _refresh_tree(self) -> None:
        if not self._conn:
            return
        tables = db_ops.list_tables(self._conn)
        infos = [db_ops.get_table_info(self._conn, t) for t in tables]
        self.folder_tree.populate(infos)

    def _on_folder_select(self, folder: str) -> None:
        self._current_table = folder
        if not self._conn:
            return
        rows = db_ops.get_all_rows(self._conn, folder)
        self.photo_list.populate(rows)
        self.app.status.set_status(f"{folder}: {len(rows)} photos")

    def _new_folder(self) -> None:
        root = self.app.cartridge_root
        if not root:
            messagebox.showwarning("No Cartridge", "Select a cartridge first.")
            return

        name = simpledialog.askstring("New Folder", "Folder name:", parent=self)
        if not name:
            return

        file_ops.create_directory(root, name)
        db_ops.create_table(self._conn, name)
        self._refresh_tree()
        self.app.status.set_status(f"Created folder: {name}")

    def _delete_folder(self) -> None:
        folder = self.folder_tree.selected_folder()
        if not folder:
            return

        info = db_ops.get_table_info(self._conn, folder)
        folder_path = self.app.cartridge_root / folder
        file_count = len(list(folder_path.iterdir())) if folder_path.is_dir() else 0

        if info.photo_count > 0:
            dlg = ConfirmDialog(
                self,
                "Delete Non-Empty Folder",
                f"Folder '{folder}' still has {info.photo_count} photo(s) in the DB "
                f"and {file_count} file(s) on disk.\n\n"
                f"This will drop the DB table AND delete all files. Continue?",
                details=f"DB table: {folder}\nDisk path: {folder_path}",
            )
            if not dlg.result:
                return
        else:
            dlg = ConfirmDialog(
                self,
                "Delete Folder",
                f"Delete folder '{folder}' and its database table?"
                + (f"\n({file_count} file(s) on disk will be removed)" if file_count else ""),
            )
            if not dlg.result:
                return

        db_ops.delete_table(self._conn, folder)
        if folder_path.is_dir():
            import shutil
            shutil.rmtree(folder_path, ignore_errors=True)
        self._refresh_tree()
        self.app.status.set_status(f"Deleted folder: {folder}")

    def _move_selected(self) -> None:
        root = self.app.cartridge_root
        if not root or not self._conn or not self._current_table:
            return

        filenames = self.photo_list.selected_filenames()
        if not filenames:
            messagebox.showinfo("No Selection", "Select photos to move.")
            return

        tables = db_ops.list_tables(self._conn)
        available = [t for t in tables if t != self._current_table]
        if not available:
            messagebox.showinfo("No Destination", "Create another folder first.")
            return

        dst = _pick_destination(self, available)
        if not dst:
            return

        src_dir = root / self._current_table
        dst_dir = root / dst

        details = "\n".join(filenames[:20])
        if len(filenames) > 20:
            details += f"\n... and {len(filenames) - 20} more"

        dlg = ConfirmDialog(
            self,
            "Move Photos",
            f"Move {len(filenames)} photo(s) from '{self._current_table}' to '{dst}'?",
            details=details,
        )
        if not dlg.result:
            return

        journal = file_ops.OperationJournal(path=root / ".move_journal.json")
        dt_conn = None
        try:
            dt_conn = db_ops.open_darktable_db(root)
        except FileNotFoundError:
            pass

        moved = 0
        errors: list[str] = []
        for i, fn in enumerate(filenames):
            try:
                file_ops.move_photo(src_dir, dst_dir, fn, journal=journal)
                db_ops.move_row(self._conn, self._current_table, dst, fn)
                if dt_conn and db_ops.darktable_image_exists(dt_conn, fn):
                    db_ops.update_darktable_folder(dt_conn, fn, dst)
                moved += 1
            except Exception as e:
                errors.append(f"{fn}: {e}")
            self.app.status.set_progress(i + 1, len(filenames))

        if dt_conn:
            dt_conn.close()
        journal.clear()

        self._on_folder_select(self._current_table)
        self._refresh_tree()
        self.app.status.reset()

        msg = f"Moved {moved}/{len(filenames)} photos."
        if errors:
            msg += f"\n\nErrors:\n" + "\n".join(errors[:10])
        messagebox.showinfo("Move Complete", msg)

    def _scan_rename(self) -> None:
        root = self.app.cartridge_root
        folder = self.folder_tree.selected_folder()
        if not root or not self._conn or not folder:
            messagebox.showwarning("No Selection", "Select a folder to scan.")
            return

        folder_dir = root / folder
        if not folder_dir.is_dir():
            messagebox.showwarning("Not Found", f"Directory not found: {folder_dir}")
            return

        # Dry run first to show preview
        self.app.status.set_status(f"Scanning {folder} for un-named photos...")
        preview = file_ops.scan_and_rename(
            folder_dir, root, dry_run=True,
        )

        if preview.renamed == 0:
            messagebox.showinfo(
                "Nothing to Rename",
                f"Found {preview.total_found} photo(s), "
                f"{preview.already_named} already named.\n"
                f"No files need renaming.",
            )
            self.app.status.reset()
            return

        trip_code = file_ops.derive_trip_code(folder)
        label = file_ops._get_volume_label(root)
        cart_id = file_ops.extract_cartridge_id(label)

        details = f"Cartridge ID: {cart_id}  Trip code: {trip_code}\n"
        details += f"Pattern: P{cart_id}{trip_code}NNNNNNN.ext\n\n"
        details += "\n".join(
            f"{old} -> {new}" for old, new in preview.renames[:30]
        )
        if len(preview.renames) > 30:
            details += f"\n... and {len(preview.renames) - 30} more"

        dlg = ConfirmDialog(
            self,
            "Scan & Rename",
            f"Rename {preview.renamed} photo(s) in '{folder}' "
            f"using PHOTONForge naming convention?\n\n"
            f"({preview.already_named} already named, {preview.total_found} total on disk)",
            details=details,
        )
        if not dlg.result:
            self.app.status.reset()
            return

        # Execute the rename
        def progress(current, total):
            self.app.status.set_progress(current, total)

        result = file_ops.scan_and_rename(
            folder_dir, root, progress_callback=progress,
        )

        # Register renamed files in photonforge.db
        from .file_ops import _read_exif_timestamp

        db_ops.create_table(self._conn, folder)
        registered = 0
        for old_name, new_name in result.renames:
            exif_ts = _read_exif_timestamp(folder_dir / new_name)
            try:
                self._conn.execute(
                    f"INSERT OR IGNORE INTO [{db_ops.sanitize_table_name(folder)}] "
                    f"(filename, original_name, exif_timestamp, stages) "
                    f"VALUES (?, ?, ?, ?)",
                    (new_name, old_name, exif_ts, "scan"),
                )
                registered += 1
            except Exception:
                pass
        self._conn.commit()

        self._on_folder_select(folder)
        self._refresh_tree()
        self.app.status.reset()

        msg = f"Renamed {result.renamed} photo(s).\nRegistered {registered} in DB."
        if result.already_named:
            msg += f"\n{result.already_named} already named (skipped)."
        if result.errors:
            msg += f"\n\nErrors:\n" + "\n".join(result.errors[:10])
        messagebox.showinfo("Scan & Rename Complete", msg)


# ── Sample Tab ───────────────────────────────────────────


class SampleTab(TabPlugin):
    label = "Sample"

    def __init__(self, parent: tk.Widget, app: "CartridgeManagerApp"):
        super().__init__(parent, app)
        self._conn: sqlite3.Connection | None = None

        frame = ttk.LabelFrame(self, text="Test Dataset Generator", padding=8)
        frame.pack(fill="both", expand=True, padx=8, pady=8)

        row = 0
        ttk.Label(frame, text="Source Folder:").grid(row=row, column=0, sticky="w", pady=2)
        self._source_var = tk.StringVar()
        self._source_combo = ttk.Combobox(frame, textvariable=self._source_var, width=30, state="readonly")
        self._source_combo.grid(row=row, column=1, sticky="ew", pady=2, padx=4)

        row += 1
        ttk.Label(frame, text="Sample Size:").grid(row=row, column=0, sticky="w", pady=2)
        self._n_var = tk.IntVar(value=20)
        ttk.Spinbox(frame, from_=1, to=10000, textvariable=self._n_var, width=10).grid(
            row=row, column=1, sticky="w", pady=2, padx=4
        )

        row += 1
        ttk.Label(frame, text="Strategy:").grid(row=row, column=0, sticky="w", pady=2)
        self._strategy_var = tk.StringVar(value="random")
        strategy_frame = ttk.Frame(frame)
        strategy_frame.grid(row=row, column=1, sticky="w", pady=2, padx=4)
        for val, label in [("random", "Random"), ("stratified", "Stratified"), ("top_bottom", "Top/Bottom")]:
            ttk.Radiobutton(strategy_frame, text=label, variable=self._strategy_var, value=val).pack(side="left", padx=4)

        row += 1
        ttk.Label(frame, text="Stratify By:").grid(row=row, column=0, sticky="w", pady=2)
        self._stratify_var = tk.StringVar(value="genre")
        ttk.Combobox(
            frame,
            textvariable=self._stratify_var,
            values=["genre", "primary_genre", "session_id"],
            width=20,
            state="readonly",
        ).grid(row=row, column=1, sticky="w", pady=2, padx=4)

        row += 1
        ttk.Label(frame, text="Seed:").grid(row=row, column=0, sticky="w", pady=2)
        self._seed_var = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=self._seed_var, width=15).grid(
            row=row, column=1, sticky="w", pady=2, padx=4
        )
        ttk.Label(frame, text="(blank = random)").grid(row=row, column=2, sticky="w")

        row += 1
        ttk.Button(frame, text="Generate Test Dataset", command=self._generate).grid(
            row=row, column=0, columnspan=3, pady=12
        )

        frame.columnconfigure(1, weight=1)

    def on_cartridge_changed(self, root: Path) -> None:
        if self._conn:
            self._conn.close()
        self._conn = db_ops.open_photondb(root)
        tables = db_ops.list_tables(self._conn)
        self._source_combo.configure(values=tables)
        if tables:
            self._source_var.set(tables[0])

    def _generate(self) -> None:
        root = self.app.cartridge_root
        if not root or not self._conn:
            messagebox.showwarning("No Cartridge", "Select a cartridge first.")
            return

        src_table = self._source_var.get()
        if not src_table:
            messagebox.showwarning("No Source", "Select a source folder.")
            return

        n = self._n_var.get()
        strategy = self._strategy_var.get()
        seed_str = self._seed_var.get().strip()
        seed = int(seed_str) if seed_str.isdigit() else None

        src_dir = root / src_table

        def progress(current, total, error=None):
            self.app.status.set_progress(current, total)
            if error:
                self.app.status.set_status(f"Error: {error}")

        self.app.status.set_status(f"Generating {strategy} sample of {n} from {src_table}...")

        try:
            manifest = sampler.generate_test_dataset(
                conn=self._conn,
                src_table=src_table,
                src_dir=src_dir,
                cartridge_root=root,
                n=n,
                strategy=strategy,
                seed=seed,
                stratify_by=self._stratify_var.get(),
                progress_callback=progress,
            )
            self.app.status.reset()
            messagebox.showinfo(
                "Dataset Created",
                f"Created test dataset: _testset_{manifest.timestamp}\n"
                f"Sampled {manifest.n_sampled}/{manifest.n_requested} photos\n"
                f"Strategy: {manifest.strategy}, Seed: {manifest.seed}",
            )
        except Exception as e:
            self.app.status.reset()
            messagebox.showerror("Error", f"Failed to generate dataset:\n{e}")


# ── Training Tab ─────────────────────────────────────────


class TrainingTab(TabPlugin):
    label = "Training"

    def __init__(self, parent: tk.Widget, app: "CartridgeManagerApp"):
        super().__init__(parent, app)
        self._db_path: Path | None = None

        # -- Local DB info --
        info_frame = ttk.LabelFrame(self, text="Local Training Database", padding=8)
        info_frame.pack(fill="x", padx=8, pady=(8, 4))

        path_row = ttk.Frame(info_frame)
        path_row.pack(fill="x")
        ttk.Label(path_row, text="DB Path:").pack(side="left")
        self._path_var = tk.StringVar()
        ttk.Entry(path_row, textvariable=self._path_var, width=50).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(path_row, text="Browse", command=self._browse_db).pack(side="left")

        self._stats_label = ttk.Label(info_frame, text="No database loaded", anchor="w")
        self._stats_label.pack(fill="x", pady=(4, 0))

        # -- Actions --
        action_frame = ttk.Frame(self, padding=8)
        action_frame.pack(fill="x", padx=8)

        ttk.Button(action_frame, text="Export Full Bundle", command=self._export_full).pack(side="left", padx=4)
        ttk.Button(action_frame, text="Export Corrections Only", command=self._export_lite).pack(side="left", padx=4)
        ttk.Button(action_frame, text="Import Bundle", command=self._import_bundle).pack(side="left", padx=4)
        ttk.Separator(action_frame, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(action_frame, text="Merge Corpora", command=self._merge_corpora).pack(side="left", padx=4)
        ttk.Button(action_frame, text="View Corpus", command=self._view_corpus).pack(side="left", padx=4)

        # -- Info / preview pane (shared) --
        preview_frame = ttk.LabelFrame(self, text="Info", padding=8)
        preview_frame.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        # Bottom bar must be packed first so it claims space before the text area
        bottom = ttk.Frame(preview_frame)
        bottom.pack(side="bottom", fill="x", pady=(4, 0))

        self._preview_text = tk.Text(
            preview_frame, height=10, width=60, wrap="none", state="disabled",
            font=("Consolas", 9),
        )
        scroll_y = ttk.Scrollbar(preview_frame, orient="vertical", command=self._preview_text.yview)
        scroll_x = ttk.Scrollbar(preview_frame, orient="horizontal", command=self._preview_text.xview)
        self._preview_text.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        scroll_y.pack(side="right", fill="y")
        scroll_x.pack(side="bottom", fill="x")
        self._preview_text.pack(fill="both", expand=True)

        ttk.Label(bottom, text="Strategy:").pack(side="left")
        self._strategy_var = tk.StringVar(value="merge_corrections")
        ttk.Combobox(
            bottom,
            textvariable=self._strategy_var,
            values=["replace", "merge_corrections", "merge_all"],
            width=20,
            state="readonly",
        ).pack(side="left", padx=4)

        self._apply_btn = ttk.Button(bottom, text="Apply Import", command=self._apply_import, state="disabled")
        self._apply_btn.pack(side="right", padx=4)

        self._save_corpus_btn = ttk.Button(bottom, text="Save Clean Corpus", command=self._save_clean_corpus, state="disabled")
        self._save_corpus_btn.pack(side="right", padx=4)

        self._pending_bundle: Path | None = None
        self._viewed_corpus: Path | None = None

    def on_cartridge_changed(self, root: Path) -> None:
        candidate = root / "training_weights.db"
        if candidate.exists():
            self._path_var.set(str(candidate))
            self._db_path = candidate
            self._refresh_stats()

    def _browse_db(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Training Weights DB",
            filetypes=[("SQLite DB", "*.db"), ("All Files", "*.*")],
        )
        if path:
            self._path_var.set(path)
            self._db_path = Path(path)
            self._refresh_stats()

    def _refresh_stats(self) -> None:
        if not self._db_path or not self._db_path.exists():
            self._stats_label.configure(text="No database loaded")
            return

        stats = training_io.get_local_stats(self._db_path)
        genres = ", ".join(stats.custom_genre_names) if stats.custom_genre_names else "none"
        self._stats_label.configure(
            text=(
                f"Prototypes: {stats.n_active_prototypes} active (v{stats.max_version})  |  "
                f"Corrections: {stats.n_corrections}  |  "
                f"Adapters: {stats.n_adapters}  |  "
                f"Custom genres: {genres}"
            )
        )

    def _export_full(self) -> None:
        if not self._db_path:
            messagebox.showwarning("No DB", "Select a training database first.")
            return

        out = filedialog.asksaveasfilename(
            title="Export Training Bundle",
            defaultextension=".photon-training",
            filetypes=[("PHOTONForge Training", "*.photon-training")],
        )
        if not out:
            return

        try:
            result = training_io.export_training_bundle(self._db_path, Path(out))
            messagebox.showinfo("Export Complete", f"Bundle saved to:\n{result}")
        except Exception as e:
            messagebox.showerror("Export Failed", str(e))

    def _export_lite(self) -> None:
        if not self._db_path:
            messagebox.showwarning("No DB", "Select a training database first.")
            return

        out = filedialog.asksaveasfilename(
            title="Export Corrections",
            defaultextension=".photon-training",
            filetypes=[("PHOTONForge Training", "*.photon-training")],
        )
        if not out:
            return

        try:
            result = training_io.export_corrections_only(self._db_path, Path(out))
            messagebox.showinfo("Export Complete", f"Corrections bundle saved to:\n{result}")
        except Exception as e:
            messagebox.showerror("Export Failed", str(e))

    def _import_bundle(self) -> None:
        if not self._db_path:
            messagebox.showwarning("No DB", "Select a local training database first.")
            return

        bundle = filedialog.askopenfilename(
            title="Select Training Bundle",
            filetypes=[("PHOTONForge Training", "*.photon-training"), ("All Files", "*.*")],
        )
        if not bundle:
            return

        self._pending_bundle = Path(bundle)
        try:
            preview = training_io.preview_import(self._pending_bundle, self._db_path)
            lines = []
            lines.append(f"+ {preview.new_corrections} new corrections")
            if preview.conflicting_prototypes:
                lines.append(f"~ {preview.conflicting_prototypes} prototype conflicts")
            if preview.new_custom_genres:
                lines.append(f"+ {len(preview.new_custom_genres)} new custom genres: {', '.join(preview.new_custom_genres)}")

            if preview.bundle_stats:
                bs = preview.bundle_stats
                lines.append(f"\nBundle: v{bs.max_version}, {bs.n_corrections} corrections, {bs.n_adapters} adapters")

            self._preview_text.configure(state="normal")
            self._preview_text.delete("1.0", "end")
            self._preview_text.insert("1.0", "\n".join(lines))
            self._preview_text.configure(state="disabled")
            self._apply_btn.configure(state="normal")

        except Exception as e:
            messagebox.showerror("Preview Failed", str(e))
            self._pending_bundle = None

    def _apply_import(self) -> None:
        if not self._pending_bundle or not self._db_path:
            return

        strategy = self._strategy_var.get()

        dlg = ConfirmDialog(
            self,
            "Confirm Import",
            f"Import training data using '{strategy}' strategy?",
            details=self._preview_text.get("1.0", "end").strip(),
        )
        if not dlg.result:
            return

        try:
            stats = training_io.import_training_bundle(
                self._pending_bundle, self._db_path, strategy
            )
            self._refresh_stats()
            self._pending_bundle = None
            self._apply_btn.configure(state="disabled")
            self._preview_text.configure(state="normal")
            self._preview_text.delete("1.0", "end")
            self._preview_text.configure(state="disabled")

            messagebox.showinfo(
                "Import Complete",
                f"Training DB updated.\n"
                f"Prototypes: {stats.n_active_prototypes} (v{stats.max_version})\n"
                f"Corrections: {stats.n_corrections}\n"
                f"Custom genres: {stats.n_custom_genres}",
            )
        except Exception as e:
            messagebox.showerror("Import Failed", str(e))

    def _view_corpus(self) -> None:
        corpus = filedialog.askopenfilename(
            title="Select Corpus JSONL",
            filetypes=[("JSONL", "*.jsonl"), ("All Files", "*.*")],
        )
        if not corpus:
            return

        self._viewed_corpus = Path(corpus)

        try:
            stats = training_io.analyze_corpus(
                self._viewed_corpus,
                training_db_path=self._db_path,
            )
            report = training_io.format_corpus_report(stats)

            self._preview_text.configure(state="normal")
            self._preview_text.delete("1.0", "end")
            self._preview_text.insert("1.0", report)
            self._preview_text.configure(state="disabled")

            self._save_corpus_btn.configure(state="normal")
        except Exception as e:
            messagebox.showerror("Corpus Analysis Failed", str(e))

    def _save_clean_corpus(self) -> None:
        if not self._viewed_corpus:
            return

        out = filedialog.asksaveasfilename(
            title="Save Clean Corpus As",
            defaultextension=".jsonl",
            filetypes=[("JSONL", "*.jsonl"), ("All Files", "*.*")],
            initialfile=self._viewed_corpus.stem + "_clean.jsonl",
        )
        if not out:
            return

        try:
            result = training_io.export_clean_corpus(
                self._viewed_corpus, Path(out),
            )
            messagebox.showinfo(
                "Corpus Saved",
                f"Input records: {result.input_records}\n"
                f"Duplicate overrides: {result.dropped_dupes}\n"
                f"Dropped (empty/unlabeled): {result.dropped_empty}\n"
                f"Clean output: {result.output_records} labels\n\n"
                f"Saved to: {result.output_path}",
            )
        except Exception as e:
            messagebox.showerror("Save Failed", str(e))

    def _merge_corpora(self) -> None:
        base = filedialog.askopenfilename(
            title="Select Base Corpus (existing labels)",
            filetypes=[("JSONL", "*.jsonl"), ("All Files", "*.*")],
        )
        if not base:
            return

        new = filedialog.askopenfilename(
            title="Select New Corpus (to merge in)",
            filetypes=[("JSONL", "*.jsonl"), ("All Files", "*.*")],
        )
        if not new:
            return

        out = filedialog.asksaveasfilename(
            title="Save Merged Corpus As",
            defaultextension=".jsonl",
            filetypes=[("JSONL", "*.jsonl"), ("All Files", "*.*")],
            initialfile=Path(base).stem + "_merged.jsonl",
        )
        if not out:
            return

        try:
            result = training_io.merge_corpora(Path(base), Path(new), Path(out))
            messagebox.showinfo(
                "Merge Complete",
                f"Base: {result.base_count} labels\n"
                f"New: {result.new_count} labels\n"
                f"Added: {result.added}, Updated: {result.updated}\n"
                f"Merged total: {result.merged_count} labels\n\n"
                f"Saved to: {result.output_path}",
            )
        except Exception as e:
            messagebox.showerror("Merge Failed", str(e))


# ── Destination picker dialog ────────────────────────────


def _pick_destination(parent: tk.Widget, folders: list[str]) -> str | None:
    result = {"value": None}

    dlg = tk.Toplevel(parent)
    dlg.title("Select Destination")
    dlg.transient(parent)
    dlg.grab_set()

    ttk.Label(dlg, text="Move to:", padding=8).pack(anchor="w")

    var = tk.StringVar()
    listbox = tk.Listbox(dlg, height=10, width=40)
    for f in folders:
        listbox.insert("end", f)
    listbox.pack(fill="both", expand=True, padx=8, pady=4)

    def confirm():
        sel = listbox.curselection()
        if sel:
            result["value"] = listbox.get(sel[0])
        dlg.destroy()

    btn_frame = ttk.Frame(dlg)
    btn_frame.pack(fill="x", padx=8, pady=8)
    ttk.Button(btn_frame, text="Cancel", command=dlg.destroy).pack(side="right", padx=4)
    ttk.Button(btn_frame, text="Select", command=confirm).pack(side="right", padx=4)

    dlg.geometry("350x300")
    dlg.wait_window()
    return result["value"]


# ── Main Application ─────────────────────────────────────


class CartridgeManagerApp:
    """Main application shell with tab-based plugin registry."""

    def __init__(self, root: tk.Tk, initial_path: Path | None = None):
        self.root = root
        self.root.title("PHOTONForge Cartridge Manager")
        self.root.geometry("1000x700")

        self.cartridge_root: Path | None = None
        self._tabs: dict[str, TabPlugin] = {}

        self.selector = CartridgeSelector(root, on_change=self._on_cartridge_changed)
        self.selector.pack(fill="x", padx=4, pady=4)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=4, pady=4)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.status = StatusBar(root)
        self.status.pack(fill="x", side="bottom")

        self.register_tab(OrganizeTab)
        self.register_tab(SampleTab)
        self.register_tab(TrainingTab)

        from .labeler import LabelerTab
        self.register_tab(LabelerTab)

        if initial_path:
            self.selector.set_path(initial_path)
            self._on_cartridge_changed(initial_path)

    def register_tab(self, tab_class: Type[TabPlugin]) -> None:
        tab = tab_class(self.notebook, self)
        self.notebook.add(tab, text=tab.label)
        self._tabs[tab.label] = tab

    def _on_cartridge_changed(self, root: Path) -> None:
        if not root.is_dir():
            messagebox.showerror("Invalid Path", f"Not a directory: {root}")
            return

        self.cartridge_root = root
        self.status.set_status(f"Cartridge: {root}")
        for tab in self._tabs.values():
            tab.on_cartridge_changed(root)

    def _on_tab_changed(self, event: tk.Event) -> None:
        idx = self.notebook.index("current")
        tab_name = self.notebook.tab(idx, "text")
        if tab_name in self._tabs:
            self._tabs[tab_name].on_activated()


def main() -> None:
    import sys

    root = tk.Tk()
    initial = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    CartridgeManagerApp(root, initial_path=initial)
    root.mainloop()


if __name__ == "__main__":
    main()
