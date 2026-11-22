"""Profile management window."""
from pathlib import Path
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
                               QPushButton, QLineEdit, QMessageBox, QInputDialog,
                               QFileDialog)
from PySide6.QtCore import Qt

from hid_proxy.config.profiles import ProfileManager


class ProfilesWindow(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        # Ensure profile_manager exists
        if not hasattr(app.config, 'profile_manager'):
            app.config.profile_manager = ProfileManager(app.config)
        self.profile_manager = app.config.profile_manager
        self.setWindowTitle("Profile Manager")
        self.resize(400, 400)
        self._setup_ui()
        self._refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._load_selected)
        layout.addWidget(self.list)

        btn_layout = QHBoxLayout()
        for text, slot in [
            ("New", self._new_profile),
            ("Save", self._save_current),
            ("Load", self._load_selected),
            ("Delete", self._delete_selected),
            ("Export", self._export),
            ("Import", self._import),
        ]:
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            btn_layout.addWidget(btn)
        layout.addLayout(btn_layout)

    def _refresh(self):
        self.list.clear()
        for p in self.profile_manager.list_profiles():
            self.list.addItem(f"{p['name']} - {p['description']}")

    def _get_selected_name(self):
        item = self.list.currentItem()
        return item.text().split(" - ")[0] if item else None

    def _new_profile(self):
        name, ok = QInputDialog.getText(self, "New Profile", "Profile name:")
        if ok and name:
            self.profile_manager.save_profile(name, "")
            self._refresh()

    def _save_current(self):
        name, ok = QInputDialog.getText(self, "Save Profile", "Profile name:")
        if ok and name:
            self.profile_manager.save_profile(name, "Saved from current settings")
            self._refresh()

    def _load_selected(self):
        name = self._get_selected_name()
        if name and self.profile_manager.load_profile(name):
            QMessageBox.information(self, "Success", f"Loaded profile: {name}")
        elif name:
            QMessageBox.warning(self, "Error", "Failed to load profile")

    def _delete_selected(self):
        name = self._get_selected_name()
        if name and self.profile_manager.delete_profile(name):
            self._refresh()

    def _export(self):
        name = self._get_selected_name()
        if not name:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Profile", f"{name}.json", "JSON (*.json)")
        if path:
            if self.profile_manager.export_profile(name, Path(path)):
                QMessageBox.information(self, "Success", f"Exported profile: {name}")
            else:
                QMessageBox.warning(self, "Error", "Failed to export profile")

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Profile", "", "JSON (*.json)")
        if path:
            if self.profile_manager.import_profile(Path(path)):
                QMessageBox.information(self, "Success", "Profile imported")
                self._refresh()
            else:
                QMessageBox.warning(self, "Error", "Failed to import profile")