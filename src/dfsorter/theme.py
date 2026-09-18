from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

COLORS = {
    "bg_app": "#1E2228",
    "bg_panel": "#181C22",
    "bg_panel_alt": "#15191F",
    "bg_surface": "#252B33",
    "bg_surface_hover": "#2D3540",
    "bg_surface_pressed": "#343E4A",
    "bg_input": "#12161C",
    "bg_video": "#000000",
    "border_subtle": "#2B323C",
    "border_default": "#3A4350",
    "border_strong": "#4B5665",
    "separator": "#303741",
    "text_primary": "#E6E9ED",
    "text_secondary": "#A9B0BA",
    "text_working_title": "#C7CDD5",
    "text_muted": "#77808C",
    "text_disabled": "#59616C",
    "text_inverse": "#111317",
    "accent": "#41B8C7",
    "accent_hover": "#56C9D7",
    "accent_pressed": "#3096A4",
    "accent_muted": "#17373D",
    "accent_selection": "#244A53",
    "accent_focus": "#59D2E2",
    "success": "#62C98D",
    "success_muted": "#1C3A2A",
    "warning": "#D9A441",
    "warning_muted": "#3A2D16",
    "danger": "#D9686A",
    "danger_hover": "#E47D7F",
    "danger_muted": "#3A2022",
    "info": "#6AA9E9",
    "rating_filled": "#E8C45A",
    "rating_hover": "#F0D16F",
    "rating_empty": "#69717D",
    "command_focus": "#141B21",
    "timeline_track": "#3A424D",
    "timeline_progress": "#617080",
    "scrollbar_hover": "#56616F",
    "tooltip": "#11151A",
}
FONT_SIZES = {"xs": 11, "sm": 12, "md": 13, "base": 14, "lg": 16, "xl": 20, "xxl": 26}
WEIGHTS = {"regular": 400, "medium": 500, "semibold": 600, "bold": 700}
SPACING = (4, 8, 12, 16, 24, 32)
RADII = {"none": 0, "sm": 3, "md": 5, "lg": 7, "control": 4}
SIZES = {
    "compact": 24,
    "normal": 28,
    "large": 32,
    "toolbar": 28,
    "nav": 34,
    "card": 48,
    "card_gap": 4,
    "panel_padding": 12,
    "timeline": 7,
    "icon_xs": 12,
    "icon_sm": 14,
    "icon_md": 16,
    "icon_lg": 20,
    "icon_xl": 24,
    "rating": 18,
    "rating_gap": 4,
}


def font(size="md", weight="regular", base=None):
    result = QFont(base) if base is not None else QFont()
    result.setPixelSize(FONT_SIZES[size])
    result.setWeight(QFont.Weight(WEIGHTS[weight]))
    return result


