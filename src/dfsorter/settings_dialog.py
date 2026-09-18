from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .playback import start_offset_seconds
from .theme import role


class SettingsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Settings")
        self.resize(850, 560)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        self.folders = QListWidget()
        self.projects = QListWidget()
        for title, listing, source, actions in [
            (
                "Capture folders",
                self.folders,
                window.folders,
                [
                    ("Add / preview", window.add_folder),
                    ("Rescan", window.rescan),
                    ("Reinspect all media…", window.reinspect),
                    ("Enable / disable", window.toggle_folder),
                    ("Migrate", window.migrate),
                    ("Remove", window.remove_folder),
                    ("Purge entries", window.purge),
                ],
            ),
            (
                "Projects",
                self.projects,
                window.projects,
                [
                    ("New", window.new_project),
                    ("Rename", window.rename_project),
                    ("Activate", window.activate_project),
                    ("Deactivate", window.deactivate),
                    ("Delete", window.delete_project),
                ],
            ),
        ]:
            page = QWidget()
            body = QVBoxLayout(page)
            body.addWidget(
                QLabel(
                    "Capture folders contain your original videos. Removing a folder keeps its files."
                    if title == "Capture folders"
                    else "Projects reference library clips. Deleting a project keeps its clips and files."
                )
            )
            body.addWidget(listing)
            controls = QHBoxLayout()
            for label, callback in actions:
                control = QPushButton(label)
                if label in {"Delete", "Purge entries"}:
                    role(control, "danger")
                control.clicked.connect(
                    lambda checked=False, listing=listing, source=source, callback=callback: (
                        self.run_action(listing, source, callback)
                    )
                )
                controls.addWidget(control)
            body.addLayout(controls)
            tabs.addTab(page, title)
        general = QWidget()
        preferences = QVBoxLayout(general)
        self.start_near_end = QCheckBox("Start videos without a valid I/O range near the end")
        self.start_near_end.setChecked(window.settings.get("start_near_end_enabled", True))
        preferences.addWidget(self.start_near_end)
        offset_row = QHBoxLayout()
        offset_label = QLabel("Start before the end:")
        self.start_offset = QSpinBox()
        self.start_offset.setRange(1, 86400)
        self.start_offset.setSuffix(" s")
        self.start_offset.setValue(start_offset_seconds(window.settings))
        self.start_offset.setEnabled(self.start_near_end.isChecked())
        offset_label.setBuddy(self.start_offset)
        offset_row.addWidget(offset_label)
        offset_row.addWidget(self.start_offset)
        offset_row.addStretch()
        preferences.addLayout(offset_row)
        explanation = QLabel(
            "Applies to videos opened in any panel. Saved I/O ranges start at the In point. "
            "Shorter videos start at the beginning. Changes are saved automatically and "
            "apply the next time a video is opened."
        )
        explanation.setWordWrap(True)
        preferences.addWidget(explanation)
        preferences.addStretch()
        self.start_near_end.toggled.connect(self.save_playback_preferences)
        self.start_offset.valueChanged.connect(self.save_playback_preferences)
        tabs.addTab(general, "General")
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.refresh()

    def save_playback_preferences(self):
        self.start_offset.setEnabled(self.start_near_end.isChecked())
        self.window.settings["start_near_end_enabled"] = self.start_near_end.isChecked()
        self.window.settings["start_near_end_seconds"] = self.start_offset.value()
        self.window.save_settings()

    def refresh(self):
        for listing, source in [
            (self.folders, self.window.folders),
            (self.projects, self.window.projects),
        ]:
            selected = self.window.selected_id(listing)
            listing.clear()
            for index in range(source.count()):
                item = QListWidgetItem(source.item(index))
                listing.addItem(item)
                if item.data(Qt.ItemDataRole.UserRole) == selected:
                    listing.setCurrentItem(item)

    def run_action(self, listing, source, callback):
        selected = self.window.selected_id(listing)
        source.setCurrentRow(-1)
        for index in range(source.count()):
            if source.item(index).data(Qt.ItemDataRole.UserRole) == selected:
                source.setCurrentRow(index)
                break
        callback()
        self.refresh()
