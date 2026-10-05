from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .playback import playback_start_settings, start_offset_seconds
from .theme import font, role


class SettingsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Settings")
        self.resize(850, 560)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        general = QWidget()
        preferences = QVBoxLayout(general)
        preferences.setSpacing(12)
        playback_group, playback = self.preference_group("Browse · Editing · Export")
        self.start_near_end = QCheckBox("Start this many seconds from the end:")
        self.start_near_end.setToolTip(
            "Applies to videos without a valid I/O range. Saved ranges start at the In point."
        )
        self.start_near_end.setChecked(window.settings.get("start_near_end_enabled", True))
        offset_row = QHBoxLayout()
        self.start_offset = QSpinBox()
        self.start_offset.setProperty("playbackOffset", True)
        self.start_offset.setRange(1, 999)
        self.start_offset.setSingleStep(5)
        self.start_offset.setSuffix(" s")
        self.start_offset.setValue(start_offset_seconds(window.settings))
        self.start_offset.setFixedWidth(52)
        self.start_offset.lineEdit().setTextMargins(0, 0, 0, 1)
        self.start_offset.setEnabled(self.start_near_end.isChecked())
        offset_row.addWidget(self.start_near_end, alignment=Qt.AlignmentFlag.AlignBaseline)
        offset_row.addWidget(self.start_offset, alignment=Qt.AlignmentFlag.AlignBaseline)
        offset_row.addStretch()
        playback.addLayout(offset_row)
        self.separate_start = QCheckBox("Use separate settings for Browse, Editing, and Export")
        self.separate_start.setChecked(window.settings.get("start_near_end_separate", False))
        playback.addWidget(self.separate_start)
        self.separate_start_group = QWidget()
        role(self.separate_start_group, "outlinedGroup")
        separate_layout = QVBoxLayout(self.separate_start_group)
        separate_layout.setSpacing(8)
        self.pane_start_controls = {}
        for pane in ("Browse", "Editing", "Export"):
            enabled, seconds = playback_start_settings(window.settings, pane)
            row = QHBoxLayout()
            check = QCheckBox(f"{pane}: start this many seconds from the end:")
            check.setToolTip(self.start_near_end.toolTip())
            check.setChecked(enabled)
            offset = QSpinBox()
            offset.setProperty("playbackOffset", True)
            offset.setRange(1, 999)
            offset.setSingleStep(5)
            offset.setSuffix(" s")
            offset.setValue(seconds)
            offset.setFixedWidth(52)
            offset.lineEdit().setTextMargins(0, 0, 0, 1)
            offset.setEnabled(enabled)
            row.addWidget(check, alignment=Qt.AlignmentFlag.AlignBaseline)
            row.addWidget(offset, alignment=Qt.AlignmentFlag.AlignBaseline)
            row.addStretch()
            separate_layout.addLayout(row)
            self.pane_start_controls[pane] = (check, offset)
            check.toggled.connect(self.save_playback_preferences)
            offset.valueChanged.connect(self.save_playback_preferences)
        playback.addWidget(self.separate_start_group)
        self.unified_start_row = offset_row
        self.update_playback_controls()
        preferences.addWidget(playback_group)
        editing_group, editing = self.preference_group("Editing")
        self.paused_typing = QCheckBox("Type to enter commands while video is paused")
        self.paused_typing.setChecked(window.settings.get("paused_typing_enabled", True))
        self.paused_typing.toggled.connect(self.save_command_preferences)
        editing.addWidget(self.paused_typing)
        self.ghost_autocomplete = QCheckBox("Show ghost expansions for command aliases")
        self.ghost_autocomplete.setChecked(window.settings.get("ghost_autocomplete_enabled", True))
        self.ghost_autocomplete.toggled.connect(self.save_command_preferences)
        editing.addWidget(self.ghost_autocomplete)
        self.editing_tips = QCheckBox("Show rotating Editing tips")
        self.editing_tips.setChecked(window.settings.get("editing_tips_enabled", True))
        self.editing_tips.toggled.connect(self.save_command_preferences)
        editing.addWidget(self.editing_tips)
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Field markers and tips size:"))
        self.editing_bottom_size = QButtonGroup(self)
        size_choices = QHBoxLayout()
        size_choices.setSpacing(0)
        for index, size in enumerate((11, 12, 13)):
            control = QPushButton(f"{size} px")
            control.setCheckable(True)
            control.setChecked(size == window.editing_bottom_size())
            control.setProperty("periodSegment", True)
            control.setProperty("editingSizeChoice", True)
            control.setProperty(
                "periodPosition", "first" if index == 0 else "last" if index == 2 else "middle"
            )
            self.editing_bottom_size.addButton(control, size)
            size_choices.addWidget(control)
        self.editing_bottom_size.idClicked.connect(self.save_command_preferences)
        size_row.addLayout(size_choices)
        size_row.addStretch()
        editing.addLayout(size_row)
        preferences.addWidget(editing_group)
        titles_group, titles = self.preference_group("Browse · Editing · Export")
        self.lowercase_titles = QCheckBox("Lowercase working titles and generated filenames")
        self.lowercase_titles.setChecked(window.settings.get("lowercase_generated_titles", True))
        self.lowercase_titles.setToolTip(
            "Keeps game codes uppercase. Custom filenames and original filename fallbacks "
            "keep their casing. Uncheck to use stored capitalization."
        )
        self.lowercase_titles.toggled.connect(self.save_title_preferences)
        titles.addWidget(self.lowercase_titles)
        preferences.addWidget(titles_group)
        preferences.addStretch()
        self.start_near_end.toggled.connect(self.save_playback_preferences)
        self.start_offset.valueChanged.connect(self.save_playback_preferences)
        self.separate_start.toggled.connect(self.save_playback_preferences)
        tabs.addTab(general, "General")
        appearance = QWidget()
        appearance_layout = QVBoxLayout(appearance)
        theme_row = QHBoxLayout()
        theme_label = QLabel("Theme:")
        self.theme = QComboBox()
        for label, value in [("System", "system"), ("Light", "light"), ("Dark", "dark")]:
            self.theme.addItem(label, value)
        self.theme.setCurrentIndex(
            max(0, self.theme.findData(window.settings.get("theme", "light")))
        )
        theme_label.setBuddy(self.theme)
        theme_row.addWidget(theme_label)
        theme_row.addWidget(self.theme)
        theme_row.addStretch()
        appearance_layout.addLayout(theme_row)
        theme_explanation = QLabel(
            "System follows the operating-system appearance. The toolbar control selects an "
            "explicit Light or Dark theme."
        )
        theme_explanation.setWordWrap(True)
        role(theme_explanation, "secondary")
        appearance_layout.addWidget(theme_explanation)
        appearance_layout.addStretch()
        self.theme.currentIndexChanged.connect(self.save_theme_preference)
        tabs.addTab(appearance, "Appearance")
        tabs.setCurrentIndex(0)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.installEventFilter(self)
        for widget in self.findChildren(QWidget):
            if widget.focusPolicy() == Qt.FocusPolicy.NoFocus:
                widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            focused = self.focusWidget()
            if focused is not None and self.isAncestorOf(focused):
                focused.clearFocus()
        return super().eventFilter(watched, event)

    def preference_group(self, title):
        group = QWidget()
        role(group, "group")
        layout = QVBoxLayout(group)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setFont(font("sm", "bold"))
        role(heading, "secondary")
        heading.setProperty("settingsGroupHeading", True)
        layout.addWidget(heading)
        layout.addSpacing(4)
        return group, layout

    def save_title_preferences(self):
        self.window.settings["lowercase_generated_titles"] = self.lowercase_titles.isChecked()
        self.window.save_settings()
        self.window.refresh_title_presentation()

    def save_theme_preference(self):
        self.window.set_theme(self.theme.currentData())

    def save_playback_preferences(self):
        if not any(
            f"start_near_end_{pane.lower()}_seconds" in self.window.settings
            for pane in self.pane_start_controls
        ):
            for check, offset in self.pane_start_controls.values():
                check.blockSignals(True)
                offset.blockSignals(True)
                check.setChecked(self.start_near_end.isChecked())
                offset.setValue(self.start_offset.value())
                check.blockSignals(False)
                offset.blockSignals(False)
        self.update_playback_controls()
        self.window.settings["start_near_end_enabled"] = self.start_near_end.isChecked()
        self.window.settings["start_near_end_seconds"] = self.start_offset.value()
        self.window.settings["start_near_end_separate"] = self.separate_start.isChecked()
        if self.separate_start.isChecked() or any(
            f"start_near_end_{pane.lower()}_seconds" in self.window.settings
            for pane in self.pane_start_controls
        ):
            for pane, (check, offset) in self.pane_start_controls.items():
                prefix = f"start_near_end_{pane.lower()}"
                self.window.settings[f"{prefix}_enabled"] = check.isChecked()
                self.window.settings[f"{prefix}_seconds"] = offset.value()
        self.window.save_settings()

    def update_playback_controls(self):
        separate = self.separate_start.isChecked()
        self.start_near_end.setVisible(not separate)
        for index in range(self.unified_start_row.count()):
            widget = self.unified_start_row.itemAt(index).widget()
            if widget is not None:
                widget.setVisible(not separate)
        self.separate_start_group.setVisible(separate)
        self.start_offset.setEnabled(self.start_near_end.isChecked())
        for check, offset in self.pane_start_controls.values():
            offset.setEnabled(check.isChecked())

    def save_command_preferences(self):
        tips_were_enabled = self.window.settings.get("editing_tips_enabled", True)
        self.window.settings["paused_typing_enabled"] = self.paused_typing.isChecked()
        self.window.settings["ghost_autocomplete_enabled"] = self.ghost_autocomplete.isChecked()
        self.window.settings["editing_tips_enabled"] = self.editing_tips.isChecked()
        self.window.settings["editing_bottom_size"] = self.editing_bottom_size.checkedId()
        self.window.save_settings()
        self.window.update_command_state()
        if tips_were_enabled != self.editing_tips.isChecked():
            self.window.update_tips_enabled()
        self.window.update_editing_bottom_size()
