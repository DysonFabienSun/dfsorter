from collections import defaultdict
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .theme import role


def size_text(size):
    return f"{size / (1024**3):.2f} GiB ({size:,} bytes)"


class DeletionDialog(QDialog):
    def __init__(self, candidates, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Permanently delete rejected originals")
        self.resize(1050, 620)
        self.candidates = tuple(item for item in candidates if not item.problem)
        layout = QVBoxLayout(self)
        warning = QLabel(
            "All discarded clips known to the library, including disabled or removed capture "
            "folders. Current filters do not apply. Only original video files are deleted; "
            "catalogue records, project/session references and sidecars remain.\n"
            "Permanent deletion bypasses the Recycle Bin and cannot be undone."
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        count = len(self.candidates)
        total = sum(item.size for item in self.candidates)
        summary = QLabel(
            f"{count} videos to delete · Estimated total: {size_text(total)}\n"
            f"{len(candidates) - count} unavailable / unsafe files excluded. "
            "Sizes are logical file sizes; disk space recovered may differ."
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Folder / full video path", "Videos", "Date", "Size / status"])
        grouped = defaultdict(list)
        for item in candidates:
            grouped[str(Path(item.display_path or item.path).parent)].append(item)
        for folder, items in sorted(grouped.items(), key=lambda entry: entry[0].casefold()):
            eligible = [item for item in items if not item.problem]
            group = QTreeWidgetItem(
                self.tree,
                [
                    folder,
                    f"{len(eligible)} to delete / {len(items)} rejected",
                    "",
                    size_text(sum(item.size for item in eligible)),
                ],
            )
            group.setToolTip(0, folder)
            for item in items:
                child = QTreeWidgetItem(
                    group,
                    [
                        item.display_path or item.path,
                        "",
                        item.date,
                        f"Excluded: {item.problem}" if item.problem else size_text(item.size),
                    ],
                )
                for column in range(4):
                    child.setToolTip(column, child.text(column))
        self.tree.expandAll()
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.tree.setColumnWidth(0, 480)
        self.tree.setColumnWidth(1, 160)
        self.tree.setColumnWidth(2, 260)
        layout.addWidget(self.tree, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.delete_button = buttons.addButton(
            "Permanently delete originals", QDialogButtonBox.ButtonRole.AcceptRole
        )
        role(self.delete_button, "danger")
        self.delete_button.setEnabled(count > 0)
        self.delete_button.setAutoDefault(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
