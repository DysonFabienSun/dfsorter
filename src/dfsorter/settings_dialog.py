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
        self.projects = QListWidget()
        for title, listing, source, actions in [
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
                    "Projects reference library clips. Deleting a project keeps its clips and files."
                )
            )
            body.addWidget(listing)
            controls = QHBoxLayout()
            for label, callback in actions:
                control = QPushButton(label)
                if label == "Delete":
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
        self.paused_typing = QCheckBox("Type to enter commands while video is paused")
        self.paused_typing.setChecked(window.settings.get("paused_typing_enabled", True))
        self.paused_typing.toggled.connect(self.save_command_preferences)
        preferences.addWidget(self.paused_typing)
        self.lowercase_titles = QCheckBox("Lowercase working titles and generated filenames")
        self.lowercase_titles.setChecked(window.settings.get("lowercase_generated_titles", True))
        self.lowercase_titles.setToolTip(
            "Keeps game codes uppercase. Custom filenames and original filename fallbacks "
            "keep their casing. Uncheck to use stored capitalization."
        )
        self.lowercase_titles.toggled.connect(self.save_title_preferences)
        preferences.addWidget(self.lowercase_titles)
        preferences.addStretch()
        self.start_near_end.toggled.connect(self.save_playback_preferences)
        self.start_offset.valueChanged.connect(self.save_playback_preferences)
        tabs.insertTab(0, general, "General")
        tabs.setCurrentIndex(0)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.refresh()

    def save_title_preferences(self):
        self.window.settings["lowercase_generated_titles"] = self.lowercase_titles.isChecked()
        self.window.save_settings()
        self.window.refresh_title_presentation()

    def save_playback_preferences(self):
        self.start_offset.setEnabled(self.start_near_end.isChecked())
        self.window.settings["start_near_end_enabled"] = self.start_near_end.isChecked()
        self.window.settings["start_near_end_seconds"] = self.start_offset.value()
        self.window.save_settings()

    def save_command_preferences(self):
        self.window.settings["paused_typing_enabled"] = self.paused_typing.isChecked()
        self.window.save_settings()
        self.window.update_command_state()

    def refresh(self):
        for listing, source in [
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
