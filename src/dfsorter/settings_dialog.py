from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

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
        future = QLabel("Additional application preferences will appear here in future updates.")
        future.setWordWrap(True)
        tabs.addTab(future, "General")
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.refresh()

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
