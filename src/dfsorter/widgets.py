import html
from functools import lru_cache

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTextDocument,
    QTextLayout,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QLabel,
    QStyle,
    QStyledItemDelegate,
    QToolButton,
    QWidget,
)

from .app_paths import ROOT
from .theme import COLORS, FONT_SIZES, SIZES, font, role

ICONS = ROOT / "resources/icons"
CLIP_ROLE = Qt.ItemDataRole.UserRole + 1
FOLDER_ROLE = Qt.ItemDataRole.UserRole + 2


def heading(text, icon_name, heading_role="sectionHeading", row_height=None):
    row = QHBoxLayout()
    row.setSpacing(8)
    section = heading_role == "sectionHeading"
    icon_size = SIZES["icon_xl"] if section else SIZES["icon_md"]
    box_size = SIZES["normal"] if section else icon_size + 4
    glyph = QLabel()
    glyph.setProperty("headingIcon", icon_name)
    glyph.setProperty("headingIconSize", icon_size)
    glyph.setProperty("headingIconColorRole", "heading_icon_foreground")
    glyph.setFixedSize(box_size, min(box_size, row_height or box_size))
    glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
    glyph.setPixmap(
        icon(icon_name, COLORS["heading_icon_foreground"], size=icon_size).pixmap(
            icon_size, icon_size
        )
    )
    label = QLabel(text)
    role(label, heading_role)
    label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    label.setContentsMargins(0, 0, 0, 4)
    if row_height is not None:
        label.setFixedHeight(max(box_size, row_height))
    row.addWidget(glyph, 0, Qt.AlignmentFlag.AlignVCenter)
    row.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
    row.addStretch()
    return row, label


class VerdictBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.counts = (0, 0, 0)
        self.setFixedHeight(16)
        self.setMinimumWidth(120)
        self.setAccessibleName("No clips")

    def set_counts(self, keep, discard, pending):
        self.counts = (keep, discard, pending)
        text = f"{keep} Keep, {discard} Discard, {pending} Pending"
        self.setToolTip(text)
        self.setAccessibleName(text)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(0, 0, -1, -1), 5, 5)
        painter.setClipPath(path)
        painter.fillRect(self.rect(), QColor(COLORS["surface_pressed"]))
        total = sum(self.counts)
        if not total:
            return
        widths = [round(self.width() * count / total) for count in self.counts]
        for index, count in enumerate(self.counts):
            if count and widths[index] == 0:
                widths[index] = 1
        widths[-1] += self.width() - sum(widths)
        left = 0
        for width, color in zip(
            widths,
            ("status_success", "status_danger", "text_muted"),
            strict=True,
        ):
            if width > 0:
                painter.fillRect(left, 0, width, self.height(), QColor(COLORS[color]))
            left += width


class SessionProgressBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.states = ()
        self.processed = 0
        self.last_processed = 0
        self.setFixedHeight(48)
        self.setMinimumWidth(120)

    def set_states(self, states, processed, last_processed):
        self.states = tuple(states)
        self.processed = processed
        self.last_processed = last_processed
        total = len(self.states)
        self.setAccessibleName(f"{processed} of {total} clips processed")
        self.setToolTip(
            f"{processed} of {total} clips processed; cursor after clip {last_processed}"
        )
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        total = len(self.states)
        bar_top = 26
        bar_height = 20
        bar_width = self.width()
        painter.fillRect(QRect(0, bar_top, bar_width, bar_height), QColor(COLORS["surface_pressed"]))
        if total:
            for index, state in enumerate(self.states):
                left = round(index * bar_width / total)
                right = round((index + 1) * bar_width / total)
                if right <= left:
                    continue
                segment = QRect(left, bar_top, right - left, bar_height)
                color = {
                    "keep": "status_success",
                    "discard": "status_danger",
                    "pending": "text_muted",
                    "unavailable": "status_warning",
                }[state]
                painter.fillRect(segment, QColor(COLORS[color]))
                if state == "unavailable":
                    painter.save()
                    painter.setClipRect(segment)
                    painter.setPen(QPen(QColor(COLORS["status_warning_soft"]), 2))
                    for offset in range(left - bar_height, right + bar_height, 7):
                        painter.drawLine(offset, bar_top + bar_height, offset + bar_height, bar_top)
                    painter.restore()
        cursor = round(self.last_processed * bar_width / total) if total else 0
        cursor = max(0, min(bar_width - 2, cursor))
        label = f"{self.processed} processed ({self.processed / total:.0%})" if total else "0 processed (0%)"
        tag_font = font("sm", "semibold", base=painter.font())
        painter.setFont(tag_font)
        metrics = painter.fontMetrics()
        tag_width = metrics.horizontalAdvance(label) + 16
        tag_left = max(0, min(bar_width - tag_width, cursor - tag_width // 2))
        tag_right = tag_left + tag_width
        tail_left = max(tag_left, min(tag_right - 12, cursor - 6))
        tail_right = tail_left + 12
        tag = QPainterPath()
        tag.moveTo(tag_left, 0)
        tag.lineTo(tag_right, 0)
        tag.lineTo(tag_right, 19)
        tag.lineTo(tail_right, 19)
        tag.lineTo(cursor, 25)
        tag.lineTo(tail_left, 19)
        tag.lineTo(tag_left, 19)
        tag.closeSubpath()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillPath(tag, QColor(COLORS["accent_default"]))
        painter.setPen(QColor(COLORS["text_inverse"]))
        painter.drawText(QRect(tag_left, 0, tag_width, 19), Qt.AlignmentFlag.AlignCenter, label)
        painter.fillRect(QRect(cursor, bar_top, 2, bar_height), QColor(COLORS["accent_default"]))


class EdgeChevron(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def paintEvent(self, event):
        painter = QPainter(self)
        border = QColor(COLORS["border_default"])
        muted = QColor(COLORS["text_muted"])
        color = QColor(
            round(border.red() * 0.6 + muted.red() * 0.4),
            round(border.green() * 0.6 + muted.green() * 0.4),
            round(border.blue() * 0.6 + muted.blue() * 0.4),
        )
        pen = QPen(color, 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawLine(4, 0, 1, 3)
        painter.drawLine(1, 3, 4, 6)


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


def tag_prefix(clip, rich=False, on_video=False, size_role="library_title"):
    value = (clip.get("tag") or "").strip()
    if not value:
        return ""
    text = f"[{value}]"
    if rich:
        color = COLORS["player_chrome_tag" if on_video else "tag"]
        size = FONT_SIZES["fullscreen_title_tag" if on_video else size_role]
        return f'<b style="color:{color};font-size:{size}px">{html.escape(text)}</b> '
    return text + " "


@lru_cache(maxsize=128)
def icon(name, color=None, fill=False, size=24, y_offset=0, right_padding=0):
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
            pixmap = QPixmap((size + right_padding) * scale, size * scale)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            if y_offset:
                painter.translate(0, y_offset * scale)
            QSvgRenderer(data).render(painter, QRectF(0, 0, size * scale, size * scale))
            painter.end()
            pixmap.setDevicePixelRatio(scale)
            result.addPixmap(pixmap, mode, state)
    return result


def set_icon(control, name, color_role=None, *, size=24, y_offset=0, right_padding=0):
    control.setProperty("iconName", name)
    control.setProperty("iconColorRole", color_role)
    control.setProperty("iconRenderSize", size)
    control.setProperty("iconYOffset", y_offset)
    control.setProperty("iconRightPadding", right_padding)
    control.setIcon(
        icon(
            name,
            COLORS[color_role] if color_role else None,
            size=size,
            y_offset=y_offset,
            right_padding=right_padding,
        )
    )


def refresh_icons(root):
    icon.cache_clear()
    for control in root.findChildren(QAbstractButton):
        name = control.property("iconName")
        if name:
            color_role = control.property("iconColorRole")
            control.setIcon(
                icon(
                    name,
                    COLORS[color_role] if color_role else None,
                    size=control.property("iconRenderSize") or 24,
                    y_offset=control.property("iconYOffset") or 0,
                    right_padding=control.property("iconRightPadding") or 0,
                )
            )


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
        data = index.data(CLIP_ROLE) or {}
        browse = data.get("browse_details") is not None
        compact_card = data.get("compact_card", False)
        title_size = "card_title" if browse or compact_card else "library_title"
        height = (
            QFontMetrics(font(title_size, "semibold" if compact_card else "bold", base=option.font)).height()
            + QFontMetrics(font("xs" if compact_card else "sm", base=option.font)).height()
            + 14
        )
        minimum = SIZES["browse_card"] if browse else SIZES["compact_card" if compact_card else "card"]
        return QSize(100, max(minimum, height) + SIZES["card_gap"])

    def paint(self, painter, option, index):
        painter.save()
        painter.setClipRect(option.rect)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        data = index.data(CLIP_ROLE) or {}
        browse = data.get("browse_details") is not None
        card = option.rect.adjusted(1, 1, -1, -SIZES["card_gap"] - 1)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        compact_card = data.get("compact_card", False)
        active_card = option.rect.adjusted(8 if browse else 1, 0, -1, 0)
        previous_index = index.siblingAtRow(index.row() - 1)
        previous_active = previous_index.isValid() and (
            self.parent().selectionModel().isSelected(previous_index)
            or self.parent().library_hover_row == previous_index.row()
        )
        if selected or hovered:
            painter.setBrush(QColor(COLORS["accent_selection" if selected else "surface_hover"]))
            painter.setPen(Qt.PenStyle.NoPen)
            if selected and compact_card:
                painter.drawRect(active_card)
            else:
                painter.drawRoundedRect(active_card, 3, 3)
        elif index.row() > 0 and not previous_active:
            painter.setPen(QColor(COLORS["border_subtle"]))
            painter.drawLine(
                card.left() + SIZES["card_padding"] + (8 if browse else 0),
                option.rect.top(),
                card.right() - SIZES["card_padding"],
                option.rect.top(),
            )
        if focused:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QColor(COLORS["focus"]))
            if selected and compact_card:
                painter.drawRect(active_card)
            else:
                painter.drawRoundedRect(active_card if selected or hovered else card, 3, 3)
        if selected and not browse:
            painter.fillRect(
                QRect(active_card.left(), active_card.top(), 2, active_card.height()),
                QColor(COLORS["accent_default"]),
            )
        compact_time = data.get("compact_time")
        metadata_row = not browse
        title_size = "card_title" if browse or compact_card else "library_title"
        title_font = font(title_size, "semibold" if compact_card else "bold", base=option.font)
        detail_font = font("xs" if compact_card else "sm", base=option.font)
        title_metrics = QFontMetrics(title_font)
        detail_metrics = QFontMetrics(detail_font)
        content_left = card.left() + SIZES["card_padding"] + (8 if browse else 0)
        if browse:
            thumbnail = QRect(content_left, card.top() + (card.height() - SIZES["thumbnail_height"]) // 2,
                              SIZES["thumbnail_width"], SIZES["thumbnail_height"])
            painter.fillRect(thumbnail, QColor(COLORS["surface_pressed"]))
            picture = data.get("thumbnail")
            if picture is not None and not picture.isNull():
                painter.drawImage(thumbnail, picture)
            if selected:
                outline = QColor(COLORS["accent_default"])
                outline.setAlpha(140)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(outline, 1))
                painter.drawRect(thumbnail.adjusted(0, 0, -1, -1))
            content_left = thumbnail.right() + 11
        if metadata_row:
            content_left += SIZES["card_dot_space"]
        content_right = card.right() - SIZES["card_padding"]
        time_rect = None
        if compact_time is not None:
            time_width = min(
                detail_metrics.horizontalAdvance(compact_time), max(0, card.width() // 4)
            )
            time_rect = QRect(content_right - time_width, card.top(), time_width, card.height())
            content_right = time_rect.left() - 8
        area = QRect(
            content_left,
            card.top(),
            max(0, content_right - content_left),
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
        text = document.toPlainText()

        def layout_for(prefix_length):
            clipped = prefix_length < len(text)
            rendered = text[:prefix_length] + ("…" if clipped else "")
            visible_formats = []
            ellipsis_format = None
            for span in formats:
                if span.start <= max(0, prefix_length - 1) < span.start + span.length:
                    ellipsis_format = span.format
                length = min(span.start + span.length, prefix_length) - span.start
                if length > 0:
                    visible = QTextLayout.FormatRange()
                    visible.start = span.start
                    visible.length = length
                    visible.format = span.format
                    visible_formats.append(visible)
            if clipped and ellipsis_format is not None:
                ellipsis = QTextLayout.FormatRange()
                ellipsis.start = prefix_length
                ellipsis.length = 1
                ellipsis.format = ellipsis_format
                visible_formats.append(ellipsis)
            result = QTextLayout(rendered, title_font)
            result.setFormats(visible_formats)
            result.beginLayout()
            result_line = result.createLine()
            result_line.setLineWidth(1_000_000)
            result.endLayout()
            return result, result_line

        text_layout, line = layout_for(len(text))
        if line.naturalTextWidth() > area.width():
            low, high = 0, len(text)
            while low < high:
                middle = (low + high + 1) // 2
                candidate, candidate_line = layout_for(middle)
                if candidate_line.naturalTextWidth() <= area.width():
                    low = middle
                else:
                    high = middle - 1
            text_layout, line = layout_for(low)
        line_height = max(title_metrics.height(), round(line.height()))
        line_gap = 3 if compact_card else 2
        block_height = line_height + line_gap + detail_metrics.height()
        optical_y = -1 if metadata_row else 0
        text_y = optical_y + (1 if compact_card else 0)
        area.moveTop(card.top() + (card.height() - block_height) // 2 + text_y)
        area.setHeight(line_height)
        painter.save()
        painter.setClipRect(area)
        text_layout.draw(painter, QPointF(area.left(), area.top()))
        painter.restore()
        detail_left = area.left() + (12 if browse else 0)
        detail = QRect(
            detail_left,
            area.bottom() + line_gap + 1,
            max(0, content_right - detail_left),
            detail_metrics.height(),
        )
        if time_rect is not None:
            time_rect.translate(0, optical_y)
            painter.setFont(detail_font)
            painter.setPen(QColor(COLORS["text_secondary"]))
            painter.drawText(
                time_rect,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                compact_time,
            )
        painter.setFont(detail_font)
        verdict = data.get("triage")
        warning = "  Unavailable" if data.get("unavailable") else ""
        rating = data.get("rating")
        rating_text = f"R{rating}" if rating is not None else ""
        rating_font = font("xs" if compact_card else "sm", "bold", base=option.font)
        rating_metrics = QFontMetrics(rating_font)
        separator = " · " if rating is not None else ""
        folder_separator = " · "
        folder = data.get("folder") or "Unlinked"
        fixed_width = (
            detail_metrics.horizontalAdvance(separator)
            + rating_metrics.horizontalAdvance(rating_text)
            + detail_metrics.horizontalAdvance(folder_separator + warning)
            + (13 if warning else 0)
        )
        flexible_width = max(0, detail.width() - fixed_width)
        folder = detail_metrics.elidedText(
            folder,
            Qt.TextElideMode.ElideMiddle,
            min(detail_metrics.horizontalAdvance(folder), flexible_width // 2),
        )
        folder_width = detail_metrics.horizontalAdvance(folder)
        reserved = (
            fixed_width + folder_width
        )
        game = detail_metrics.elidedText(
            data.get("game") or "Unassigned",
            Qt.TextElideMode.ElideRight,
            max(0, detail.width() - reserved),
        )
        text = game + separator + rating_text + folder_separator + folder
        if data.get("browse_details") is not None:
            text = detail_metrics.elidedText(
                data["browse_details"],
                Qt.TextElideMode.ElideRight,
                max(0, detail.width() - detail_metrics.horizontalAdvance(warning) - (13 if warning else 0)),
            )
        painter.setClipRect(card)
        painter.setPen(QColor(COLORS["text_secondary"]))
        if data.get("browse_details") is not None:
            painter.drawText(detail, Qt.AlignmentFlag.AlignVCenter, text)
            warning_offset = detail_metrics.horizontalAdvance(text)
        else:
            game_width = detail_metrics.horizontalAdvance(game)
            separator_width = detail_metrics.horizontalAdvance(separator)
            rating_width = rating_metrics.horizontalAdvance(rating_text)
            folder_separator_width = detail_metrics.horizontalAdvance(folder_separator)
            painter.drawText(detail, Qt.AlignmentFlag.AlignVCenter, game)
            painter.drawText(
                detail.adjusted(game_width, 0, 0, 0),
                Qt.AlignmentFlag.AlignVCenter,
                separator,
            )
            if rating is not None:
                painter.setFont(rating_font)
                painter.setPen(QColor(COLORS[f"rating_label_{rating}"]))
                painter.drawText(
                    detail.adjusted(game_width + separator_width, 0, 0, 0),
                    Qt.AlignmentFlag.AlignVCenter,
                    rating_text,
                )
            painter.setFont(detail_font)
            painter.setPen(QColor(COLORS["text_secondary"]))
            folder_offset = game_width + separator_width + rating_width
            painter.drawText(
                detail.adjusted(folder_offset, 0, 0, 0),
                Qt.AlignmentFlag.AlignVCenter,
                folder_separator + folder,
            )
            warning_offset = (
                game_width
                + separator_width
                + rating_width
                + folder_separator_width
                + folder_width
            )
        if warning:
            painter.setPen(QColor(COLORS["status_warning"]))
            warning_x = detail.left() + warning_offset + 3
            warning_icon = icon("triangle-alert", COLORS["status_warning"], size=12)
            warning_icon.paint(painter, QRect(warning_x, detail.center().y() - 6, 12, 12))
            painter.drawText(
                detail.adjusted(warning_offset + 13, 0, 0, 0),
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
        if metadata_row:
            center = QPointF(
                card.left() + SIZES["card_padding"] + 4,
                card.center().y() + optical_y + (2 if compact_card else 0),
            )
        else:
            baseline = (
                detail.top() + (detail.height() - detail_metrics.height()) / 2
                + detail_metrics.ascent()
            )
            ink = detail_metrics.tightBoundingRect(text)
            center_y = baseline + ink.y() + ink.height() / 2 - 1
            center = QPointF(area.left() + 3, center_y)
        painter.drawEllipse(center, 4, 4)
        painter.restore()


class CaptureFolderDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        path_height = QFontMetrics(font("md", "semibold", base=option.font)).height()
        summary_height = QFontMetrics(font("sm", base=option.font)).height()
        detail_height = QFontMetrics(font("xs", base=option.font)).height()
        return QSize(100, path_height + summary_height + detail_height + 22)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        data = index.data(FOLDER_ROLE) or {}
        row = option.rect.adjusted(1, 1, -1, -1)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        if selected or hovered:
            painter.setBrush(QColor(COLORS["accent_selection" if selected else "surface_hover"]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(row, 3, 3)
        else:
            painter.setPen(QColor(COLORS["border_subtle"]))
            painter.drawLine(row.left() + 8, row.bottom(), row.right() - 8, row.bottom())
        if focused:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QColor(COLORS["focus"]))
            painter.drawRoundedRect(row, 3, 3)
        if selected:
            painter.fillRect(
                row.left() + 1,
                row.top() + 5,
                2,
                row.height() - 10,
                QColor(COLORS["accent_default"]),
            )

        left = row.left() + 10
        right = row.right() - 10
        path_font = font("md", "semibold", base=option.font)
        summary_font = font("sm", base=option.font)
        detail_font = font("xs", base=option.font)
        path_metrics = QFontMetrics(path_font)
        summary_metrics = QFontMetrics(summary_font)
        detail_metrics = QFontMetrics(detail_font)
        top = row.top() + 6

        status = data.get("status", "")
        status_width = summary_metrics.horizontalAdvance(status)
        dot_width = 14 if status else 0
        status_rect = QRect(right - status_width, top, status_width, path_metrics.height())
        painter.setFont(summary_font)
        painter.setPen(QColor(COLORS["text_secondary"]))
        painter.drawText(status_rect, Qt.AlignmentFlag.AlignVCenter, status)
        if status:
            dot_color = "status_success" if data.get("enabled") else "status_warning"
            painter.setBrush(QColor(COLORS[dot_color]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(status_rect.left() - 8, status_rect.center().y()), 3, 3)

        path_width = max(0, right - left - status_width - dot_width - 8)
        path = path_metrics.elidedText(
            data.get("path", str(index.data())), Qt.TextElideMode.ElideMiddle, path_width
        )
        painter.setFont(path_font)
        painter.setPen(QColor(COLORS["text_primary"]))
        painter.drawText(
            QRect(left, top, path_width, path_metrics.height()),
            Qt.AlignmentFlag.AlignVCenter,
            path,
        )

        summary_top = top + path_metrics.height() + 2
        painter.setFont(summary_font)
        painter.setPen(QColor(COLORS["text_secondary"]))
        summary_new = data.get("summary_new", "")
        summary_new_width = min(
            summary_metrics.horizontalAdvance(summary_new), right - left
        )
        summary_width = right - left - summary_new_width
        painter.drawText(
            QRect(left, summary_top, summary_width, summary_metrics.height()),
            Qt.AlignmentFlag.AlignVCenter,
            summary_metrics.elidedText(
                data.get("summary", ""), Qt.TextElideMode.ElideRight, summary_width
            ),
        )
        if summary_new:
            painter.setPen(QColor(COLORS["accent_default"]))
            painter.drawText(
                QRect(left + summary_width, summary_top, summary_new_width, summary_metrics.height()),
                Qt.AlignmentFlag.AlignVCenter,
                summary_metrics.elidedText(
                    summary_new, Qt.TextElideMode.ElideRight, summary_new_width
                ),
            )
        detail_top = summary_top + summary_metrics.height() + 2
        painter.setFont(detail_font)
        game_details = data.get("game_details")
        if game_details:
            detail_left = left
            for position, detail in enumerate(game_details):
                prefix = ("   " if position else "") + detail["text"]
                new_text = f" ({detail['new']} new)" if detail["new"] else ""
                remaining = right - detail_left
                combined = prefix + new_text
                if detail_metrics.horizontalAdvance(combined) > remaining:
                    painter.setPen(QColor(COLORS["text_muted"]))
                    painter.drawText(
                        QRect(detail_left, detail_top, remaining, detail_metrics.height()),
                        Qt.AlignmentFlag.AlignVCenter,
                        detail_metrics.elidedText(
                            combined, Qt.TextElideMode.ElideRight, remaining
                        ),
                    )
                    break
                painter.setPen(QColor(COLORS["text_muted"]))
                painter.drawText(
                    QRect(detail_left, detail_top, remaining, detail_metrics.height()),
                    Qt.AlignmentFlag.AlignVCenter,
                    prefix,
                )
                detail_left += detail_metrics.horizontalAdvance(prefix)
                if new_text:
                    painter.setPen(QColor(COLORS["accent_default"]))
                    painter.drawText(
                        QRect(detail_left, detail_top, right - detail_left, detail_metrics.height()),
                        Qt.AlignmentFlag.AlignVCenter,
                        new_text,
                    )
                    detail_left += detail_metrics.horizontalAdvance(new_text)
        else:
            painter.setPen(QColor(COLORS["text_muted"]))
            painter.drawText(
                QRect(left, detail_top, right - left, detail_metrics.height()),
                Qt.AlignmentFlag.AlignVCenter,
                detail_metrics.elidedText(
                    data.get("details", ""), Qt.TextElideMode.ElideRight, right - left
                ),
            )
        painter.restore()


class Rating(QWidget):
    changed = Signal(object)

    def __init__(self):
        super().__init__()
        self.value = None
        self.preview = None
        self.command_preview = None
        self.step = SIZES["rating"] + SIZES["rating_gap"]
        self.setFixedSize(self.step * 5, SIZES["toolbar"])
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
                tint = COLORS["rating_pending_low"]
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
