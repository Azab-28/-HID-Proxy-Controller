"""Targets window for process selection with save/apply functionality."""
from typing import List, Dict
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
                               QTableWidgetItem, QPushButton, QLineEdit, QHeaderView,
                               QCheckBox, QMessageBox, QAbstractItemView, QLabel)
from PySide6.QtCore import Qt, QTimer, Signal

from hid_proxy.system.process import ProcessEnumerator
from hid_proxy.utils.logging import get_logger

log = get_logger(__name__)


class TargetsWindow(QWidget):
    """Target process configuration window."""
    
    # Signal emitted when targets are saved
    targets_saved = Signal(list)

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.process_enum = ProcessEnumerator()
        self.setWindowTitle("Target Processes")
        self.resize(700, 500)
        self._selected_pids = set()
        self._current_filter = ""
        self._setup_ui()
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh_processes)
        self._refresh_timer.start(5000)  # Refresh every 5 seconds
        self._refresh_processes()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Header with status
        header_layout = QHBoxLayout()
        self.status_label = QLabel("0 targets selected")
        header_layout.addWidget(self.status_label)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Search/filter
        filter_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter processes...")
        self.search_input.textChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.search_input)

        self.games_only = QCheckBox("Games only")
        self.games_only.toggled.connect(self._refresh_processes)
        filter_layout.addWidget(self.games_only)

        self.auto_refresh = QCheckBox("Auto-refresh")
        self.auto_refresh.setChecked(True)
        self.auto_refresh.toggled.connect(self._toggle_auto_refresh)
        filter_layout.addWidget(self.auto_refresh)

        layout.addLayout(filter_layout)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Select", "PID", "Name", "Path", "User"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 60)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 70)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(4, 120)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        # Buttons
        btn_layout = QHBoxLayout()
        refresh_btn = QPushButton("Refresh Now")
        refresh_btn.clicked.connect(self._refresh_processes)
        btn_layout.addWidget(refresh_btn)

        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(lambda: self._set_all_checks(True))
        btn_layout.addWidget(select_all_btn)

        clear_btn = QPushButton("Clear Selection")
        clear_btn.clicked.connect(lambda: self._set_all_checks(False))
        btn_layout.addWidget(clear_btn)

        btn_layout.addStretch()

        # Save/Apply buttons
        self.save_btn = QPushButton("Save Selection")
        self.save_btn.clicked.connect(self._save_selection)
        self.save_btn.setEnabled(False)
        btn_layout.addWidget(self.save_btn)

        self.apply_btn = QPushButton("Apply to Targeting")
        self.apply_btn.clicked.connect(self._apply_to_targeting)
        self.apply_btn.setEnabled(False)
        btn_layout.addWidget(self.apply_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.hide)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def _refresh_processes(self):
        """Fetch and populate process list, preserving selections and filter."""
        try:
            processes = self.process_enum.enumerate()
            if self.games_only.isChecked():
                processes = self.process_enum.filter_games(processes)

            # Store current selections
            selected_pids = set()
            for row in range(self.table.rowCount()):
                checkbox = self.table.cellWidget(row, 0)
                if checkbox and checkbox.isChecked():
                    pid_item = self.table.item(row, 1)
                    if pid_item:
                        selected_pids.add(int(pid_item.text()))

            # Store current filter
            current_filter = self.search_input.text().lower()

            # Populate table
            self.table.setRowCount(0)  # Clear first
            for proc in processes:
                row = self.table.rowCount()
                self.table.insertRow(row)

                # Checkbox
                checkbox = QCheckBox()
                checkbox.setChecked(proc['pid'] in self._selected_pids)
                checkbox.toggled.connect(self._on_selection_changed)
                self.table.setCellWidget(row, 0, checkbox)

                # PID
                pid_item = QTableWidgetItem(str(proc['pid']))
                pid_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, 1, pid_item)

                # Name
                self.table.setItem(row, 2, QTableWidgetItem(proc['name']))

                # Path
                self.table.setItem(row, 3, QTableWidgetItem(proc['path']))

                # User
                user_item = QTableWidgetItem(proc['user'] or "N/A")
                user_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, 4, user_item)

            # Restore selections
            self._selected_pids = selected_pids
            for row in range(self.table.rowCount()):
                checkbox = self.table.cellWidget(row, 0)
                if checkbox:
                    pid_item = self.table.item(row, 1)
                    if pid_item and int(pid_item.text()) in selected_pids:
                        checkbox.setChecked(True)

            # Apply filter without clearing it
            self._apply_filter(self._current_filter)
            self._update_status()

        except Exception as e:
            log.error(f"Failed to refresh processes: {e}")

    def _on_selection_changed(self):
        """Update selected PIDs when checkbox toggled."""
        checkbox = self.sender()
        if not isinstance(checkbox, QCheckBox):
            return
        
        row = self.table.indexAt(checkbox.pos()).row()
        pid_item = self.table.item(row, 1)
        if pid_item:
            pid = int(pid_item.text())
            if checkbox.isChecked():
                self._selected_pids.add(pid)
            else:
                self._selected_pids.discard(pid)
            self._update_status()
            self.save_btn.setEnabled(len(self._selected_pids) > 0)
            self.apply_btn.setEnabled(len(self._selected_pids) > 0)

    def _on_filter_changed(self, text: str):
        """Handle filter text change."""
        self._current_filter = text.lower()
        self._apply_filter(self._current_filter)

    def _apply_filter(self, text: str):
        """Apply filter to table rows."""
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 2)
            path_item = self.table.item(row, 3)
            show = False
            if name_item and text in name_item.text().lower():
                show = True
            if path_item and text in path_item.text().lower():
                show = True
            self.table.setRowHidden(row, not show)

    def _toggle_auto_refresh(self, enabled: bool):
        if enabled:
            self._refresh_timer.start(5000)
        else:
            self._refresh_timer.stop()

    def _set_all_checks(self, checked: bool):
        for row in range(self.table.rowCount()):
            checkbox = self.table.cellWidget(row, 0)
            if checkbox:
                checkbox.setChecked(checked)

    def _update_status(self):
        count = len(self._selected_pids)
        self.status_label.setText(f"{count} target{'s' if count != 1 else ''} selected")
        self.save_btn.setEnabled(count > 0)
        self.apply_btn.setEnabled(count > 0)

    def _save_selection(self):
        """Save selected PIDs to config."""
        if not self._selected_pids:
            return
        
        # Save to config
        targets = list(self._selected_pids)
        self.app.config.set("targeting.target_pids", targets)
        log.info(f"Saved {len(targets)} target PIDs")
        QMessageBox.information(self, "Saved", f"Saved {len(targets)} target PIDs to configuration.")

    def _apply_to_targeting(self):
        """Apply selected targets to targeting system."""
        if not self._selected_pids:
            return
        
        targets = list(self._selected_pids)
        self.app.config.set("targeting.target_pids", targets)
        
        # Update detector if needed
        if hasattr(self.app, 'detector') and self.app.detector:
            self.app.detector.config = self.app.config
        
        self.targets_saved.emit(list(self._selected_pids))
        QMessageBox.information(self, "Applied", f"Applied {len(targets)} targets to targeting system.")

    def _toggle_auto_refresh(self, enabled: bool):
        if enabled:
            self._refresh_timer.start(5000)
        else:
            self._refresh_timer.stop()

    def closeEvent(self, event):
        self._refresh_timer.stop()
        super().closeEvent(event)