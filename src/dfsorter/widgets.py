from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QToolButton, QWidget

ICONS = Path(__file__).resolve().parents[2] / "resources/icons"


@lru_cache(maxsize=128)
def icon(name, color="#cbd5df"):
    data = (ICONS / f"{name}.svg").read_bytes().replace(b"currentColor", color.encode())
    if name == "star" and color == "#efd17b":
        data = data.replace(b'fill="none"', b'fill="#efd17b"')
    renderer = QSvgRenderer(data)
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def tool(name, label, callback):
    control = QToolButton()
    control.setIcon(icon(name))
    control.setIconSize(QSize(20, 20))
    control.setToolTip(label)
    control.setAccessibleName(label)
    control.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    control.clicked.connect(callback)
    return control


class ClipDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(100, 48)

    def paint(self, painter, option, index):
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor("#254557"))
        title, _, detail = str(index.data()).partition("\n")
        area = option.rect.adjusted(20, 3, -10, -3)
        painter.setPen(QColor("#e2e7ed"))
        painter.drawText(
            area,
            Qt.AlignmentFlag.AlignTop,
            option.fontMetrics.elidedText(title, Qt.TextElideMode.ElideRight, area.width()),
        )
        painter.setPen(QColor("#94a3b2"))
        painter.drawText(
            area,
            Qt.AlignmentFlag.AlignBottom,
            option.fontMetrics.elidedText(detail, Qt.TextElideMode.ElideRight, area.width()),
        )
        painter.setBrush(
            QColor(
                "#67c7ae"
                if "keep" in detail.lower()
                else "#db8791"
                if "discard" in detail.lower()
                else "#687887"
            )
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(option.rect.left() + 7, option.rect.center().y() - 3, 6, 6)
        painter.restore()


class Rating(QWidget):
    changed = Signal(object)

    def __init__(self):
        super().__init__()
        self.value = None
        self.preview = None
        self.setFixedSize(150, 30)
        self.setMouseTracking(True)
        self.setAccessibleName("Rating, one to five stars; right-click to clear")
        self.setToolTip("Click a star to rate · Right-click to clear · R then 1–5")

    def paintEvent(self, event):
        painter = QPainter(self)
        value = self.preview if self.preview is not None else (self.value or 0)
        for position in range(5):
            icon("star", "#efd17b" if position < value else "#566575").paint(
                painter, QRect(position * 30 + 3, 3, 24, 24)
            )

    def mouseMoveEvent(self, event):
        self.preview = min(5, max(1, int(event.position().x()) // 30 + 1))
        self.update()

    def leaveEvent(self, event):
        self.preview = None
        self.update()

    def mousePressEvent(self, event):
        self.changed.emit(
            None
            if event.button() == Qt.MouseButton.RightButton
            else min(5, max(1, int(event.position().x()) // 30 + 1))
        )
