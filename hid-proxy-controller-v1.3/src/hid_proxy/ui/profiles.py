"""Profile management window."""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
                               QPushButton, QLineEdit, QMessageBox, QInputDialog)
from PySide6.QtCore import Qt

class ProfilesWindow(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
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
        for p in self.app.config.profile_manager.list_profiles():
            self.list.addItem(f"{p['name']} - {p['description']}")
    
    def _get_selected_name(self):
        item = self.list.currentItem()
        return item.text().split(" - ")[0] if item else None
    
    def _new_profile(self):
        name, ok = QInputDialog.getText(self, "New Profile", "Profile name:")
        if ok and name:
            self.app.config.profile_manager.save_profile(name, "")
            self._refresh()
    
    def _save_current(self):
        name, ok = QInputDialog.getText(self, "Save Profile", "Profile name:")
        if ok and name:
            self.app.config.profile_manager.save_profile(name, "Saved from current settings")
            self._refresh()
    
    def _load_selected(self):
        name = self._get_selected_name()
        if name and self.app.config.profile_manager.load_profile(name):
            QMessageBox.information(self, "Success", f"Loaded profile: {name}")
        elif name:
            QMessageBox.warning(self, "Error", "Failed to load profile")
    
    def _delete_selected(self):
        name = self._get_selected_name()
        if name and self.app.config.profile_manager.delete_profile(name):
            self._refresh()
    
    def _export(self):
        name = self._get_selected_name()
        if not name:
            return
        profile = self.app.config.profile_manager.get_profile(name)
        if profile:
            import json
            from PySide6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getSaveFileName(self, "Export Profile", f"{name}.json", "JSON (*.json)")
            if path:
                with open(path, "w") as f:
                    json.dump(profile.__dict__, f, indent=2)
    
    def _import(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "Import Profile", "", "JSON (*.json)")
        if path:
            import json
            with open(path) as f:
                data = json.load(f)
            # Implementation would restore profile
            pass
