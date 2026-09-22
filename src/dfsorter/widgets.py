import html
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QIcon,
    QLinearGradient,
    QPainter,
    QPixmap,
    QTextDocument,
    QTextLayout,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton, QStyle, QStyledItemDelegate, QToolButton, QWidget

from .theme import COLORS, SIZES, font

ICONS = Path(__file__).resolve().parents[2] / "resources/icons"
CLIP_ROLE = Qt.ItemDataRole.UserRole + 1


class ClipScrollFade(QWidget):
    def __init__(self, edge, parent=None):
        super().__init__(parent)
        self.edge = edge
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def paintEvent(self, event):
        color = QColor(COLORS["surface_sidebar"])
        transparent = QColor(color)
        transparent.setAlpha(0)
        gradient = QLinearGradient(0, 0, 0, self.height())
        if self.edge == "top":
            gradient.setColorAt(0, color)
            gradient.setColorAt(1, transparent)
        else:
            gradient.setColorAt(0, transparent)
            gradient.setColorAt(1, color)
        painter = QPainter(self)
        painter.fillRect(self.rect(), gradient)


def tag_prefix(clip, rich=False):
    value = (clip.get("tag") or "").strip()
    if not value:
        return ""
    text = f"[{value}]"
    if rich:
        return f'<b style="color:{COLORS["tag"]}">{html.escape(text)}</b> '
    return text + " "


@lru_cache(maxsize=128)
def icon(name, color=None, fill=False, size=24):
    result = QIcon()
    source = (ICONS / f"{name}.svg").read_bytes()
    for mode, state, tint in [
        (QIcon.Mode.Normal, QIcon.State.Off, color or COLORS["text_secondary"]),
        (QIcon.Mode.Active, QIcon.State.Off, color or COLORS["text_primary"]),
        (QIcon.Mode.Normal, QIcon.State.On, color or COLORS["accent_default"]),
        (QIcon.Mode.Active, QIcon.State.On, color or COLORS["accent_hover"]),
        (QIcon.Mode.Disabled, QIcon.State.Off, COLORS["text_disabled"]),
        (QIcon.Mode.Disabled, QIcon.State.On, COLORS["text_disabled"]),
    ]:
        data = source.replace(b"currentColor", tint.encode())
        if fill:
            data = data.replace(b'fill="none"', f'fill="{tint}"'.encode())
        for scale in (1, 2, 3):
            pixmap = QPixmap(size * scale, size * scale)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            QSvgRenderer(data).render(painter)
            painter.end()
            pixmap.setDevicePixelRatio(scale)
            result.addPixmap(pixmap, mode, state)
    return result


def set_icon(control, name, color_role=None):
    control.setProperty("iconName", name)
    control.setProperty("iconColorRole", color_role)
    control.setIcon(icon(name, COLORS[color_role] if color_role else None))


def refresh_icons(root):
    icon.cache_clear()
    for control in root.findChildren(QAbstractButton):
        name = control.property("iconName")
        if name:
            color_role = control.property("iconColorRole")
            control.setIcon(icon(name, COLORS[color_role] if color_role else None))


def tool(name, label, callback):
    control = QToolButton()
    set_icon(control, name)
    size = (
        SIZES["icon_lg"]
        if name in {"play", "pause", "skip-back", "skip-forward", "volume-2"}
        else SIZES["icon_md"]
    )
    control.setIconSize(QSize(size, size))
    control.setFixedSize(SIZES["toolbar"], SIZES["toolbar"])
    control.setToolTip(label)
    control.setAccessibleName(label)
    control.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    control.clicked.connect(callback)
    return control


class ClipDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        height = (
            QFontMetrics(font("md", base=option.font)).height()
            + QFontMetrics(font("xs", base=option.font)).height()
            + 14
        )
        return QSize(100, max(SIZES["card"], height) + SIZES["card_gap"])

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        data = index.data(CLIP_ROLE) or {}
        card = option.rect.adjusted(1, 1, -1, -SIZES["card_gap"] - 1)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        if selected or hovered:
            painter.setBrush(QColor(COLORS["accent_selection" if selected else "surface_hover"]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(card, 3, 3)
        else:
            painter.setPen(QColor(COLORS["border_subtle"]))
            painter.drawLine(
                card.left() + SIZES["card_padding"],
                card.bottom(),
                card.right() - SIZES["card_padding"],
                card.bottom(),
            )
        if focused:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QColor(COLORS["focus"]))
            painter.drawRoundedRect(card, 3, 3)
        if selected:
            painter.fillRect(
                card.left() + 1,
                card.top() + 4,
                2,
                card.height() - 8,
                QColor(COLORS["accent_default"]),
            )
        title_font = font("md", base=option.font)
        detail_font = font("xs", base=option.font)
        title_metrics = QFontMetrics(title_font)
        detail_metrics = QFontMetrics(detail_font)
        top = (
            card.top() + (card.height() - title_metrics.height() - detail_metrics.height() - 2) // 2
        )
        area = QRect(
            card.left() + SIZES["card_padding"],
            top,
            max(0, card.width() - 2 * SIZES["card_padding"]),
            title_metrics.height(),
        )
        painter.setFont(title_font)
        painter.setPen(QColor(COLORS["text_primary"]))
        document = QTextDocument()
        document.setDefaultFont(title_font)
        document.setHtml(
            '<span style="white-space:pre-wrap">' + data.get("rich_title", "") + "</span>"
        )
        formats = []
        fragment_iterator = document.begin().begin()
        while not fragment_iterator.atEnd():
            fragment = fragment_iterator.fragment()
            span = QTextLayout.FormatRange()
            span.start = fragment.position()
            span.length = fragment.length()
            span.format = fragment.charFormat()
            formats.append(span)
            fragment_iterator += 1
        text = data.get("title", str(index.data()))
        elided = QFontMetrics(font("md", "bold", base=option.font)).elidedText(
            text, Qt.TextElideMode.ElideRight, area.width()
        )
        text_layout = QTextLayout(elided, title_font)
        text_layout.setFormats(formats)
        text_layout.beginLayout()
        line = text_layout.createLine()
        line.setLineWidth(area.width())
        text_layout.endLayout()
        painter.save()
        painter.setClipRect(area)
        text_layout.draw(painter, QPointF(area.left(), area.top()))
        painter.restore()
        detail = QRect(
            area.left() + 12, area.bottom() + 3, max(0, area.width() - 12), detail_metrics.height()
        )
        painter.setFont(detail_font)
        verdict = data.get("triage")
        warning = " · Unavailable" if data.get("unavailable") else ""
        status = f" · {(verdict or 'undefined').capitalize()}"
        reserved = detail_metrics.horizontalAdvance(status + warning)
        game = detail_metrics.elidedText(
            data.get("game") or "Unassigned",
            Qt.TextElideMode.ElideRight,
            max(0, detail.width() - reserved),
        )
        text = game + status
        if data.get("browse_details") is not None:
            text = detail_metrics.elidedText(
                data["browse_details"],
                Qt.TextElideMode.ElideRight,
                max(0, detail.width() - detail_metrics.horizontalAdvance(warning)),
            )
        painter.setClipRect(card)
        painter.setPen(QColor(COLORS["text_secondary"]))
        painter.drawText(detail, Qt.AlignmentFlag.AlignVCenter, text)
        if warning:
            painter.setPen(QColor(COLORS["status_warning"]))
            painter.drawText(
                detail.adjusted(detail_metrics.horizontalAdvance(text), 0, 0, 0),
                Qt.AlignmentFlag.AlignVCenter,
                warning,
            )
        painter.setBrush(
            QColor(
                COLORS[
                    {"keep": "status_success", "discard": "status_danger"}.get(
                        verdict, "text_muted"
                    )
                ]
            )
        )
        painter.setPen(Qt.PenStyle.NoPen)
        baseline = (
            detail.top() + (detail.height() - detail_metrics.height()) / 2 + detail_metrics.ascent()
        )
        ink = detail_metrics.tightBoundingRect(text)
        center_y = baseline + ink.y() + ink.height() / 2
        painter.drawEllipse(QPointF(area.left() + 3, center_y), 3, 3)
        painter.restore()


class Rating(QWidget):
    changed = Signal(object)

    def __init__(self):
        super().__init__()
        self.value = None
        self.preview = None
        self.command_preview = None
        self.command_flash = False
        self.step = SIZES["rating"] + SIZES["rating_gap"]
        self.setFixedSize(self.step * 5, SIZES["normal"])
        self.setMouseTracking(True)
        self.setAccessibleName("Rating, one to five stars; right-click to clear")
        self.setToolTip("Click a star to rate · Right-click to clear · R then 1–5")

    def paintEvent(self, event):
        painter = QPainter(self)
        pending = self.command_preview is not None and self.preview is None
        value = (
            self.preview
            if self.preview is not None
            else (self.command_preview if pending else (self.value or 0))
        )
        for position in range(5):
            color = "rating_hover" if self.preview is not None else "rating_filled"
            tint = COLORS[color if position < value else "rating_empty"]
            if pending and position < value:
                tint = COLORS["rating_pending_high" if self.command_flash else "rating_pending_low"]
            icon(
                "star",
                tint,
                fill=position < value,
                size=SIZES["rating"],
            ).paint(painter, QRect(position * self.step + 2, 5, SIZES["rating"], SIZES["rating"]))

    def mouseMoveEvent(self, event):
        self.preview = min(5, max(1, int(event.position().x()) // self.step + 1))
        self.update()

    def leaveEvent(self, event):
        self.preview = None
        self.update()

    def mousePressEvent(self, event):
        self.changed.emit(
            None
            if event.button() == Qt.MouseButton.RightButton
            else min(5, max(1, int(event.position().x()) // self.step + 1))
        )
