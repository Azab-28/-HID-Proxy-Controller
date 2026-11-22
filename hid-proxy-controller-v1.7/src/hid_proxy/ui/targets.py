"""Targets window for process selection with persistence and timer lifecycle management."""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from hid_proxy.system.process import ProcessEnumerator
from hid_proxy.utils.logging import get_logger

log = get_logger(__name__)


class TargetsWindow(QWidget):
    targets_saved = Signal(list)

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.process_enum = ProcessEnumerator()
        self.setWindowTitle("Target Processes")
        self.resize(700, 500)
        self._selected_pids = set(self.app.config.get("targeting.target_pids", []))
        self._current_filter = ""
        self._setup_ui()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_processes)
        self._refresh_timer.start(5000)
        self._refresh_processes()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        header_layout = QHBoxLayout()
        self.status_label = QLabel("0 targets selected")
        header_layout.addWidget(self.status_label)
        header_layout.addStretch()
        layout.addLayout(header_layout)

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

        self.save_btn = QPushButton("Save Selection")
        self.save_btn.clicked.connect(self._save_selection)
        btn_layout.addWidget(self.save_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.hide)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.auto_refresh.isChecked() and not self._refresh_timer.isActive():
            self._refresh_timer.start(5000)
        self._refresh_processes()

    def hideEvent(self, event) -> None:
        self._refresh_timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self._refresh_timer.stop()
        event.ignore()
        self.hide()

    def _refresh_processes(self) -> None:
        try:
            processes = self.process_enum.enumerate()
            if self.games_only.isChecked():
                processes = self.process_enum.filter_games(processes)

            self.table.setRowCount(0)
            for proc in processes:
                row = self.table.rowCount()
                self.table.insertRow(row)
                pid = proc["pid"]

                checkbox = QCheckBox()
                checkbox.setChecked(pid in self._selected_pids)
                checkbox.toggled.connect(lambda checked, p=pid: self._on_pid_toggled(p, checked))
                self.table.setCellWidget(row, 0, checkbox)

                pid_item = QTableWidgetItem(str(pid))
                pid_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, 1, pid_item)
                self.table.setItem(row, 2, QTableWidgetItem(proc["name"]))
                self.table.setItem(row, 3, QTableWidgetItem(proc["path"]))

                user_item = QTableWidgetItem(proc["user"] or "N/A")
                user_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, 4, user_item)

            self._apply_filter(self._current_filter)
            self._update_status()
        except Exception as e:
            log.error(f"Failed to refresh processes: {e}")

    def _on_pid_toggled(self, pid: int, checked: bool) -> None:
        if checked:
            self._selected_pids.add(pid)
        else:
            self._selected_pids.discard(pid)
        self._update_status()

    def _on_filter_changed(self, text: str) -> None:
        self._current_filter = text.lower()
        self._apply_filter(self._current_filter)

    def _apply_filter(self, text: str) -> None:
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 2)
            path_item = self.table.item(row, 3)
            show = not text or (
                (name_item and text in name_item.text().lower())
                or (path_item and text in path_item.text().lower())
            )
            self.table.setRowHidden(row, not show)

    def _toggle_auto_refresh(self, enabled: bool) -> None:
        if enabled:
            self._refresh_timer.start(5000)
        else:
            self._refresh_timer.stop()

    def _set_all_checks(self, checked: bool) -> None:
        for row in range(self.table.rowCount()):
            if not self.table.isRowHidden(row):
                checkbox = self.table.cellWidget(row, 0)
                if checkbox:
                    checkbox.setChecked(checked)

    def _update_status(self) -> None:
        count = len(self._selected_pids)
        self.status_label.setText(f"{count} target{'s' if count != 1 else ''} selected")

    def _save_selection(self) -> None:
        targets = sorted(self._selected_pids)
        self.app.config.set("targeting.target_pids", targets)
        self.targets_saved.emit(targets)
        log.info(f"Saved {len(targets)} target PIDs")
        QMessageBox.information(self, "Saved", f"Saved {len(targets)} target PIDs.")
