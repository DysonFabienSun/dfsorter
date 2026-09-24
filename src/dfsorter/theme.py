from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QProxyStyle, QStyle

THEMES = {
    "light": {
        "surface_canvas": "#F3F5F7",
        "surface_workspace": "#FFFFFF",
        "surface_sidebar": "#F8F9FA",
        "surface_panel": "#FFFFFF",
        "surface_subtle": "#F6F8FA",
        "surface_control": "#FFFFFF",
        "surface_hover": "#EDF1F3",
        "surface_pressed": "#E4E9ED",
        "surface_video": "#000000",
        "text_primary": "#1F252B",
        "text_secondary": "#4F5B66",
        "text_muted": "#65717C",
        "text_disabled": "#A3ABB3",
        "text_inverse": "#FFFFFF",
        "border_default": "#C8D1D9",
        "border_subtle": "#DEE5EA",
        "border_strong": "#AEB8C1",
        "accent_default": "#087F8C",
        "accent_hover": "#066E79",
        "accent_pressed": "#055E68",
        "accent_soft": "#E2F2F4",
        "accent_soft_hover": "#D4EAED",
        "accent_selection": "#D9EFF1",
        "focus": "#087F8C",
        "status_success": "#247A4B",
        "status_success_soft": "#E6F4EC",
        "status_warning": "#9A6700",
        "status_warning_soft": "#FFF4D6",
        "status_danger": "#C83C43",
        "status_danger_hover": "#AD3037",
        "status_danger_soft": "#FBEAEC",
        "status_info": "#316DCA",
        "rating_filled": "#A66A00",
        "rating_hover": "#C17C00",
        "rating_empty": "#7C8791",
        "rating_pending_low": "#B9A269",
        "rating_label_1": "#A83245",
        "rating_label_2": "#A65318",
        "rating_label_3": "#806000",
        "rating_label_4": "#526C20",
        "rating_label_5": "#1F7044",
        "component_command_valid": "#EAF2FB",
        "component_timeline_track": "#C7E0E3",
        "component_timeline_progress": "#087F8C",
        "component_volume_track": "#D5E7E9",
        "component_volume_progress": "#3D929B",
        "component_clip_scrollbar_track": "#D5E7E9",
        "component_clip_scrollbar_thumb": "#3D929B",
        "component_clip_scrollbar_thumb_hover": "#087F8C",
        "component_scrollbar": "#CDD5DC",
        "component_scrollbar_hover": "#AEB8C1",
        "component_tooltip": "#252B33",
        "component_tooltip_text": "#F1F4F6",
        "tag": "#A66A00",
    },
    "dark": {
        "surface_canvas": "#181C21",
        "surface_workspace": "#1F242B",
        "surface_sidebar": "#1B2026",
        "surface_panel": "#1F242B",
        "surface_subtle": "#252B33",
        "surface_control": "#20262D",
        "surface_hover": "#2A313A",
        "surface_pressed": "#303842",
        "surface_video": "#000000",
        "text_primary": "#F1F4F6",
        "text_secondary": "#BEC6CD",
        "text_muted": "#8E99A4",
        "text_disabled": "#626C76",
        "text_inverse": "#111317",
        "border_default": "#39424C",
        "border_subtle": "#2D343D",
        "border_strong": "#515C67",
        "accent_default": "#43B6C3",
        "accent_hover": "#58C2CD",
        "accent_pressed": "#32A4B1",
        "accent_soft": "#173D43",
        "accent_soft_hover": "#1B4850",
        "accent_selection": "#20515A",
        "focus": "#4CC1CE",
        "status_success": "#62C98D",
        "status_success_soft": "#1C3A2A",
        "status_warning": "#D9A441",
        "status_warning_soft": "#3A2D16",
        "status_danger": "#EF6A70",
        "status_danger_hover": "#FF8086",
        "status_danger_soft": "#48252A",
        "status_info": "#6AA9E9",
        "rating_filled": "#E8C45A",
        "rating_hover": "#F0D16F",
        "rating_empty": "#69717D",
        "rating_pending_low": "#6D5B33",
        "rating_label_1": "#FFA0A8",
        "rating_label_2": "#FFB07A",
        "rating_label_3": "#E8C45A",
        "rating_label_4": "#C1DA82",
        "rating_label_5": "#79D7A0",
        "component_command_valid": "#172B40",
        "component_timeline_track": "#23434A",
        "component_timeline_progress": "#43B6C3",
        "component_volume_track": "#29434A",
        "component_volume_progress": "#3698A3",
        "component_clip_scrollbar_track": "#29434A",
        "component_clip_scrollbar_thumb": "#3698A3",
        "component_clip_scrollbar_thumb_hover": "#43B6C3",
        "component_scrollbar": "#3A424D",
        "component_scrollbar_hover": "#515C67",
        "component_tooltip": "#11151A",
        "component_tooltip_text": "#F1F4F6",
        "tag": "#E8C45A",
    },
}

