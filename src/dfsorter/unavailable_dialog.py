from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .theme import font, role


def unavailable_groups(catalogue):
    groups = defaultdict(list)
    for clip in catalogue.clips():
        if not Path(clip["source_path"]).is_file():
            groups[str(Path(clip["source_path"]).parent)].append(clip)
    return dict(sorted(groups.items(), key=lambda item: item[0].casefold()))


def match_unavailable(clips, destination, media_info):
    destination = Path(destination)
    matches = {}
    missing = []
    mismatched = []
    for clip in clips:
        target = destination / Path(clip["source_path"]).name
        try:
            stamp = target.stat()
            if not target.is_file():
                raise OSError("Not a file")
        except OSError:
            missing.append(clip["source_path"])
            continue
        cached = media_info.get(clip["source_path"])
        if cached and cached["size"] is not None and stamp.st_size != cached["size"]:
            mismatched.append(clip["source_path"])
            continue
        matches[clip["clip_id"]] = (
            clip["source_path"],
            str(target),
            cached["size"] if cached else None,
        )
    return matches, missing, mismatched


class UnavailableClipsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.dismissed = set()
        self.setWindowTitle("Manage unavailable clips")
        self.resize(980, 620)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Catalogue clips whose original video files are missing or unreachable. "
            "Actions affect only unavailable entries in the selected folder."
        )
        intro.setWordWrap(True)
        role(intro, "secondary")
        layout.addWidget(intro)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.content = QWidget()
        self.rows = QVBoxLayout(self.content)
        self.rows.setSpacing(12)
        scroll.setWidget(self.content)
        layout.addWidget(scroll, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(close)
        layout.addLayout(footer)
        self.refresh()

    def refresh(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        groups = unavailable_groups(self.window.catalogue)
        visible = [(path, clips) for path, clips in groups.items() if path not in self.dismissed]
        if not visible:
            empty = QLabel("No unavailable clips need review.")
            role(empty, "secondary")
            self.rows.addWidget(empty)
        for path, clips in visible:
            group = QWidget()
            body = QVBoxLayout(group)
            body.setContentsMargins(0, 4, 0, 8)
            body.setSpacing(5)
            header = QHBoxLayout()
            folder = QLabel(path)
            folder.setFont(font("md", "semibold"))
            folder.setWordWrap(True)
            folder.setToolTip(path)
            header.addWidget(folder, 1)
            for label, action in (
                ("Do nothing", self.dismiss),
                ("Delete…", self.delete),
                ("Reassociate…", self.reassociate),
            ):
                button = QPushButton(label)
                button.clicked.connect(lambda checked=False, path=path, action=action: action(path))
                header.addWidget(button)
            body.addLayout(header)
            body.addWidget(self.summary(clips))
            self.rows.addWidget(group)
        self.rows.addStretch()

    def summary(self, clips):
        verdicts = Counter(clip["triage"] or "pending" for clip in clips)
        games = Counter(clip["game"] or "Uncategorized" for clip in clips)
        cached = [self.window.media_info.get(clip["source_path"], {}) for clip in clips]
        dates = []
        for info in cached:
            if info.get("created"):
                try:
                    value = datetime.fromisoformat(info["created"].replace("Z", "+00:00"))
                    dates.append(value.replace(tzinfo=value.tzinfo or timezone.utc))
                except ValueError:
                    pass
        known_sizes = [info["size"] for info in cached if info.get("size") is not None]
        date_text = (
            f"{min(dates):%Y-%m-%d}–{max(dates):%Y-%m-%d} ({len(dates)} dated)"
            if dates
            else "Date unavailable"
        )
        size_text = (
            f"{sum(known_sizes) / (1024**3):.2f} GB cached ({len(known_sizes)} of {len(clips)})"
            if known_sizes
            else "Size unavailable"
        )
        games_text = ", ".join(f"{name} {count}" for name, count in sorted(games.items()))
        video_count = f"{len(clips)} {'video' if len(clips) == 1 else 'videos'}"
        details = QLabel(
            f"{video_count} · {verdicts['keep']} Keep · {verdicts['discard']} Discard · "
            f"{verdicts['pending']} Pending\n{games_text} · {date_text} · {size_text}"
        )
        details.setWordWrap(True)
        role(details, "muted")
        return details

    def dismiss(self, path):
        self.dismissed.add(path)
        self.refresh()

    def delete(self, path):
        clips = unavailable_groups(self.window.catalogue).get(path, [])
        if not clips:
            self.refresh()
            return
        ids = {clip["clip_id"] for clip in clips}
        session = self.window.catalogue.state("session")
        in_session = len(ids.intersection(session["ids"])) if session else 0
        in_projects = len(
            ids.intersection(
                row["clip_id"]
                for row in self.window.catalogue.rows("SELECT DISTINCT clip_id FROM members")
            )
        )
        box = QMessageBox(self)
        box.setWindowTitle("Delete unavailable catalogue entries")
        box.setText(path)
        box.setInformativeText(
            f"Remove {len(clips)} unavailable catalogue entries, including metadata? "
            f"{in_session} are in the current session and {in_projects} are in projects. "
            "A database backup will be saved first. No video files will be deleted."
        )
        box.setDetailedText("\n".join(clip["source_path"] for clip in clips))
        remove = box.addButton("Remove from catalogue", QMessageBox.ButtonRole.DestructiveRole)
        role(remove, "danger")
        cancel = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(cancel)
        box.exec()
        if box.clickedButton() is not remove:
            return
        try:
            backup = self.window.catalogue.backup()
            self.window.catalogue.remove_unavailable(ids)
            self.window.media_info = self.window.catalogue.media_cache()
            for clip_id in ids:
                self.window.drafts.pop(clip_id, None)
                self.window.history.pop(clip_id, None)
            if self.window.current_id in ids:
                self.window.current_id = None
                self.window.player.load(None)
            self.window.refresh_references()
            self.window.refresh_library()
            self.window.statusBar().showMessage(
                f"Catalogue entries removed. Backup: {backup}", 20000
            )
            self.refresh()
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "Unavailable clips", str(error))

    def reassociate(self, path):
        clips = unavailable_groups(self.window.catalogue).get(path, [])
        if not clips:
            self.refresh()
            return
        destination = QFileDialog.getExistingDirectory(
            self, "Replacement folder for unavailable clips"
        )
        if not destination:
            return
        matches, missing, mismatched = match_unavailable(clips, destination, self.window.media_info)
        preview = QMessageBox(self)
        preview.setWindowTitle("Review reassociation")
        preview.setText(f"{len(matches)} of {len(clips)} clips match in {destination}")
        preview.setInformativeText(
            f"{len(missing)} filenames absent · {len(mismatched)} cached size mismatches. "
            "Matched clips keep their metadata and project/session references. "
            "Unmatched clips remain at their original paths."
        )
        preview.setDetailedText(
            "Matched:\n"
            + "\n".join(path for _old, path, _size in matches.values())
            + "\n\nMissing:\n"
            + "\n".join(missing)
            + "\n\nSize mismatches:\n"
            + "\n".join(mismatched)
        )
        apply = preview.addButton("Reassociate matched clips", QMessageBox.ButtonRole.AcceptRole)
        apply.setEnabled(bool(matches))
        cancel = preview.addButton(QMessageBox.StandardButton.Cancel)
        preview.setDefaultButton(cancel)
        preview.exec()
        if preview.clickedButton() is not apply:
            return
        try:
            self.window.catalogue.reassociate_unavailable(matches, destination)
            self.window.media_info = self.window.catalogue.media_cache()
            self.window.refresh_references()
            self.window.refresh_library()
            self.refresh()
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "Unavailable clips", str(error))
