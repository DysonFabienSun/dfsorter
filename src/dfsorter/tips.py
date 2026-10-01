"""Editable Editing tips and their per-run rotation state."""

import random

import yaml
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from .theme import COLORS, font
from .widgets import icon


class TipLibrary:
    def __init__(self, directory):
        self.tips = []
        self.shown = set()
        self.errors = []
        for path in sorted(directory.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or not isinstance(data.get("tips"), list):
                    raise ValueError("expected a mapping with a tips list")
                game = data.get("game")
                if path.name == "default.yaml":
                    if game is not None:
                        raise ValueError("default tips cannot specify a game")
                elif not isinstance(game, str) or not game.strip():
                    raise ValueError("game tips require a game name")
                entries = []
                for index, message in enumerate(data["tips"]):
                    if not isinstance(message, str) or not message.strip():
                        raise ValueError(f"tip {index + 1} must be nonempty text")
                    entries.append((path.name, index, game, message.strip()))
                self.tips.extend(entries)
            except (OSError, ValueError, yaml.YAMLError) as error:
                self.errors.append(f"Tips {path.name}: {error}")

    def next(self, game):
        available = [tip for tip in self.tips if tip[2] is None or tip[2] == game]
        if not available:
            return None
        unseen = [tip for tip in available if tip[:2] not in self.shown]
        if not unseen:
            self.shown.difference_update(tip[:2] for tip in available)
            unseen = available
        chosen = random.choice(unseen)
        self.shown.add(chosen[:2])
        return chosen[3]


class TipWidget(QWidget):
    def __init__(self, parent=None, size=12):
        super().__init__(parent)
        self.message = ""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.set_tip_size(size)

    def set_tip_size(self, size):
        self.tip_size = size
        self.setFont(font({11: "xs", 12: "sm", 13: "md"}[size]))
        self.refresh_theme()
        self.updateGeometry()

    def set_message(self, message):
        self.message = message or ""
        self.setAccessibleName(self.message)
        self.setToolTip(self.message)
        self.update()

    def refresh_theme(self):
        self.symbol = icon("info", COLORS["accent_default"], size=self.tip_size).pixmap(
            self.tip_size, self.tip_size
        )
        self.update()

    def sizeHint(self):
        result = super().sizeHint()
        result.setHeight(max(self.tip_size, self.fontMetrics().height()))
        return result

    def paintEvent(self, event):
        if not self.message:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setPen(COLORS["accent_default"])
        icon_width = self.tip_size
        spacing = 4
        available_text = max(0, self.width() - icon_width - spacing)
        display = self.fontMetrics().elidedText(
            self.message, Qt.TextElideMode.ElideRight, available_text
        )
        text_width = self.fontMetrics().horizontalAdvance(display)
        left = max(0, self.width() - icon_width - spacing - text_width)
        painter.drawPixmap(
            QRectF(left, (self.height() - self.tip_size) / 2, self.tip_size, self.tip_size),
            self.symbol,
            QRectF(self.symbol.rect()),
        )
        painter.drawText(
            left + icon_width + spacing, 0, text_width, self.height(),
            Qt.AlignmentFlag.AlignVCenter, display,
        )
