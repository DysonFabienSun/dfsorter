
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QCheckBox, QProxyStyle, QStyle

from .app_paths import ROOT

THEMES = {
    "light": {
        "surface_canvas": "#F3F5F7",
        "surface_workspace": "#FFFFFF",
        "surface_sidebar": "#F8F9FA",
        "bg_library_toolbar": "#F1F3F5",
        "bg_library_search": "#F8F9FA",
        "surface_panel": "#FFFFFF",
        "surface_subtle": "#F6F8FA",
        "surface_prominent_neutral": "#FFFFFF",
        "surface_control": "#FFFFFF",
        "surface_hover": "#EDF1F3",
        "surface_pressed": "#E4E9ED",
        "surface_video": "#000000",
        "text_primary": "#1F252B",
        "text_secondary": "#4F5B66",
        "text_muted": "#65717C",
        "text_disabled": "#A3ABB3",
        "text_inverse": "#FFFFFF",
        "heading_icon_foreground": "#000000",
        "player_chrome_text": "#F1F4F6",
        "player_chrome_secondary": "#E0E5E9",
        "player_chrome_muted": "#CDD5DC",
        "player_chrome_tag": "#E8C45A",
        "border_default": "#C8D1D9",
        "border_subtle": "#DEE5EA",
        "border_strong": "#AEB8C1",
        "accent_default": "#087F8C",
        "accent_hover": "#066E79",
        "accent_pressed": "#055E68",
        "accent_soft": "#E2F2F4",
        "accent_soft_hover": "#D4EAED",
        "accent_selection": "#C9E9ED",
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
        "bg_library_toolbar": "#171B20",
        "bg_library_search": "#1D2329",
        "surface_panel": "#1F242B",
        "surface_subtle": "#252B33",
        "surface_prominent_neutral": "#2C333B",
        "surface_control": "#20262D",
        "surface_hover": "#2A313A",
        "surface_pressed": "#303842",
        "surface_video": "#000000",
        "text_primary": "#F1F4F6",
        "text_secondary": "#BEC6CD",
        "text_muted": "#8E99A4",
        "text_disabled": "#626C76",
        "text_inverse": "#111317",
        "heading_icon_foreground": "#FFFFFF",
        "player_chrome_text": "#F1F4F6",
        "player_chrome_secondary": "#E0E5E9",
        "player_chrome_muted": "#CDD5DC",
        "player_chrome_tag": "#E8C45A",
        "border_default": "#39424C",
        "border_subtle": "#2D343D",
        "border_strong": "#515C67",
        "accent_default": "#43B6C3",
        "accent_hover": "#58C2CD",
        "accent_pressed": "#32A4B1",
        "accent_soft": "#173D43",
        "accent_soft_hover": "#1B4850",
        "accent_selection": "#245E68",
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

FONT_SIZES = {
    "xs": 11, "sm": 12, "md": 13, "base": 14, "card_title": 14,
    "library_title": 15, "lg": 16, "xl": 20, "section_heading": 22,
    "pane_heading": 16, "xxl": 26, "fullscreen_title_small": 17,
    "fullscreen_title": 21, "fullscreen_title_tag": 20,
}
WEIGHTS = {"regular": 400, "medium": 500, "semibold": 600, "bold": 700}
SPACING = (4, 8, 12, 16, 24, 32)
RADII = {"none": 0, "structural": 2, "sm": 3, "md": 5, "lg": 7, "control": 4}
SIZES = {
    "compact": 24,
    "normal": 32,
    "large": 36,
    "toolbar": 28,
    "nav": 34,
    "card": 56,
    "compact_card": 53,
    "browse_card": 64,
    "thumbnail_width": 84,
    "thumbnail_height": 48,
    "card_gap": 1,
    "card_padding": 7,
    "card_dot_space": 18,
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
        **{f"radius_{key}": value for key, value in RADII.items()},
        **{f"font_{key}": value for key, value in FONT_SIZES.items()},
        "combo_chevron": (
            ROOT / "resources/icons/chevron-down.svg"
        ).as_posix(),
        "spin_up_chevron": (
            ROOT / "resources/icons/chevron-up.svg"
        ).as_posix(),
        "check_icon": (ROOT / "resources/icons/check.svg").as_posix(),
    }
    return (
        """
        QWidget { background: %(surface_workspace)s; color: %(text_primary)s; }
        QMainWindow { background: %(surface_canvas)s; }
        QWidget#videoSurface { background: %(surface_video)s; }
        QWidget#videoContainer { background: %(surface_canvas)s; }
        QWidget#fullscreenChromeContent { background: transparent; }
        QWidget#fullscreenChromeContent[chromePosition="top"] {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 rgba(0, 0, 0, 160), stop:1 rgba(0, 0, 0, 0));
        }
        QWidget#playerControlBar { background: transparent; }
        QWidget#fullscreenChromeContent QLabel { color: %(player_chrome_text)s; }
        QWidget#fullscreenChromeContent QToolButton { color: %(player_chrome_text)s; }
        QWidget#fullscreenChromeContent QToolButton:hover { background: rgba(255, 255, 255, 35); }
        QWidget#fullscreenChromeContent QToolButton:pressed { background: rgba(255, 255, 255, 55); }
        QWidget#fullscreenChromeContent QToolButton:disabled { background: transparent; border-color: transparent; color: rgba(241, 244, 246, 110); }
        QWidget#pageLoading, QWidget#commandCover { background: %(surface_workspace)s; }
        QLabel { background: transparent; }
        QCheckBox { background: transparent; }
        QCheckBox::indicator { background: %(surface_control)s; border: 1px solid %(border_default)s; border-radius: 3px; width: 14px; height: 14px; }
        QCheckBox::indicator:checked { background: %(accent_default)s; border-color: %(accent_default)s; image: url("%(check_icon)s"); }
        QCheckBox:focus { border: none; }
        QCheckBox::indicator:focus { border: 2px solid %(focus)s; }
        QLabel#fastIndicator { color: %(accent_default)s; background: transparent; }
        QWidget[role="panel"] { background: %(surface_panel)s; }
        QWidget[role="sidebar"] { background: %(surface_sidebar)s; }
        QWidget#libraryToolbar { background: %(bg_library_toolbar)s; }
        QLineEdit[librarySearch="true"] { background: %(bg_library_search)s; border-color: %(border_subtle)s; }
        QLineEdit[librarySearch="true"]:hover { border-color: %(border_strong)s; }
        QLineEdit[librarySearch="true"]:focus { border: 2px solid %(focus)s; padding: 3px 7px; }
        QWidget#clipLibraryPane, QWidget#projectsPane { border-radius: %(radius_structural)spx; }
        QWidget#projectsPane { background: %(surface_sidebar)s; border-left: 1px solid %(border_subtle)s; }
        QWidget[role="transparent"] { background: transparent; }
        QWidget[role="group"] { background: %(surface_subtle)s; border: 1px solid %(border_subtle)s; border-radius: %(radius_structural)spx; }
        QWidget[role="outlinedGroup"] { background: %(surface_workspace)s; border: 1px solid %(border_default)s; border-radius: %(radius_structural)spx; }
        QWidget#folderPreviewTip { background: %(accent_soft)s; border-left: 2px solid %(accent_default)s; }
        QWidget#folderPreviewPath { background: %(surface_subtle)s; border: 1px solid %(border_subtle)s; border-radius: 4px; }
        QWidget#folderPreviewResultRow { background: transparent; border-bottom: 1px solid %(border_subtle)s; }
        QWidget[role="divider"] { background: %(border_subtle)s; }
        QLabel#muted, QLabel[role="secondary"] { color: %(text_secondary)s; font-size: %(font_sm)spx; }
        QLabel[role="muted"] { color: %(text_muted)s; font-size: %(font_sm)spx; }
        QLabel[role="helper"] { color: %(text_muted)s; font-size: %(font_xs)spx; }
        QLabel[role="heading"] { font-size: %(font_section_heading)spx; font-weight: 600; }
        QLabel[role="sectionHeading"] { font-size: %(font_section_heading)spx; font-weight: 600; color: %(text_primary)s; }
        QLabel[role="paneHeading"] { font-size: %(font_pane_heading)spx; font-weight: 600; color: %(text_primary)s; }
        QWidget#sessionHeader { background: %(bg_library_toolbar)s; }
        QWidget#configSidebarHeader { background: %(bg_library_toolbar)s; }
        QLabel#projectsActiveName { color: %(accent_default)s; font-size: %(font_sm)spx; }
        QToolButton[projectsAction="true"]:hover { background: %(surface_hover)s; border-color: %(border_subtle)s; }
        QToolButton[projectsAction="true"]:pressed { background: %(surface_pressed)s; }
        QWidget#overviewSummary { border-bottom: 1px solid %(border_subtle)s; }
        QPushButton[periodSegment="true"] { border-radius: 0px; margin: 0px; border-left: none; }
        QPushButton[periodSegment="true"][periodPosition="first"] { border-left: 1px solid %(border_subtle)s; border-top-left-radius: 4px; border-bottom-left-radius: 4px; }
        QPushButton[periodSegment="true"][periodPosition="last"] { border-top-right-radius: 4px; border-bottom-right-radius: 4px; }
        QPushButton[periodSegment="true"]:checked { border: 1px solid %(accent_default)s; }
        QLabel#workingTitle { font-size: %(font_lg)spx; font-weight: 600; }
        QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {
            background: %(surface_control)s; border: 1px solid %(border_default)s;
            border-radius: 4px; padding: 4px 8px; selection-background-color: %(accent_selection)s;
            selection-color: %(text_primary)s;
        }
        QLineEdit, QComboBox, QSpinBox { min-height: 18px; }
        QSpinBox[playbackOffset="true"] { min-height: 15px; padding: 0px 2px; margin-top: 1px; margin-bottom: 3px; }
        QSpinBox[playbackOffset="true"]:focus { padding: 1px 1px; }
        QComboBox { padding: 4px 28px 4px 8px; }
        QComboBox#browseShareMode { padding-right: 20px; }
        QComboBox::drop-down {
            subcontrol-origin: padding; subcontrol-position: top right;
            width: 24px; border: none; background: transparent;
        }
        QComboBox::down-arrow { image: url("%(combo_chevron)s"); width: 14px; height: 14px; }
        QSpinBox::up-button, QSpinBox::down-button {
            subcontrol-origin: border; width: 20px; border: none; background: transparent;
        }
        QSpinBox[playbackOffset="true"]::up-button,
        QSpinBox[playbackOffset="true"]::down-button { width: 12px; }
        QSpinBox::up-button { subcontrol-position: top right; }
        QSpinBox::down-button { subcontrol-position: bottom right; }
        QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: %(surface_hover)s; }
        QSpinBox::up-button:pressed, QSpinBox::down-button:pressed { background: %(surface_pressed)s; }
        QSpinBox::up-arrow { image: url("%(spin_up_chevron)s"); width: 12px; height: 12px; }
        QSpinBox::down-arrow { image: url("%(combo_chevron)s"); width: 12px; height: 12px; }
        QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: %(border_strong)s; }
        QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus { border: 2px solid %(focus)s; padding: 3px 7px; }
        QComboBox:focus { padding: 3px 27px 3px 7px; }
        QComboBox#browseShareMode:focus { padding-right: 19px; }
        QLineEdit#command[validationState="valid"] { background: %(component_command_valid)s; }
        QLineEdit#command[validationState="incomplete"] { border-bottom: 2px solid %(status_warning)s; }
        QLineEdit#command[validationState="invalid"] { border-bottom: 2px solid %(status_danger)s; }
        QLineEdit#command[validationState="saved"] { border-bottom: 2px solid %(status_success)s; }
        QPushButton, QToolButton { background: %(surface_subtle)s; border: 1px solid %(border_subtle)s; border-radius: 4px; padding: 5px 9px; min-height: 20px; }
        QPushButton[role="primary"], QPushButton[role="prominentNeutral"] { min-height: 24px; }
        QPushButton:hover, QToolButton:hover { background: %(surface_hover)s; }
        QPushButton:pressed, QToolButton:pressed { background: %(surface_pressed)s; }
        QPushButton:checked, QToolButton:checked { background: %(accent_soft)s; border-color: %(accent_default)s; }
        QPushButton[role="primary"] { background: %(accent_default)s; color: %(text_inverse)s; border-color: %(accent_default)s; font-weight: 600; }
        QPushButton[role="primary"]:hover { background: %(accent_hover)s; border-color: %(accent_hover)s; }
        QPushButton[role="primary"]:pressed { background: %(accent_pressed)s; border-color: %(accent_pressed)s; }
        QPushButton[shareAccepted="true"], QToolButton[shareAccepted="true"] { background: %(status_success_soft)s; color: %(status_success)s; border: 1px solid %(status_success)s; }
        QPushButton[role="prominentNeutral"] { border-color: %(border_default)s; font-weight: 600; }
        QPushButton[role="danger"], QToolButton[role="danger"] { color: %(status_danger)s; border-color: %(border_default)s; background: %(status_danger_soft)s; }
        QPushButton[role="danger"]:hover, QToolButton[role="danger"]:hover { color: %(status_danger_hover)s; border-color: %(status_danger)s; }
        QPushButton[role="keep"]:checked { background: %(status_success_soft)s; color: %(status_success)s; border-color: %(status_success)s; }
        QPushButton[role="discard"]:checked { background: %(status_danger_soft)s; color: %(status_danger)s; border-color: %(status_danger)s; }
        QPushButton[role="undefined"]:checked { background: %(surface_pressed)s; color: %(text_secondary)s; border-color: %(border_strong)s; }
        QPushButton:focus, QToolButton:focus { border: 2px solid %(focus)s; }
        QToolButton#settingsMenuButton::menu-indicator, QToolButton#captureFolderMenuButton::menu-indicator, QToolButton#activitiesButton::menu-indicator { image: none; width: 0px; }
        QToolButton { background: transparent; border: 1px solid transparent; padding: 2px; }
        QPushButton[captureFolderAction="true"], QToolButton[captureFolderAction="true"] { min-height: 24px; }
        QPushButton[role="prominentNeutral"][captureFolderAction="true"] { background: %(surface_prominent_neutral)s; color: %(text_primary)s; border: 1px solid %(border_default)s; }
        QPushButton[role="prominentNeutral"][captureFolderAction="true"]:hover { background: %(accent_soft)s; border-color: %(accent_default)s; }
        QPushButton[role="prominentNeutral"][captureFolderAction="true"]:focus { border: 1px solid %(focus)s; }
        QPushButton[role="prominentNeutral"][captureFolderAction="true"]:pressed { background: %(accent_soft_hover)s; }
        QToolButton#captureFolderMenuButton { background: transparent; color: %(text_secondary)s; border: 1px solid transparent; border-radius: 4px; padding: 5px 9px; }
        QToolButton#captureFolderMenuButton:hover { background: %(surface_hover)s; border-color: %(border_subtle)s; }
        QToolButton#captureFolderMenuButton:focus { border-color: %(focus)s; }
        QToolButton#captureFolderMenuButton:pressed { background: %(surface_pressed)s; }
        QWidget#navigationStrip { background: %(surface_sidebar)s; border-bottom: 1px solid %(border_subtle)s; }
        QPushButton#projectsDrawerTab { background: %(surface_sidebar)s; border: 1px solid %(border_subtle)s; border-top: none; border-top-left-radius: 0px; border-top-right-radius: 0px; border-bottom-left-radius: 9px; border-bottom-right-radius: 0px; padding: 3px 11px 5px 6px; }
        QPushButton#projectsDrawerTab:hover { background: %(surface_hover)s; border-color: %(border_default)s; border-top-color: transparent; }
        QPushButton#projectsDrawerTab:pressed { background: %(surface_pressed)s; border-color: %(border_default)s; border-top-color: transparent; }
        QWidget#projectsDrawerTabEdge { background: %(border_default)s; border: none; }
        QToolButton#projectsPaneClose { background: transparent; border-color: transparent; }
        QToolButton#projectsPaneClose:hover { background: %(surface_hover)s; }
        QToolButton#projectsPaneClose:pressed { background: %(surface_pressed)s; }
        QPushButton[navUtility="true"] { min-height: 24px; max-height: 24px; padding: 1px 6px; }
        QToolButton[navUtility="true"] { min-height: 22px; max-height: 22px; padding: 3px 2px 1px 2px; }
        QPushButton[navUtilityStyle="framed"], QToolButton[navUtilityStyle="framed"] { background: %(surface_subtle)s; border: 1px solid %(border_subtle)s; }
        QPushButton[navUtilityStyle="framed"]:hover, QToolButton[navUtilityStyle="framed"]:hover { background: %(surface_hover)s; border-color: %(border_default)s; }
        QPushButton[navUtilityStyle="framed"]:pressed, QToolButton[navUtilityStyle="framed"]:pressed { background: %(surface_pressed)s; border-color: %(border_default)s; }
        QPushButton[navUtilityStyle="ghost"], QToolButton[navUtilityStyle="ghost"] { background: transparent; border-color: transparent; }
        QPushButton[navUtilityStyle="ghost"]:hover, QToolButton[navUtilityStyle="ghost"]:hover { background: %(surface_hover)s; border-color: transparent; }
        QPushButton[navUtilityStyle="ghost"]:pressed, QToolButton[navUtilityStyle="ghost"]:pressed { background: %(surface_pressed)s; border-color: transparent; }
        QPushButton[navUtilityStyle="ghost"]:disabled, QToolButton[navUtilityStyle="ghost"]:disabled { background: transparent; border-color: transparent; }
        QToolButton#activitiesButton { background: transparent; border: 1px solid %(border_default)s; min-height: 20px; max-height: 20px; }
        QToolButton#activitiesButton:hover { background: %(surface_hover)s; border-color: %(border_strong)s; }
        QToolButton#activitiesButton:pressed { background: %(surface_pressed)s; border-color: %(border_strong)s; }
        QToolButton#activitiesButton[activityBusy="true"] { background: %(accent_soft)s; color: %(accent_default)s; border: 1px solid %(accent_default)s; }
        QToolButton#activitiesButton[activityBusy="true"]:hover { background: %(accent_soft_hover)s; }
        QToolButton#activitiesButton[activityAttention="true"] { background: %(status_warning_soft)s; color: %(status_warning)s; border: 1px solid %(status_warning)s; }
        QProgressBar { background: %(surface_subtle)s; color: %(text_primary)s; border: 1px solid %(border_subtle)s; border-radius: 4px; text-align: center; min-height: 13px; }
        QProgressBar::chunk { background: %(accent_default)s; border-radius: 3px; }
        QWidget#outputJobCard { background: %(surface_subtle)s; border: 1px solid %(border_subtle)s; border-radius: %(radius_md)spx; }
        QLabel#outputJobTitle { color: %(text_primary)s; font-weight: 600; }
        QLabel#outputJobSubtitle, QLabel#outputJobPhase { color: %(text_secondary)s; font-size: %(font_sm)spx; }
        QLabel#outputJobPhase[failed="true"] { color: %(status_danger)s; }
        QLabel#outputJobStatusDot, QLabel#outputJobStatus { font-size: %(font_sm)spx; }
        QLabel#outputJobStatusDot[statusColor="accent_default"], QLabel#outputJobStatus[statusColor="accent_default"] { color: %(accent_default)s; }
        QLabel#outputJobStatusDot[statusColor="status_success"], QLabel#outputJobStatus[statusColor="status_success"] { color: %(status_success)s; }
        QLabel#outputJobStatusDot[statusColor="status_danger"], QLabel#outputJobStatus[statusColor="status_danger"] { color: %(status_danger)s; }
        QLabel#outputJobStatusDot[statusColor="text_muted"], QLabel#outputJobStatus[statusColor="text_muted"] { color: %(text_muted)s; }
        QProgressBar#outputJobProgress { min-height: 6px; max-height: 6px; border-radius: 3px; }
        QProgressBar#outputJobProgress::chunk { border-radius: 2px; }
        QProgressBar#outputJobProgress[statusColor="status_success"]::chunk { background: %(status_success)s; }
        QProgressBar#outputJobProgress[statusColor="status_danger"]::chunk { background: %(status_danger)s; }
        QProgressBar#outputJobProgress[statusColor="text_muted"]::chunk { background: %(text_muted)s; }
        QPushButton#navigation { background: transparent; border: none; border-bottom: 2px solid transparent; border-radius: 0; color: %(text_secondary)s; font-size: %(font_base)spx; font-weight: 500; padding: 0px 16px; min-height: 32px; }
        QPushButton#navigation:hover { color: %(text_primary)s; background: %(surface_hover)s; }
        QPushButton#navigation:checked { background: transparent; color: %(text_primary)s; font-weight: 600; border-bottom-color: %(accent_default)s; }
        QPushButton#navigation:disabled { background: transparent; color: %(text_disabled)s; border-bottom-color: transparent; }
        QListWidget { background: %(surface_workspace)s; border: none; padding: 4px; outline: none; }
        QListWidget#clipLibrary { padding: 0px; }
        QWidget#clipScrollTopFade, QWidget#clipScrollBottomFade { background: transparent; border: none; }
        QWidget[role="sidebar"] QListWidget { background: %(surface_sidebar)s; }
        QListWidget#projectsList::item:selected { background: %(surface_pressed)s; color: %(text_primary)s; }
        QListWidget[contentSurface="secondary"] { background: %(surface_subtle)s; }
        QListWidget::item { padding: 2px 4px; }
        QListWidget::item:selected { background: %(accent_selection)s; color: %(text_primary)s; }
        QListWidget::item:hover { background: %(surface_hover)s; }
        QTableWidget { background: %(surface_control)s; color: %(text_primary)s; border: 1px solid %(border_default)s; gridline-color: %(border_subtle)s; selection-background-color: %(accent_selection)s; selection-color: %(text_primary)s; outline: none; }
        QTableWidget::item:hover { background: %(surface_hover)s; }
        QHeaderView::section { background: %(surface_subtle)s; color: %(text_secondary)s; border: none; border-bottom: 1px solid %(border_subtle)s; padding: 4px 8px; }
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
        QSlider#timeline, QSlider#volume { background: transparent; border: none; }
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
        QToolButton:disabled { background: transparent; border-color: transparent; }
        QPushButton[shareCompleted="true"], QToolButton[shareCompleted="true"] { background: %(status_success_soft)s; color: %(status_success)s; border: 1px solid %(status_success)s; }
        QLabel:disabled, QMenu::item:disabled, QMenuBar::item:disabled { color: %(text_disabled)s; }
        """
        % values
    )


class ApplicationStyle(QProxyStyle):
    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PrimitiveElement.PE_FrameFocusRect and isinstance(widget, QCheckBox):
            return
        super().drawPrimitive(element, option, painter, widget)

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
    if not isinstance(application.style(), ApplicationStyle):
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


def title_styles(card=False, on_video=False, library=False, compact_card=False):
    small = FONT_SIZES["fullscreen_title_small"] if on_video else FONT_SIZES[
        "base" if library and not compact_card else "md"
    ]
    if on_video:
        large_role = "fullscreen_title"
    elif compact_card:
        large_role = "card_title"
    elif library:
        large_role = "library_title"
    else:
        large_role = "card_title" if card else "lg"
    large = FONT_SIZES[large_role]
    mainline_weight = 600 if compact_card else 700
    muted = COLORS["player_chrome_muted" if on_video else "text_muted"]
    secondary = COLORS["player_chrome_secondary" if on_video else "text_secondary"]
    primary = COLORS["player_chrome_text"] if on_video else COLORS["text_primary"]
    return {
        "prefix": f"color:{muted}; font-size:{small}px; font-weight:400",
        "metadata": f"color:{secondary}; font-size:{small}px; font-weight:400",
        "separator": f"color:{muted}; font-size:{small}px; font-weight:400",
        "mainline": f"color:{primary}; font-size:{large}px; font-weight:{mainline_weight}",
    }
