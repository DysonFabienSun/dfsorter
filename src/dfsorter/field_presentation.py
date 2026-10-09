"""Shared field sequence controls for game configuration."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QWidget,
)

from .theme import role
from .widgets import icon


class FieldPresentation(QListWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAccessibleName("Field order, title inclusion and review visibility")
        self.setToolTip("Drag the grip to reorder. Alt+Up / Alt+Down moves the selected field.")
        self.model().rowsMoved.connect(self.renumber)

    def entries(self):
        return [self.item(index).data(Qt.ItemDataRole.UserRole) for index in range(self.count())]

    def set_entries(self, entries):
        self.clear()
        for key, included, review in entries:
            item = QListWidgetItem()
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
            item.setData(Qt.ItemDataRole.UserRole, (key, included, review))
            self.addItem(item)
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(8, 4, 8, 4)
            layout.setSpacing(8)
            grip = QLabel()
            grip.setProperty("headingIcon", "grip-vertical")
            grip.setProperty("headingIconSize", 16)
            grip.setPixmap(icon("grip-vertical").pixmap(16, 16))
            grip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(grip)
            position = QLabel()
            position.setObjectName("position")
            position.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            role(position, "muted")
            layout.addWidget(position)
            label = QLabel(key)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(label, 1)
            title = QCheckBox("In title")
            title.setChecked(included)
            title.setEnabled(key not in {"rating", "tag"})
            title.setAccessibleName(f"{key}: include in title")
            layout.addWidget(title)
            control = QComboBox()
            control.setMinimumContentsLength(len("Suggested"))
            control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            control.addItems(["Hidden", "Shown"] + ([] if key in {"mainline", "rating", "tag"} else ["Suggested"]))
            control.setCurrentText(review)
            control.setAccessibleName(f"{key}: review visibility")
            layout.addWidget(control)
            title.toggled.connect(lambda checked, entry=item: self.change_entry(entry, included=checked))
            control.currentTextChanged.connect(lambda value, entry=item: self.change_entry(entry, review=value))
            item.setSizeHint(widget.sizeHint())
            self.setItemWidget(item, widget)
        self.renumber(emit=False)

    def change_entry(self, item, *, included=None, review=None):
        key, old_included, old_review = item.data(Qt.ItemDataRole.UserRole)
        item.setData(Qt.ItemDataRole.UserRole, (
            key, old_included if included is None else included,
            old_review if review is None else review,
        ))
        self.setCurrentItem(item)
        self.changed.emit()

    def renumber(self, *args, emit=True):
        for index in range(self.count()):
            widget = self.itemWidget(self.item(index))
            if widget:
                widget.findChild(QLabel, "position").setText(f"{index + 1:02}")
        if emit:
            self.changed.emit()

    def move_selected(self, offset):
        index = self.currentRow()
        target = index + offset
        if index < 0 or not 0 <= target < self.count():
            return
        entries = self.entries()
        entries.insert(target, entries.pop(index))
        self.set_entries(entries)
        self.setCurrentRow(target)
        self.changed.emit()

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.AltModifier and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.move_selected(-1 if event.key() == Qt.Key.Key_Up else 1)
            event.accept()
            return
        super().keyPressEvent(event)
