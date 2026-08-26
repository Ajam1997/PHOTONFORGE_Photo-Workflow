"""Backup/restore view for managing cartridge mirrors and snapshots."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from photo_workflow import backup

from .workers import Worker


class BackupView(QWidget):
    """Backup/restore operations for cartridge mirrors and snapshots."""

    operation_started = Signal(str)  # which op: "snapshot" | "backup" | "verify" | "restore"
    operation_finished = Signal(str, object)  # (op, result) — result type varies by op
    operation_failed = Signal(str, str)  # (op, message)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._current_op: str | None = None
        self._worker: Worker | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the UI: snapshot, backup, verify, restore sections."""
        layout = QVBoxLayout(self)

        # Shared cartridge root
        root_layout = QHBoxLayout()
        root_layout.addWidget(QLabel("Cartridge Root:"))
        self.root_edit = QLineEdit()
        root_layout.addWidget(self.root_edit, 1)
        root_browse = QPushButton("Browse…")
        root_browse.clicked.connect(self._on_root_browse)
        root_layout.addWidget(root_browse)
        layout.addLayout(root_layout)

        # Snapshot section
        snapshot_layout = QVBoxLayout()
        snapshot_layout.addWidget(QLabel("Snapshot (Catalog Backup)"))
        snapshot_opts = QHBoxLayout()
        snapshot_opts.addWidget(QLabel("Keep:"))
        self.keep_spinbox = QSpinBox()
        self.keep_spinbox.setValue(7)
        self.keep_spinbox.setMinimum(1)
        snapshot_opts.addWidget(self.keep_spinbox)
        snapshot_opts.addWidget(QLabel("Destination (blank → root/.photon-snapshots):"))
        self.snapshot_dest_edit = QLineEdit()
        snapshot_opts.addWidget(self.snapshot_dest_edit, 1)
        snapshot_browse = QPushButton("Browse…")
        snapshot_browse.clicked.connect(self._on_snapshot_dest_browse)
        snapshot_opts.addWidget(snapshot_browse)
        self.snapshot_button = QPushButton("Snapshot")
        self.snapshot_button.clicked.connect(self.run_snapshot)
        snapshot_opts.addWidget(self.snapshot_button)
        snapshot_layout.addLayout(snapshot_opts)
        layout.addLayout(snapshot_layout)

        # Backup section
        backup_layout = QVBoxLayout()
        backup_layout.addWidget(QLabel("Backup (Whole-Cartridge Mirror)"))
        backup_dest_layout = QHBoxLayout()
        backup_dest_layout.addWidget(QLabel("Destination:"))
        self.backup_dest_edit = QLineEdit()
        backup_dest_layout.addWidget(self.backup_dest_edit, 1)
        backup_dest_browse = QPushButton("Browse…")
        backup_dest_browse.clicked.connect(self._on_backup_dest_browse)
        backup_dest_layout.addWidget(backup_dest_browse)
        backup_layout.addLayout(backup_dest_layout)

        backup_opts1 = QHBoxLayout()
        self.state_only_checkbox = QCheckBox("State Only (no RAWs)")
        backup_opts1.addWidget(self.state_only_checkbox)
        self.exclude_models_checkbox = QCheckBox("Exclude Models")
        backup_opts1.addWidget(self.exclude_models_checkbox)
        self.no_incremental_checkbox = QCheckBox("No Incremental")
        backup_opts1.addWidget(self.no_incremental_checkbox)
        self.backup_force_checkbox = QCheckBox("Force (if busy)")
        backup_opts1.addWidget(self.backup_force_checkbox)
        backup_opts1.addStretch()
        backup_layout.addLayout(backup_opts1)

        backup_opts2 = QHBoxLayout()
        backup_opts2.addWidget(QLabel("Keep (blank → no cleanup):"))
        self.backup_keep_edit = QLineEdit()
        backup_opts2.addWidget(self.backup_keep_edit)
        self.backup_button = QPushButton("Backup")
        self.backup_button.clicked.connect(self.run_backup)
        backup_opts2.addWidget(self.backup_button)
        backup_opts2.addStretch()
        backup_layout.addLayout(backup_opts2)
        layout.addLayout(backup_layout)

        # Verify section
        verify_layout = QVBoxLayout()
        verify_layout.addWidget(QLabel("Verify (Re-hash Mirror)"))
        verify_snap_layout = QHBoxLayout()
        verify_snap_layout.addWidget(QLabel("Snapshot Path (blank → newest under Backup Dest):"))
        self.verify_snapshot_edit = QLineEdit()
        verify_snap_layout.addWidget(self.verify_snapshot_edit, 1)
        verify_snap_browse = QPushButton("Browse…")
        verify_snap_browse.clicked.connect(self._on_verify_snapshot_browse)
        verify_snap_layout.addWidget(verify_snap_browse)
        verify_layout.addLayout(verify_snap_layout)

        verify_opts = QHBoxLayout()
        verify_opts.addWidget(QLabel("Against (optional, compare against live cartridge):"))
        self.verify_against_edit = QLineEdit()
        verify_opts.addWidget(self.verify_against_edit, 1)
        verify_against_browse = QPushButton("Browse…")
        verify_against_browse.clicked.connect(self._on_verify_against_browse)
        verify_opts.addWidget(verify_against_browse)
        self.verify_button = QPushButton("Verify")
        self.verify_button.clicked.connect(self.run_verify)
        verify_opts.addWidget(self.verify_button)
        verify_layout.addLayout(verify_opts)
        layout.addLayout(verify_layout)

        # Restore section
        restore_layout = QVBoxLayout()
        restore_layout.addWidget(QLabel("Restore (Copy Mirror Back to Cartridge)"))
        restore_snap_layout = QHBoxLayout()
        restore_snap_layout.addWidget(QLabel("Snapshot Path:"))
        self.restore_snapshot_edit = QLineEdit()
        restore_snap_layout.addWidget(self.restore_snapshot_edit, 1)
        restore_snap_browse = QPushButton("Browse…")
        restore_snap_browse.clicked.connect(self._on_restore_snapshot_browse)
        restore_snap_layout.addWidget(restore_snap_browse)
        restore_layout.addLayout(restore_snap_layout)

        restore_target_layout = QHBoxLayout()
        restore_target_layout.addWidget(QLabel("Target Path:"))
        self.restore_target_edit = QLineEdit()
        restore_target_layout.addWidget(self.restore_target_edit, 1)
        restore_target_browse = QPushButton("Browse…")
        restore_target_browse.clicked.connect(self._on_restore_target_browse)
        restore_target_layout.addWidget(restore_target_browse)
        restore_layout.addLayout(restore_target_layout)

        restore_opts = QHBoxLayout()
        self.restore_force_checkbox = QCheckBox("Force (overwrite non-empty target)")
        restore_opts.addWidget(self.restore_force_checkbox)
        self.restore_button = QPushButton("Restore")
        self.restore_button.clicked.connect(self.run_restore)
        restore_opts.addWidget(self.restore_button)
        restore_opts.addStretch()
        restore_layout.addLayout(restore_opts)
        layout.addLayout(restore_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # Add stretch at the end
        layout.addStretch()

    def _on_root_browse(self) -> None:
        """Handle cartridge root browse button."""
        path = QFileDialog.getExistingDirectory(self, "Select cartridge root")
        if path:
            self.root_edit.setText(path)

    def _on_snapshot_dest_browse(self) -> None:
        """Handle snapshot destination browse button."""
        path = QFileDialog.getExistingDirectory(self, "Select snapshot destination")
        if path:
            self.snapshot_dest_edit.setText(path)

    def _on_backup_dest_browse(self) -> None:
        """Handle backup destination browse button."""
        path = QFileDialog.getExistingDirectory(self, "Select backup destination")
        if path:
            self.backup_dest_edit.setText(path)

    def _on_verify_snapshot_browse(self) -> None:
        """Handle verify snapshot path browse button."""
        path = QFileDialog.getExistingDirectory(self, "Select snapshot directory")
        if path:
            self.verify_snapshot_edit.setText(path)

    def _on_verify_against_browse(self) -> None:
        """Handle verify against cartridge browse button."""
        path = QFileDialog.getExistingDirectory(self, "Select cartridge root")
        if path:
            self.verify_against_edit.setText(path)

    def _on_restore_snapshot_browse(self) -> None:
        """Handle restore snapshot path browse button."""
        path = QFileDialog.getExistingDirectory(self, "Select snapshot directory")
        if path:
            self.restore_snapshot_edit.setText(path)

    def _on_restore_target_browse(self) -> None:
        """Handle restore target browse button."""
        path = QFileDialog.getExistingDirectory(self, "Select target directory")
        if path:
            self.restore_target_edit.setText(path)

    def run_snapshot(self) -> None:
        """Execute synchronous snapshot (catalog backup)."""
        # Guard: if worker is running, return
        if self.is_running():
            return

        # Guard: root must be selected
        if not self.root_edit.text():
            self.status_label.setText("No cartridge root selected.")
            return

        root = Path(self.root_edit.text())
        snaproot = (
            Path(self.snapshot_dest_edit.text())
            if self.snapshot_dest_edit.text()
            else root / backup.SNAPSHOT_DIRNAME
        )
        target = snaproot / backup.snapshot_timestamp()

        try:
            backup.snapshot_databases(root, target)
        except FileNotFoundError as exc:
            self.status_label.setText(str(exc))
            return

        pruned = backup.rotate_snapshots(snaproot, self.keep_spinbox.value())
        self.status_label.setText(
            f"Snapshot written to {target.name} (pruned {len(pruned)} old)."
        )
        self.operation_finished.emit("snapshot", target)

    def run_backup(self) -> None:
        """Execute asynchronous backup (whole-cartridge mirror)."""
        # Guard: if worker is running, return
        if self.is_running():
            return

        # Guard: root and dest must be selected
        if not self.root_edit.text():
            self.status_label.setText("No cartridge root selected.")
            return
        if not self.backup_dest_edit.text():
            self.status_label.setText("No backup destination selected.")
            return

        root = Path(self.root_edit.text())
        dest = Path(self.backup_dest_edit.text())

        # Resolve link_dest for incremental backup
        label = backup.cartridge_backup_name(root)
        link_dest = (
            None
            if self.no_incremental_checkbox.isChecked()
            else backup.latest_snapshot(dest, label)
        )

        # Parse keep value
        keep_text = self.backup_keep_edit.text()
        try:
            keep = int(keep_text) if keep_text else None
        except ValueError:
            self.status_label.setText("Keep must be a number.")
            return

        self._start_worker(
            "backup",
            backup.mirror_cartridge,
            root,
            dest,
            state_only=self.state_only_checkbox.isChecked(),
            exclude_models=self.exclude_models_checkbox.isChecked(),
            link_dest=link_dest,
            keep=keep,
            force=self.backup_force_checkbox.isChecked(),
        )

    def run_verify(self) -> None:
        """Execute asynchronous verify (re-hash mirror)."""
        # Guard: if worker is running, return
        if self.is_running():
            return

        # Resolve the snapshot path
        if self.verify_snapshot_edit.text():
            snapshot = Path(self.verify_snapshot_edit.text())
        else:
            # Use backup dest and root to find newest
            if not self.backup_dest_edit.text():
                self.status_label.setText(
                    "Give a snapshot path, or a Backup Dest to find the newest."
                )
                return
            dest = Path(self.backup_dest_edit.text())
            label = (
                backup.cartridge_backup_name(Path(self.root_edit.text()))
                if self.root_edit.text()
                else None
            )
            snapshot = backup.latest_snapshot(dest, label)
            if snapshot is None:
                self.status_label.setText(f"No snapshot found under {dest}")
                return

        # Resolve against cartridge (optional)
        against = (
            Path(self.verify_against_edit.text())
            if self.verify_against_edit.text()
            else None
        )

        self._start_worker("verify", backup.verify_snapshot, snapshot, against=against)

    def run_restore(self) -> None:
        """Execute asynchronous restore (copy mirror back to cartridge)."""
        # Guard: if worker is running, return
        if self.is_running():
            return

        # Guard: snapshot and target must be selected
        if not self.restore_snapshot_edit.text():
            self.status_label.setText("No snapshot path selected.")
            return
        if not self.restore_target_edit.text():
            self.status_label.setText("No target path selected.")
            return

        self._start_worker(
            "restore",
            backup.restore_snapshot,
            Path(self.restore_snapshot_edit.text()),
            Path(self.restore_target_edit.text()),
            force=self.restore_force_checkbox.isChecked(),
        )

    def _start_worker(self, op: str, fn, *args, **kwargs) -> None:
        """Start a Worker for the given operation."""
        self._current_op = op
        self._worker = Worker(fn, *args, **kwargs)

        # Connect signals
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.finished.connect(self._on_finished)
        self._worker.signals.failed.connect(self._on_failed)

        # Disable all buttons
        self.snapshot_button.setEnabled(False)
        self.backup_button.setEnabled(False)
        self.verify_button.setEnabled(False)
        self.restore_button.setEnabled(False)

        # Show progress bar (indeterminate initially)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()

        # Emit signal and start worker
        self.operation_started.emit(op)
        self._worker.start()

    def _on_progress(self, index: int, total: int, label: str) -> None:
        """Handle progress signal from worker."""
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(index)
        else:
            self.progress_bar.setRange(0, 0)
        op = self._current_op or "operation"
        self.status_label.setText(f"[{op}] [{index}/{total}] {label}")

    def _on_finished(self, result: object) -> None:
        """Handle successful operation completion."""
        op = self._current_op or "operation"

        # Format completion message based on operation type
        if op == "backup":
            msg = f"Backup complete: {result}"
        elif op == "verify":
            # result is a list of problem strings; empty means clean
            if isinstance(result, list) and len(result) == 0:
                msg = "Verify: clean."
            elif isinstance(result, list):
                problems_summary = "; ".join(result[:3])
                msg = f"Verify: {len(result)} problem(s): {problems_summary}"
            else:
                msg = f"Verify complete: {result}"
        elif op == "restore":
            msg = f"Restore complete: {result}"
        else:
            msg = f"{op.title()} complete: {result}"

        self.status_label.setText(msg)

        # Re-enable all buttons
        self.snapshot_button.setEnabled(True)
        self.backup_button.setEnabled(True)
        self.verify_button.setEnabled(True)
        self.restore_button.setEnabled(True)

        # Hide progress bar
        self.progress_bar.hide()
        self._worker.wait()  # ensure the OS thread has actually joined before releasing it
        self._worker = None

        # Emit signal
        self.operation_finished.emit(op, result)

    def _on_failed(self, message: str) -> None:
        """Handle operation failure."""
        op = self._current_op or "operation"
        self.status_label.setText(f"{op.title()} failed: {message}")

        # Re-enable all buttons
        self.snapshot_button.setEnabled(True)
        self.backup_button.setEnabled(True)
        self.verify_button.setEnabled(True)
        self.restore_button.setEnabled(True)

        # Hide progress bar
        self.progress_bar.hide()
        self._worker.wait()  # ensure the OS thread has actually joined before releasing it
        self._worker = None

        # Emit signal
        self.operation_failed.emit(op, message)

    def is_running(self) -> bool:
        """Return whether a worker is currently active."""
        return self._worker is not None and self._worker.isRunning()