# Custom painters import this object. Mutating it keeps those references current.
COLORS = dict(THEMES["light"])
ACTIVE_SCHEME = "light"

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
    "card_gap": 1,
    "card_padding": 7,
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


def resolved_scheme(application, mode):
    mode = str(mode or "light").casefold()
    if mode not in {"system", "light", "dark"}:
        mode = "light"
    if mode == "system":
        return "dark" if application.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
    return mode


def stylesheet():
    values = {
        **COLORS,
        **SIZES,
        **{f"font_{key}": value for key, value in FONT_SIZES.items()},
        "combo_chevron": (
            Path(__file__).resolve().parents[2] / "resources/icons/chevron-down.svg"
        ).as_posix(),
        "spin_up_chevron": (
            Path(__file__).resolve().parents[2] / "resources/icons/chevron-up.svg"
        ).as_posix(),
    }
    return (
        """
        QWidget { background: %(surface_workspace)s; color: %(text_primary)s; }
        QMainWindow { background: %(surface_canvas)s; }
        QWidget#videoSurface { background: %(surface_video)s; }
        QWidget#videoContainer { background: %(surface_canvas)s; }
        QWidget#pageLoading, QWidget#commandCover { background: %(surface_canvas)s; }
        QLabel { background: transparent; }
        QLabel#fastIndicator { color: %(accent_default)s; background: transparent; }
        QWidget[role="panel"] { background: %(surface_panel)s; }
        QWidget[role="sidebar"] { background: %(surface_sidebar)s; }
        QWidget#clipLibraryPane { border-radius: 7px; }
        QWidget[role="transparent"] { background: transparent; }
        QWidget[role="group"] { background: %(surface_subtle)s; border: 1px solid %(border_subtle)s; border-radius: 5px; }
        QWidget[role="divider"] { background: %(border_subtle)s; }
        QLabel#muted, QLabel[role="secondary"] { color: %(text_secondary)s; font-size: %(font_sm)spx; }
        QLabel[role="muted"] { color: %(text_muted)s; font-size: %(font_sm)spx; }
        QLabel[role="helper"] { color: %(text_muted)s; font-size: %(font_xs)spx; }
        QLabel[role="heading"] { font-size: %(font_xl)spx; font-weight: 600; }
        QLabel[role="sectionHeading"], QLabel[role="paneHeading"] { font-size: %(font_base)spx; font-weight: 600; color: %(text_primary)s; }
        QWidget#sessionHeader { background: transparent; }
        QLabel#workingTitle { font-size: %(font_lg)spx; font-weight: 600; }
        QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {
            background: %(surface_control)s; border: 1px solid %(border_default)s;
            border-radius: 4px; padding: 4px 8px; selection-background-color: %(accent_selection)s;
            selection-color: %(text_primary)s;
        }
        QLineEdit, QComboBox, QSpinBox { min-height: 18px; }
        QComboBox { padding: 4px 28px 4px 8px; }
        QComboBox::drop-down {
            subcontrol-origin: padding; subcontrol-position: top right;
            width: 24px; border: none; background: transparent;
        }
        QComboBox::down-arrow { image: url("%(combo_chevron)s"); width: 14px; height: 14px; }
        QSpinBox::up-button, QSpinBox::down-button {
            subcontrol-origin: border; width: 20px; border: none; background: transparent;
        }
        QSpinBox::up-button { subcontrol-position: top right; }
        QSpinBox::down-button { subcontrol-position: bottom right; }
        QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: %(surface_hover)s; }
        QSpinBox::up-button:pressed, QSpinBox::down-button:pressed { background: %(surface_pressed)s; }
        QSpinBox::up-arrow { image: url("%(spin_up_chevron)s"); width: 12px; height: 12px; }
        QSpinBox::down-arrow { image: url("%(combo_chevron)s"); width: 12px; height: 12px; }
        QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: %(border_strong)s; }
        QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus { border: 2px solid %(focus)s; padding: 3px 7px; }
        QComboBox:focus { padding: 3px 27px 3px 7px; }
        QLineEdit#command[validationState="valid"] { background: %(component_command_valid)s; }
        QLineEdit#command[validationState="incomplete"] { border-bottom: 2px solid %(status_warning)s; }
        QLineEdit#command[validationState="invalid"] { border-bottom: 2px solid %(status_danger)s; }
        QLineEdit#command[validationState="saved"] { border-bottom: 2px solid %(status_success)s; }
        QPushButton, QToolButton { background: %(surface_subtle)s; border: 1px solid %(border_subtle)s; border-radius: 4px; padding: 5px 9px; min-height: 18px; }
        QPushButton:hover, QToolButton:hover { background: %(surface_hover)s; }
        QPushButton:pressed, QToolButton:pressed { background: %(surface_pressed)s; }
        QPushButton:checked, QToolButton:checked { background: %(accent_soft)s; border-color: %(accent_default)s; }
        QPushButton[role="primary"] { background: %(accent_default)s; color: %(text_inverse)s; border-color: %(accent_default)s; font-weight: 600; }
        QPushButton[role="primary"]:hover { background: %(accent_hover)s; border-color: %(accent_hover)s; }
        QPushButton[role="primary"]:pressed { background: %(accent_pressed)s; border-color: %(accent_pressed)s; }
        QPushButton[role="prominentNeutral"] { border-color: %(border_default)s; font-weight: 600; }
        QPushButton[role="danger"], QToolButton[role="danger"] { color: %(status_danger)s; border-color: %(border_default)s; background: %(status_danger_soft)s; }
        QPushButton[role="danger"]:hover, QToolButton[role="danger"]:hover { color: %(status_danger_hover)s; border-color: %(status_danger)s; }
        QPushButton[role="keep"]:checked { background: %(status_success_soft)s; color: %(status_success)s; border-color: %(status_success)s; }
        QPushButton[role="discard"]:checked { background: %(status_danger_soft)s; color: %(status_danger)s; border-color: %(status_danger)s; }
        QPushButton[role="undefined"]:checked { background: %(surface_pressed)s; color: %(text_secondary)s; border-color: %(border_strong)s; }
        QPushButton:focus, QToolButton:focus, QCheckBox:focus { border: 2px solid %(focus)s; }
        QToolButton#settingsMenuButton::menu-indicator, QToolButton#captureFolderMenuButton::menu-indicator { image: none; width: 0px; }
        QToolButton { background: transparent; border: 1px solid transparent; padding: 2px; }
        QToolButton[sessionAction="true"] { padding: 4px 2px 0px 2px; }
        QWidget#navigationStrip { background: %(surface_sidebar)s; border-bottom: 1px solid %(border_subtle)s; }
        QPushButton[navUtility="true"] { min-height: 24px; max-height: 24px; padding: 1px 6px; }
        QToolButton[navUtility="true"] { min-height: 22px; max-height: 22px; padding: 3px 2px 1px 2px; }
        QPushButton[navUtilityStyle="framed"], QToolButton[navUtilityStyle="framed"] { background: %(surface_subtle)s; border: 1px solid %(border_subtle)s; }
        QPushButton[navUtilityStyle="framed"]:hover, QToolButton[navUtilityStyle="framed"]:hover { background: %(surface_hover)s; border-color: %(border_default)s; }
        QPushButton[navUtilityStyle="framed"]:pressed, QToolButton[navUtilityStyle="framed"]:pressed { background: %(surface_pressed)s; border-color: %(border_default)s; }
        QPushButton[navUtilityStyle="ghost"], QToolButton[navUtilityStyle="ghost"] { background: transparent; border-color: transparent; }
        QPushButton[navUtilityStyle="ghost"]:hover, QToolButton[navUtilityStyle="ghost"]:hover { background: %(surface_hover)s; border-color: transparent; }
        QPushButton[navUtilityStyle="ghost"]:pressed, QToolButton[navUtilityStyle="ghost"]:pressed { background: %(surface_pressed)s; border-color: transparent; }
        QPushButton[navUtilityStyle="ghost"]:disabled, QToolButton[navUtilityStyle="ghost"]:disabled { background: transparent; border-color: transparent; }
        QPushButton#navigation { background: transparent; border: none; border-bottom: 2px solid transparent; border-radius: 0; color: %(text_secondary)s; font-size: %(font_base)spx; font-weight: 500; padding: 0px 16px; min-height: 32px; }
        QPushButton#navigation:hover { color: %(text_primary)s; background: %(surface_hover)s; }
        QPushButton#navigation:checked { background: transparent; color: %(text_primary)s; font-weight: 600; border-bottom-color: %(accent_default)s; }
        QPushButton#navigation:disabled { background: transparent; color: %(text_disabled)s; border-bottom-color: transparent; }
        QListWidget { background: %(surface_workspace)s; border: none; padding: 4px; outline: none; }
        QListWidget#clipLibrary { padding: 0px; }
        QWidget#clipScrollTopFade, QWidget#clipScrollBottomFade { background: transparent; border: none; }
        QWidget[role="sidebar"] QListWidget { background: %(surface_sidebar)s; }
        QListWidget[contentSurface="secondary"] { background: %(surface_subtle)s; }
        QListWidget::item { padding: 2px 4px; }
        QListWidget::item:selected { background: %(accent_selection)s; color: %(text_primary)s; }
        QListWidget::item:hover { background: %(surface_hover)s; }
        QComboBox QAbstractItemView { background: %(surface_panel)s; selection-background-color: %(accent_selection)s; }
        QMenuBar, QMenu { background: %(surface_panel)s; }
        QMenuBar::item { background: transparent; border: none; padding: 2px 4px; }
        QMenu { border: 1px solid %(border_default)s; }
        QMenu::item { padding: 6px 24px; }
        QMenu::item:selected, QMenuBar::item:selected { background: %(accent_selection)s; }
        QMenu::separator { height: 1px; background: %(border_subtle)s; margin: 4px 8px; }
        QTabWidget::pane { border: 1px solid %(border_subtle)s; background: %(surface_panel)s; }
        QTabBar::tab { background: transparent; color: %(text_secondary)s; padding: 6px 12px; border-bottom: 2px solid transparent; }
        QTabBar::tab:hover { background: %(surface_hover)s; color: %(text_primary)s; }
        QTabBar::tab:selected { color: %(text_primary)s; font-weight: 600; border-bottom-color: %(accent_default)s; }
        QSplitter#workspaceSplitter::handle { background: transparent; }
        QSplitter#workspaceSplitter::handle:hover { background: %(border_subtle)s; }
        QSlider::groove:horizontal { height: 4px; background: %(component_volume_track)s; border-radius: 2px; }
        QSlider::sub-page:horizontal { background: %(component_volume_progress)s; border-radius: 2px; }
        QSlider::handle:horizontal { width: 12px; margin: -4px 0; background: %(accent_default)s; border-radius: 3px; }
        QSlider::handle:horizontal:hover { background: %(accent_hover)s; }
        QSlider#timeline::groove:horizontal { height: %(timeline)spx; background: %(component_timeline_track)s; border-radius: 3px; }
        QSlider#timeline::sub-page:horizontal { background: %(component_timeline_progress)s; border-radius: 3px; }
        QSlider#volume::groove:horizontal { height: 3px; background: %(component_volume_track)s; border-radius: 1px; }
        QSlider#volume::sub-page:horizontal { background: %(component_volume_progress)s; border-radius: 1px; }
        QSlider#volume::handle:horizontal { width: 10px; margin: -4px 0; border-radius: 3px; }
        QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
        QScrollBar:horizontal { background: transparent; height: 8px; margin: 0; }
        QScrollBar::handle { background: %(component_scrollbar)s; border-radius: 3px; min-height: 24px; min-width: 24px; }
        QScrollBar::handle:hover { background: %(component_scrollbar_hover)s; }
        QWidget#clipLibraryPane QScrollBar:vertical { background: %(component_clip_scrollbar_track)s; }
        QWidget#clipLibraryPane QScrollBar::handle { background: %(component_clip_scrollbar_thumb)s; }
        QWidget#clipLibraryPane QScrollBar::handle:hover { background: %(component_clip_scrollbar_thumb_hover)s; }
        QWidget#clipLibraryPane QScrollBar::add-page, QWidget#clipLibraryPane QScrollBar::sub-page { background: %(component_clip_scrollbar_track)s; }
        QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
        QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
        QToolTip { background: %(component_tooltip)s; border: 1px solid %(border_default)s; color: %(component_tooltip_text)s; font-size: %(font_sm)spx; padding: 0px 3px 2px 3px; border-radius: 4px; }
        QWidget[role="error"] { color: %(status_danger)s; }
        QWidget[role="warning"] { color: %(status_warning)s; }
        QWidget[role="success"] { color: %(status_success)s; }
        QPushButton:disabled, QToolButton:disabled, QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { background: %(surface_subtle)s; border-color: %(border_subtle)s; color: %(text_disabled)s; }
        QLabel:disabled, QMenu::item:disabled, QMenuBar::item:disabled { color: %(text_disabled)s; }
        """
        % values
    )


