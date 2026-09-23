import json
import os
import sqlite3
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def normalized(path) -> str:
    """Resolve a stored path without discarding its filesystem capitalization."""
    return str(Path(path).resolve())


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
            if version > 6:
                raise ValueError("This catalogue requires a newer DFSorter version")
            database.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS clips (
                    clip_id TEXT PRIMARY KEY, source_path TEXT UNIQUE NOT NULL,
                    game TEXT, triage TEXT CHECK(triage IN ('keep','discard')),
                    rating INTEGER CHECK(rating BETWEEN 1 AND 5),
                    tag TEXT, mainline TEXT, description TEXT,
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
                CREATE TABLE IF NOT EXISTS deleted_sources (
                    clip_id TEXT PRIMARY KEY REFERENCES clips ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS media_cache (
                    path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
                    duration REAL, created TEXT, error TEXT, inspected_at REAL NOT NULL
                );
            """)
            if version < 4:
                columns = {row["name"] for row in database.execute("PRAGMA table_info(clips)")}
                if "technical_condition" in columns:
                    database.execute("ALTER TABLE clips RENAME COLUMN technical_condition TO tag")
            if version < 3:
                for table, column in [
                    ("folders", "path"),
                    ("clips", "source_path"),
                    ("media_cache", "path"),
                ]:
                    rows = database.execute(f"SELECT {column} FROM {table}").fetchall()
                    for row in rows:
                        try:
                            restored = normalized(row[0])
                        except (OSError, RuntimeError):
                            continue
                        if restored != row[0]:
                            database.execute(
                                f"UPDATE {table} SET {column}=? WHERE {column}=?",
                                (restored, row[0]),
                            )
            if os.name == "nt":
                database.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS clip_path_identity "
                    "ON clips(source_path COLLATE NOCASE)"
                )
                database.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS folder_path_identity "
                    "ON folders(path COLLATE NOCASE)"
                )
            database.execute(
                "CREATE INDEX IF NOT EXISTS tag_casefold_identity "
                "ON clips(casefold(tag)) WHERE tag IS NOT NULL"
            )
            database.execute("PRAGMA user_version = 6")

    def hidden_deleted_ids(self):
        """Hide intentional deletions until their current (possibly relinked) source returns."""
        rows = self.rows("SELECT clip_id, source_path FROM deleted_sources JOIN clips USING(clip_id)")
        restored = {row["clip_id"] for row in rows if Path(row["source_path"]).is_file()}
        if restored:
            with self.connection() as database:
                database.executemany(
                    "DELETE FROM deleted_sources WHERE clip_id=?", [(clip_id,) for clip_id in restored]
                )
        return {row["clip_id"] for row in rows} - restored

    def media_cache(self):
        return {row["path"]: row for row in self.rows("SELECT * FROM media_cache")}

    def cache_media(self, entries, invalidated=()):
        with self.connection() as database:
            database.executemany(
                "DELETE FROM media_cache WHERE path=?", [(path,) for path in invalidated]
            )
            database.executemany(
                "INSERT OR REPLACE INTO media_cache VALUES "
                "(:path,:size,:mtime_ns,:duration,:created,:error,:inspected_at)",
                entries,
            )

    @contextmanager
    def connection(self):
        database = sqlite3.connect(self.path, timeout=10)
        database.row_factory = sqlite3.Row
        database.create_function(
            "casefold",
            1,
            lambda value: value.casefold() if isinstance(value, str) else value,
            deterministic=True,
        )
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

    def tag_exists(self, tag):
        return bool(
            self.rows(
                "SELECT 1 FROM clips "
                "WHERE tag IS NOT NULL AND casefold(tag)=? LIMIT 1",
                (tag.casefold(),),
            )
        )

    def state(self, key, default=None):
        rows = self.rows("SELECT value FROM state WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set_state(self, key, value):
        with self.connection() as database:
            database.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, json.dumps(value)))

    def folders(self):
        return self.rows("SELECT * FROM folders ORDER BY path COLLATE NOCASE")

    def clip_folder_names(self):
        return {
            row["clip_id"]: Path(row["path"]).name
            for row in self.rows(
                "SELECT sources.clip_id, folders.path "
                "FROM sources JOIN folders USING(folder_id)"
            )
        }

    def session_excluded_ids(self):
        return {
            row["clip_id"]
            for row in self.rows(
                "SELECT DISTINCT clip_id FROM sources JOIN folders USING(folder_id) WHERE enabled=0"
            )
        }

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

    def ingest(self, folder_id, discovered, cancelled=lambda: False):
        with self.connection() as database:
            for item in discovered:
                if cancelled():
                    raise InterruptedError("Scan cancelled")
                path = normalized(item["path"])
                database.execute(
                    """INSERT OR IGNORE INTO clips
                    (clip_id,source_path,game,catalogue_modified_at) VALUES (?,?,?,?)""",
                    (uuid4().hex, path, item["game"], now()),
                )
                clip_id = database.execute(
                    "SELECT clip_id FROM clips WHERE source_path=?"
                    + (" COLLATE NOCASE" if os.name == "nt" else ""),
                    (path,),
                ).fetchone()[0]
                if item["game"] is not None:
                    database.execute(
                        "UPDATE clips SET game=?,catalogue_modified_at=? "
                        "WHERE clip_id=? AND game IS NULL",
                        (item["game"], now(), clip_id),
                    )
                database.execute("INSERT OR IGNORE INTO sources VALUES (?,?)", (folder_id, clip_id))
            if cancelled():
                raise InterruptedError("Scan cancelled")

    def unlinked_clips(self):
        linked = {row["clip_id"] for row in self.rows("SELECT DISTINCT clip_id FROM sources")}
        return [clip for clip in self.clips() if clip["clip_id"] not in linked]

    def backup(self):
        directory = self.path.parent / "backups"
        directory.mkdir(exist_ok=True)
        target = directory / f"catalogue-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
        with self.connection() as source, sqlite3.connect(target) as destination:
            source.backup(destination)
        return target

    def _purge_clips(self, database, clip_ids):
        clip_ids = set(clip_ids)
        database.executemany(
            "DELETE FROM media_cache WHERE path=(SELECT source_path FROM clips WHERE clip_id=?)",
            [(clip_id,) for clip_id in clip_ids],
        )
        database.executemany(
            "DELETE FROM clips WHERE clip_id=?", [(clip_id,) for clip_id in clip_ids]
        )
        row = database.execute("SELECT value FROM state WHERE key='session'").fetchone()
        session = json.loads(row[0]) if row else None
        if session:
            previous = session["ids"]
            ids = [clip_id for clip_id in previous if clip_id not in clip_ids]
            current = next(
                (clip_id for clip_id in previous[session["index"] :] if clip_id not in clip_ids),
                ids[-1] if ids else None,
            )
            session = {"ids": ids, "index": ids.index(current)} if ids else None
            database.execute("UPDATE state SET value=? WHERE key='session'", (json.dumps(session),))

    def remove_unlinked(self, clip_ids):
        with self.connection() as database:
            database.execute("BEGIN IMMEDIATE")
            unlinked = {
                row[0]
                for row in database.execute(
                    "SELECT clip_id FROM clips WHERE NOT EXISTS "
                    "(SELECT 1 FROM sources WHERE sources.clip_id=clips.clip_id)"
                )
            }
            if not set(clip_ids) <= unlinked:
                raise ValueError(
                    "Some clips are linked to a folder now. Review the selection again."
                )
            self._purge_clips(database, clip_ids)
        self.undo_stack.clear()
        self.redo_stack.clear()

    def remove_folder(self, folder_id, purge=True):
        with self.connection() as database:
            database.execute("BEGIN IMMEDIATE")
            if purge:
                ids = [
                    row[0]
                    for row in database.execute(
                        "SELECT clip_id FROM sources WHERE folder_id=?", (folder_id,)
                    )
                ]
                self._purge_clips(database, ids)
            database.execute("DELETE FROM folders WHERE folder_id=?", (folder_id,))
        if purge:
            self.undo_stack.clear()
            self.redo_stack.clear()

    def migration_plan(self, folder_id, destination):
        folders = {folder["folder_id"]: folder for folder in self.folders()}
        if folder_id not in folders:
            raise ValueError("Capture folder no longer exists")
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
        existing = {Path(clip["source_path"]): clip["clip_id"] for clip in self.clips()}
        if len(targets) != len({Path(path) for path in targets}) or any(
            Path(path) in existing and existing[Path(path)] != clip_id for path, clip_id in updates
        ):
            raise ValueError("Migration would collide with an existing source identity")
        return str(new), rows, updates

    def migrate(self, folder_id, destination):
        new, rows, updates = self.migration_plan(folder_id, destination)
        targets = [path for path, clip_id in updates]
        with self.connection() as database:
            database.executemany(
                "DELETE FROM media_cache WHERE path=?",
                [(row["source_path"],) for row in rows] + [(path,) for path in targets],
            )
            database.executemany("UPDATE clips SET source_path=? WHERE clip_id=?", updates)
            database.execute("UPDATE folders SET path=? WHERE folder_id=?", (new, folder_id))
        self.hidden_deleted_ids()

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
        return self.clip(clip_id), sorted(self.memberships(clip_id))

    def snapshot(self, clip_id):
        return deepcopy(self._snapshot(clip_id))

    def draft_snapshot(
        self, snapshot, patch, *, editing=False, replace_metadata=False, membership=None,
        active_project=None,
    ):
        before = deepcopy(snapshot)
        after = deepcopy(snapshot)
        clip, memberships = after
        allowed = {
            "game",
            "triage",
            "rating",
            "tag",
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
        if (
            editing and clip["triage"] == "keep" and before[0]["triage"] != "keep"
            and active_project
        ):
            if active_project not in memberships:
                memberships.append(active_project)
        if membership:
            project_id, include = membership
            if include and project_id not in memberships:
                memberships.append(project_id)
            if not include and project_id in memberships:
                memberships.remove(project_id)
        memberships.sort()
        return after

    def _restore(self, snapshot):
        clip, memberships = snapshot
        fields = [
            "game",
            "triage",
            "rating",
            "tag",
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

    def commit_snapshot(self, baseline, draft):
        if baseline == draft:
            return False
        clip_id = baseline[0]["clip_id"]
        if draft[0]["clip_id"] != clip_id:
            raise ValueError("Atomic edit snapshot does not match the clip")
        current = self._snapshot(clip_id)
        current[1].sort()
        expected = deepcopy(baseline)
        expected[1].sort()
        if current != expected:
            raise ValueError(
                "Clip or project membership changed outside Editing. Review the newer catalogue state before saving."
            )
        fields = [
            "game", "triage", "rating", "tag", "mainline", "description",
            "metadata", "in_ms", "out_ms",
        ]
        clip, memberships = draft
        values = [json.dumps(clip[key]) if key == "metadata" else clip[key] for key in fields]
        with self.connection() as database:
            database.execute("BEGIN IMMEDIATE")
            persisted = database.execute("SELECT * FROM clips WHERE clip_id=?", (clip_id,)).fetchone()
            if persisted is None:
                raise ValueError("Clip no longer exists")
            persisted_clip = dict(persisted)
            persisted_clip["metadata"] = json.loads(persisted_clip["metadata"])
            persisted_memberships = sorted(
                row[0] for row in database.execute(
                    "SELECT project_id FROM members WHERE clip_id=?", (clip_id,)
                )
            )
            if (persisted_clip, persisted_memberships) != expected:
                raise ValueError(
                    "Clip or project membership changed outside Editing. Review the newer catalogue state before saving."
                )
            project_ids = {
                row[0] for row in database.execute("SELECT project_id FROM projects")
            }
            if not set(memberships) <= project_ids:
                raise ValueError(
                    "A staged project no longer exists. Review project membership before saving."
                )
            database.execute(
                "UPDATE clips SET " + ",".join(f"{key}=?" for key in fields)
                + ",catalogue_modified_at=? WHERE clip_id=?",
                [*values, now(), clip_id],
            )
            database.execute("DELETE FROM members WHERE clip_id=?", (clip_id,))
            database.executemany(
                "INSERT INTO members VALUES (?,?)",
                [(project_id, clip_id) for project_id in memberships],
            )
        after = self._snapshot(clip_id)
        self.undo_stack.append((deepcopy(baseline), after))
        self.redo_stack.clear()
        return True

    def patch(self, clip_id, patch, editing=False, replace_metadata=False, membership=None):
        before = self._snapshot(clip_id)
        after = self.draft_snapshot(
            before, patch, editing=editing, replace_metadata=replace_metadata,
            membership=membership, active_project=self.state("active_project"),
        )
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
        if self.session_excluded_ids().intersection(ids):
            raise ValueError("Clips from disabled capture folders cannot be added to a Session")
        self.set_state("session", {"ids": ids, "index": 0})

    def navigate(self, index):
        session = self.state("session")
        if not session:
            return
        session["index"] = max(0, min(index, len(session["ids"]) - 1))
        self.set_state("session", session)