def role(widget, value):
    widget.setProperty("role", value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def stylesheet():
    values = {**COLORS, **SIZES, **{f"font_{key}": value for key, value in FONT_SIZES.items()}}
    return (
        """
        QWidget { background: %(bg_app)s; color: %(text_primary)s; }
        QLabel { background: transparent; }
        QWidget[role="panel"] { background: %(bg_panel)s; }
        QLabel#muted, QLabel[role="secondary"] { color: %(text_secondary)s; font-size: %(font_sm)spx; }
        QLabel[role="muted"] { color: %(text_muted)s; font-size: %(font_sm)spx; }
        QLabel[role="heading"] { font-size: %(font_xl)spx; font-weight: 600; }
        QLabel[role="paneHeading"] { font-size: %(font_base)spx; font-weight: 600; color: %(text_primary)s; }
        QWidget#sessionHeader { background: transparent; }
        QLabel#workingTitle { font-size: %(font_lg)spx; font-weight: 600; }
        QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {
            background: %(bg_input)s; border: 1px solid %(border_subtle)s;
            border-radius: 4px; padding: 4px 8px; selection-background-color: %(accent_selection)s;
            selection-color: %(text_primary)s;
        }
        QLineEdit, QComboBox, QSpinBox { min-height: 18px; }
        QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover, QComboBox:hover, QSpinBox:hover {
            border-color: %(border_default)s;
        }
        QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus {
            border-color: %(accent_focus)s;
        }
        QLineEdit#command:focus { background: %(command_focus)s; border-color: %(accent_focus)s; }
        QPushButton, QToolButton {
            background: %(bg_surface)s; border: 1px solid %(border_default)s;
            border-radius: 4px; padding: 4px 8px; min-height: 18px;
        }
        QPushButton:hover, QToolButton:hover { background: %(bg_surface_hover)s; }
        QPushButton:pressed, QToolButton:pressed { background: %(bg_surface_pressed)s; }
        QPushButton:checked, QToolButton:checked { background: %(accent_muted)s; border-color: %(accent)s; }
        QPushButton[role="primary"] { background: %(accent_muted)s; border-color: %(accent)s; }
        QPushButton[role="primary"]:hover { background: %(accent_selection)s; }
        QPushButton[role="danger"] { color: %(danger)s; border-color: %(danger)s; background: %(danger_muted)s; }
        QPushButton[role="danger"]:hover { color: %(danger_hover)s; }
        QPushButton[role="keep"]:checked { background: %(success_muted)s; color: %(success)s; border-color: %(success)s; }
        QPushButton[role="discard"]:checked { background: %(danger_muted)s; color: %(danger)s; border-color: %(danger)s; }
        QPushButton[role="undefined"]:checked { background: %(bg_surface_pressed)s; color: %(text_secondary)s; border-color: %(border_strong)s; }
        QPushButton:focus, QToolButton:focus, QCheckBox:focus { border: 1px solid %(accent_focus)s; }
        QToolButton#settingsMenuButton::menu-indicator { image: none; width: 0px; }
        QToolButton { background: transparent; border: 1px solid transparent; padding: 2px; }
        QWidget#navigationStrip { background: %(bg_panel)s; border-bottom: 1px solid %(separator)s; }
        QToolButton[navUtility="true"] { padding: 3px 2px 1px 2px; }
        QPushButton#navigation {
            background: transparent; border: 1px solid transparent;
            border-top: 2px solid transparent; border-bottom: 1px solid %(separator)s;
            border-radius: 0; color: %(text_secondary)s; font-size: %(font_base)spx;
            font-weight: 500; padding: 0px 16px; min-height: 33px;
        }
        QPushButton#navigation:hover { color: %(text_primary)s; background: %(bg_surface)s; }
        QPushButton#navigation:checked {
            background: %(bg_app)s; color: %(text_primary)s; font-weight: 600;
            border-left-color: %(separator)s; border-right-color: %(separator)s;
            border-top-color: %(accent)s; border-bottom-color: %(bg_app)s;
        }
        QPushButton#navigation:disabled {
            background: transparent; color: %(text_disabled)s;
            border-top-color: transparent; border-left-color: transparent;
            border-right-color: transparent;
        }
        QListWidget { background: %(bg_panel)s; border: none; padding: 4px; outline: none; }
        QListWidget::item { padding: 4px; }
        QListWidget::item:selected { background: %(accent_selection)s; color: %(text_primary)s; }
        QListWidget::item:hover { background: %(bg_surface_hover)s; }
        QComboBox QAbstractItemView { background: %(bg_panel)s; selection-background-color: %(accent_selection)s; }
        QMenuBar, QMenu { background: %(bg_panel)s; }
        QMenuBar::item { background: transparent; border: none; padding: 2px 4px; }
        QMenu { border: 1px solid %(border_default)s; }
        QMenu::item { padding: 6px 24px; }
        QMenu::item:selected, QMenuBar::item:selected { background: %(accent_selection)s; }
        QMenu::separator { height: 1px; background: %(separator)s; margin: 4px 8px; }
        QSplitter::handle { background: %(separator)s; }
        QSplitter::handle:hover { background: %(border_strong)s; }
        QSlider::groove:horizontal { height: 4px; background: %(timeline_track)s; border-radius: 2px; }
        QSlider#timeline::groove:horizontal { height: %(timeline)spx; border-radius: 3px; }
        QSlider::sub-page:horizontal { background: %(timeline_progress)s; border-radius: 2px; }
        QSlider::handle:horizontal { width: 12px; margin: -4px 0; background: %(accent)s; border-radius: 3px; }
        QSlider::handle:horizontal:hover { background: %(accent_hover)s; }
        QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
        QScrollBar:horizontal { background: transparent; height: 8px; margin: 0; }
        QScrollBar::handle { background: %(timeline_track)s; border-radius: 3px; min-height: 24px; min-width: 24px; }
        QScrollBar::handle:hover { background: %(scrollbar_hover)s; }
        QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
        QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
        QToolTip { background: %(tooltip)s; border: 1px solid %(border_default)s;
            color: %(text_primary)s; padding: 6px 8px; border-radius: 4px; }
        QWidget[role="error"] { color: %(danger)s; }
        QWidget[role="warning"] { color: %(warning)s; }
        QWidget[role="success"] { color: %(success)s; }
        QPushButton:disabled, QToolButton:disabled, QLineEdit:disabled, QComboBox:disabled,
        QSpinBox:disabled { background: %(bg_panel)s; border-color: %(border_subtle)s; color: %(text_disabled)s; }
        QLabel:disabled, QMenu::item:disabled, QMenuBar::item:disabled { color: %(text_disabled)s; }
    """
        % values
    )


def apply_theme(application):
    application.setStyle("Fusion")
    available = set(QFontDatabase.families())
    family = next(
        (name for name in ("Segoe UI", "Inter", "Arial") if name in available), "sans-serif"
    )
    application.setFont(font(base=QFont(family)))
    palette = QPalette()
    for name, token in {
        "Window": "bg_app",
        "WindowText": "text_primary",
        "Base": "bg_input",
        "AlternateBase": "bg_panel_alt",
        "Text": "text_primary",
        "Button": "bg_surface",
        "ButtonText": "text_primary",
        "Highlight": "accent_selection",
        "HighlightedText": "text_primary",
        "PlaceholderText": "text_muted",
        "ToolTipBase": "tooltip",
        "ToolTipText": "text_primary",
        "Link": "accent",
    }.items():
        palette.setColor(getattr(QPalette.ColorRole, name), QColor(COLORS[token]))
    for name in ("Text", "WindowText", "ButtonText", "PlaceholderText"):
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            getattr(QPalette.ColorRole, name),
            QColor(COLORS["text_disabled"]),
        )
    application.setPalette(palette)
    application.setStyleSheet(stylesheet())