class ApplicationStyle(QProxyStyle):
    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_ToolTip_WakeUpDelay:
            return 200
        return super().styleHint(hint, option, widget, returnData)


def apply_theme(application, mode="light"):
    global ACTIVE_SCHEME
    ACTIVE_SCHEME = resolved_scheme(application, mode)
    COLORS.clear()
    COLORS.update(THEMES[ACTIVE_SCHEME])
    application.setProperty("appearanceMode", str(mode or "light").casefold())
    application.setStyle(ApplicationStyle("Fusion"))
    available = set(QFontDatabase.families())
    family = next(
        (name for name in ("Segoe UI", "Inter", "Arial") if name in available), "sans-serif"
    )
    application.setFont(font(base=QFont(family)))
    palette = QPalette()
    for name, token in {
        "Window": "surface_canvas",
        "WindowText": "text_primary",
        "Base": "surface_control",
        "AlternateBase": "surface_subtle",
        "Text": "text_primary",
        "Button": "surface_control",
        "ButtonText": "text_primary",
        "Highlight": "accent_selection",
        "HighlightedText": "text_primary",
        "PlaceholderText": "text_muted",
        "ToolTipBase": "component_tooltip",
        "ToolTipText": "component_tooltip_text",
        "Link": "accent_default",
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
    return ACTIVE_SCHEME


def title_styles(card=False):
    small = FONT_SIZES["sm" if card else "md"]
    large = FONT_SIZES["md" if card else "lg"]
    return {
        "prefix": f"color:{COLORS['text_muted']}; font-size:{small}px; font-weight:400",
        "metadata": f"color:{COLORS['text_secondary']}; font-size:{small}px; font-weight:400",
        "separator": f"color:{COLORS['text_muted']}; font-size:{small}px; font-weight:400",
        "mainline": f"color:{COLORS['text_primary']}; font-size:{large}px; font-weight:700",
    }
