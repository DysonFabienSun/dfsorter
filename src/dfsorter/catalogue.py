import json
import os
import sqlite3
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def normalized(path) -> str:
    return os.path.normcase(str(Path(path).resolve()))


def now():
    return datetime.now(timezone.utc).isoformat()


class Catalogue:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.undo_stack = []
        self.redo_stack = []
        with self.connection() as database:
            version = database.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise ValueError("This catalogue requires a newer DFSorter version")
            database.executescript("""
                CREATE TABLE IF NOT EXISTS clips (
                    clip_id TEXT PRIMARY KEY, source_path TEXT UNIQUE NOT NULL,
                    game TEXT, triage TEXT CHECK(triage IN ('keep','discard')),
                    rating INTEGER CHECK(rating BETWEEN 1 AND 5),
                    technical_condition TEXT, mainline TEXT, description TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}', in_ms INTEGER, out_ms INTEGER,
                    catalogue_modified_at TEXT NOT NULL,
                    CHECK((in_ms IS NULL AND out_ms IS NULL) OR
                          (in_ms >= 0 AND out_ms > in_ms))
                );
                CREATE TABLE IF NOT EXISTS folders (
                    folder_id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1, forced_game TEXT
                );
                CREATE TABLE IF NOT EXISTS sources (
                    folder_id TEXT REFERENCES folders ON DELETE CASCADE,
                    clip_id TEXT REFERENCES clips ON DELETE CASCADE,
                    PRIMARY KEY(folder_id, clip_id)
                );
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY, name TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS members (
                    project_id TEXT REFERENCES projects ON DELETE CASCADE,
                    clip_id TEXT REFERENCES clips ON DELETE CASCADE,
                    PRIMARY KEY(project_id, clip_id)
                );
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                PRAGMA user_version = 1;
            """)

    @contextmanager
    def connection(self):
        database = sqlite3.connect(self.path, timeout=10)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA foreign_keys = ON")
        try:
            with database:
                yield database
        finally:
            database.close()

    def rows(self, sql, parameters=()):
        with self.connection() as database:
            return [dict(row) for row in database.execute(sql, parameters)]

    def clips(self):
        result = self.rows("SELECT * FROM clips ORDER BY source_path COLLATE NOCASE")
        for clip in result:
            clip["metadata"] = json.loads(clip["metadata"])
        return result

    def clip(self, clip_id):
        rows = self.rows("SELECT * FROM clips WHERE clip_id=?", (clip_id,))
        if not rows:
            raise ValueError("Clip no longer exists")
        clip = rows[0]
        clip["metadata"] = json.loads(clip["metadata"])
        return clip

    def state(self, key, default=None):
        rows = self.rows("SELECT value FROM state WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set_state(self, key, value):
        with self.connection() as database:
            database.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, json.dumps(value)))

    def folders(self):
        return self.rows("SELECT * FROM folders ORDER BY path COLLATE NOCASE")

    def add_folder(self, path, forced_game=None):
        path = normalized(path)
        if not Path(path).is_dir():
            raise ValueError("Capture folder does not exist")
        if any(
            Path(path).is_relative_to(Path(folder["path"]))
            or Path(folder["path"]).is_relative_to(Path(path))
            for folder in self.folders()
        ):
            raise ValueError("Capture folders must not overlap")
        folder_id = uuid4().hex
        with self.connection() as database:
            database.execute("INSERT INTO folders VALUES (?,?,1,?)", (folder_id, path, forced_game))
        return folder_id

    def enable_folder(self, folder_id, enabled):
        with self.connection() as database:
            database.execute(
                "UPDATE folders SET enabled=? WHERE folder_id=?", (int(enabled), folder_id)
            )

    def ingest(self, folder_id, discovered):
        with self.connection() as database:
            for item in discovered:
                path = normalized(item["path"])
                database.execute(
                    """INSERT OR IGNORE INTO clips
                    (clip_id,source_path,game,catalogue_modified_at) VALUES (?,?,?,?)""",
                    (uuid4().hex, path, item["game"], now()),
                )
                clip_id = database.execute(
                    "SELECT clip_id FROM clips WHERE source_path=?", (path,)
                ).fetchone()[0]
                database.execute("INSERT OR IGNORE INTO sources VALUES (?,?)", (folder_id, clip_id))

    def remove_folder(self, folder_id, purge=False):
        with self.connection() as database:
            if purge:
                database.execute(
                    "DELETE FROM clips WHERE clip_id IN "
                    "(SELECT clip_id FROM sources WHERE folder_id=?)",
                    (folder_id,),
                )
            database.execute("DELETE FROM folders WHERE folder_id=?", (folder_id,))
        if purge:
            self.undo_stack.clear()
            self.redo_stack.clear()
            session = self.state("session")
            if session:
                existing = {clip["clip_id"] for clip in self.clips()}
                ids = [clip_id for clip_id in session["ids"] if clip_id in existing]
                self.set_state(
                    "session",
                    {"ids": ids, "index": min(session["index"], len(ids) - 1)} if ids else None,
                )

    def migrate(self, folder_id, destination):
        folders = {folder["folder_id"]: folder for folder in self.folders()}
        old = Path(folders[folder_id]["path"])
        new = Path(normalized(destination))
        if not new.is_dir():
            raise ValueError("Destination capture folder does not exist")
        if any(
            other_id != folder_id
            and (
                new.is_relative_to(Path(folder["path"])) or Path(folder["path"]).is_relative_to(new)
            )
            for other_id, folder in folders.items()
        ):
            raise ValueError("Capture folders must not overlap")
        rows = self.rows(
            "SELECT clips.* FROM clips JOIN sources USING(clip_id) WHERE folder_id=?", (folder_id,)
        )
        updates = [
            (normalized(new / Path(row["source_path"]).relative_to(old)), row["clip_id"])
            for row in rows
        ]
        targets = [path for path, clip_id in updates]
        existing = {clip["source_path"]: clip["clip_id"] for clip in self.clips()}
        if len(targets) != len(set(targets)) or any(
            path in existing and existing[path] != clip_id for path, clip_id in updates
        ):
            raise ValueError("Migration would collide with an existing source identity")
        with self.connection() as database:
            database.executemany("UPDATE clips SET source_path=? WHERE clip_id=?", updates)
            database.execute("UPDATE folders SET path=? WHERE folder_id=?", (str(new), folder_id))

    def projects(self):
        return self.rows("SELECT * FROM projects ORDER BY name COLLATE NOCASE")

    def save_project(self, name, project_id=None):
        if not name.strip():
            raise ValueError("Project name cannot be empty")
        project_id = project_id or uuid4().hex
        with self.connection() as database:
            database.execute(
                "INSERT INTO projects VALUES (?,?) ON CONFLICT(project_id) "
                "DO UPDATE SET name=excluded.name",
                (project_id, name.strip()),
            )
        return project_id

    def delete_project(self, project_id):
        with self.connection() as database:
            database.execute("DELETE FROM projects WHERE project_id=?", (project_id,))
        if self.state("active_project") == project_id:
            self.set_state("active_project", None)
        self.undo_stack.clear()
        self.redo_stack.clear()

    def member_ids(self, project_id):
        return {
            row["clip_id"]
            for row in self.rows("SELECT clip_id FROM members WHERE project_id=?", (project_id,))
        }

    def memberships(self, clip_id):
        return [
            row["project_id"]
            for row in self.rows("SELECT project_id FROM members WHERE clip_id=?", (clip_id,))
        ]

    def _snapshot(self, clip_id):
        return self.clip(clip_id), self.memberships(clip_id)

    def _restore(self, snapshot):
        clip, memberships = snapshot
        fields = [
            "game",
            "triage",
            "rating",
            "technical_condition",
            "mainline",
            "description",
            "metadata",
            "in_ms",
            "out_ms",
        ]
        values = [json.dumps(clip[key]) if key == "metadata" else clip[key] for key in fields]
        with self.connection() as database:
            database.execute(
                "UPDATE clips SET "
                + ",".join(f"{key}=?" for key in fields)
                + ",catalogue_modified_at=? WHERE clip_id=?",
                [*values, now(), clip["clip_id"]],
            )
            database.execute("DELETE FROM members WHERE clip_id=?", (clip["clip_id"],))
            database.executemany(
                "INSERT INTO members VALUES (?,?)",
                [(project_id, clip["clip_id"]) for project_id in memberships],
            )

    def patch(self, clip_id, patch, editing=False, replace_metadata=False, membership=None):
        before = self._snapshot(clip_id)
        after = deepcopy(before)
        clip, memberships = after
        allowed = {
            "game",
            "triage",
            "rating",
            "technical_condition",
            "mainline",
            "description",
            "metadata",
            "in_ms",
            "out_ms",
        }
        if set(patch) - allowed:
            raise ValueError("Unsupported metadata field")
        for key, value in patch.items():
            if key == "metadata" and not replace_metadata:
                clip[key].update(value)
            else:
                clip[key] = value
        if clip["triage"] not in {None, "keep", "discard"}:
            raise ValueError("Invalid triage")
        if clip["rating"] is not None and (
            type(clip["rating"]) is not int or clip["rating"] not in range(1, 6)
        ):
            raise ValueError("Rating must be 1 through 5")
        start, end = clip["in_ms"], clip["out_ms"]
        if not (start is None and end is None) and not (
            isinstance(start, int) and isinstance(end, int) and 0 <= start < end
        ):
            raise ValueError("In/Out range must have 0 <= In < Out")
        active = self.state("active_project")
        if editing and clip["triage"] == "keep" and before[0]["triage"] != "keep" and active:
            if active not in memberships:
                memberships.append(active)
        if membership:
            project_id, include = membership
            if include and project_id not in memberships:
                memberships.append(project_id)
            if not include and project_id in memberships:
                memberships.remove(project_id)
        if before == after:
            return
        self._restore(after)
        self.undo_stack.append((before, after))
        self.redo_stack.clear()

    def undo(self, redo=False):
        source, destination = (
            (self.redo_stack, self.undo_stack) if redo else (self.undo_stack, self.redo_stack)
        )
        if source:
            operation = source[-1]
            self._restore(operation[1 if redo else 0])
            destination.append(source.pop())

    def create_session(self, ids, replace=False):
        if self.state("session") and not replace:
            raise ValueError("End or explicitly replace the existing session")
        existing = {clip["clip_id"] for clip in self.clips()}
        if not ids or len(ids) != len(set(ids)) or any(clip_id not in existing for clip_id in ids):
            raise ValueError("Session needs a nonempty unique list of existing clips")
        self.set_state("session", {"ids": ids, "index": 0})

    def navigate(self, index):
        session = self.state("session")
        if not session:
            return
        session["index"] = max(0, min(index, len(session["ids"]) - 1))
        self.set_state("session", session)
