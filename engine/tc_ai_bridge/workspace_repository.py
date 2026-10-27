"""SQLite persistence for Bridge's app-level workspace store.

One database per installation (``%LOCALAPPDATA%\\Bridge\\data\\workspace.sqlite3``
on Windows; callers decide the path, this module only opens what it is
given), holding what is *about* projects rather than *inside* one:

- ``devices`` -- one generated, stable device id per installation;
- ``users`` -- one stable local ``user_id`` (#76), so every workbench write
  has a real ``actor_id``/``device_id`` pair to stamp;
- ``projects`` -- the project registry (#77; formerly ``project-registry.json``);
- ``settings_kv`` -- non-secret application settings (#77; DPAPI-wrapped
  secrets stay in ``settings.json``, see ``secret_store.py``);
- ``project_progress_cache`` -- one cached progress rollup per project, so the
  multi-book dashboard reads one table instead of opening every sibling's
  per-project workbench database (#77, ``docs/TEAM_ARCHITECTURE.md`` section 4).

Why the ``user_id`` exists before #78 builds real identity: ``change_log``
is append-only and its ``BEFORE UPDATE``/``BEFORE DELETE`` triggers reject
every column but ``synced_at``, so whatever ``actor_id`` a workbench write
stamps is permanent and cannot be backfilled later. The only identity that
existed before this was ``AppSettings.reviewer_name`` -- a *display name*
the user can change in Settings at any time (and which V11-005 reseeds), so
stamping it would mean one person's history splits irreversibly into two
un-linkable sets of immutable rows the first time they rename themselves.
The id here is stable and the display name hangs off it, which is the shape
section 5 specifies ("every workbench write carries ``actor_id = user_id``;
display names resolve at read time"). Roles, ``authorize()`` and real
multi-user remain #78's.

Schema changes are migrations here too (CLAUDE.md). This is the third
versioned ladder, independent of both the semantic database
(``DATABASE_SCHEMA_VERSION``) and the workbench (``WORKBENCH_SCHEMA_VERSION``):
a bump here is never a bump there. ``_MIGRATION_V1`` is deliberately what the
first version of this module created with ``CREATE TABLE IF NOT EXISTS`` and
no version number at all, so a database made by that code is adopted as v1
-- its device and user ids are already stamped on immutable workbench rows
and must survive -- rather than treated as unversioned. Every later change
is a new forward block.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Iterator
import os
import uuid


WORKSPACE_SCHEMA_VERSION = 5
WORKSPACE_SCHEMA_ID = "bridge-workspace"

# #338: the last-good copy of the workspace database, written beside it on
# every healthy open (VACUUM INTO, one statement, milliseconds at this file's
# size) -- at startup, not shutdown, because a crash on exit is one of the
# ways the file gets damaged. It is the first thing recovery restores.
LAST_GOOD_BACKUP_SUFFIX = ".last-good.sqlite3"
QUARANTINE_INFIX = ".quarantined-"

# What SQLite says about a file that is not, or no longer, a database. Any
# other DatabaseError (locked, busy, read-only, cannot open) is a condition
# to report, not damage to quarantine, and is re-raised as before.
_DAMAGE_MARKERS = ("not a database", "malformed", "corrupt", "disk image")

# v1: exactly the two tables the unversioned first cut of this module created.
# IF NOT EXISTS is correct *here and only here*: the block has to adopt an
# existing database as much as build a fresh one.
_MIGRATION_V1 = r"""
CREATE TABLE IF NOT EXISTS devices(
    device_id TEXT PRIMARY KEY,
    machine_id TEXT,
    os_user TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users(
    user_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
"""

# v2 (#77): the project registry, non-secret settings and the per-project
# progress rollup cache. `entry_json` on `projects` keeps the registry entry
# exactly as `project-registry.json` held it, so `ProjectRegistry` returns the
# same dict shape it always did; the lifted columns are the ones it looks rows
# up by. `project_progress_cache.source_seq` is the workbench `change_log.seq`
# of the progress_totals write the cached totals came from, which is what lets
# a project open detect a cache that lags (or predates a re-import) and repair
# it -- see TranslationCoreProject.sync_progress_cache.
_MIGRATION_V2 = r"""
CREATE TABLE projects(
    project_id TEXT PRIMARY KEY,
    collection_id TEXT,
    path TEXT NOT NULL,
    path_key TEXT NOT NULL,
    managed INTEGER NOT NULL DEFAULT 0,
    missing INTEGER NOT NULL DEFAULT 0,
    last_opened_at TEXT,
    position INTEGER NOT NULL,
    entry_json TEXT NOT NULL
);
CREATE INDEX ix_projects_path_key ON projects(path_key);
CREATE INDEX ix_projects_collection ON projects(collection_id);

CREATE TABLE settings_kv(
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE project_progress_cache(
    path_key TEXT PRIMARY KEY,
    project_path TEXT NOT NULL,
    project_id TEXT NOT NULL,
    book_id TEXT NOT NULL,
    totals_json TEXT NOT NULL,
    updated_at TEXT,
    source_seq INTEGER NOT NULL,
    refreshed_at TEXT NOT NULL
);
"""

# v3 (#238): the projects list's archive flag and who opened a project last.
# Both are lifted from `entry_json` (`archivedAt`, `lastOpenedBy`) the way
# `last_opened_at` is, so a list can filter and sort without parsing JSON;
# the entry stays the record. Additive: nothing is rebuilt.
_MIGRATION_V3 = r"""
ALTER TABLE projects ADD COLUMN archived_at TEXT;
ALTER TABLE projects ADD COLUMN last_opened_by TEXT;
"""

# v4 (#236): the user's role. The default is project_admin because a
# single-user installation always was one; a second user is given a role by
# a project_admin on the Users screen (#237). Additive.
_MIGRATION_V4 = r"""
ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'project_admin';
"""

# v5 (#240): one cached list of assignments per book, keyed like the
# progress cache and refreshed from the same `change_log.seq` discipline,
# so the dashboard's "My work" reads 66 books in one query and never opens a
# sibling's database. The workbench row is the record; this is a copy.
_MIGRATION_V5 = r"""
CREATE TABLE project_assignments_cache(
    path_key TEXT PRIMARY KEY,
    project_path TEXT NOT NULL,
    project_id TEXT NOT NULL,
    book_id TEXT NOT NULL,
    assignments_json TEXT NOT NULL,
    source_seq INTEGER NOT NULL,
    refreshed_at TEXT NOT NULL
);
"""

_MIGRATIONS: tuple[tuple[int, str], ...] = (
    (1, _MIGRATION_V1),
    (2, _MIGRATION_V2),
    (3, _MIGRATION_V3),
    (4, _MIGRATION_V4),
    (5, _MIGRATION_V5),
)


class WorkspaceError(RuntimeError):
    pass


def project_path_key(path: str | Path) -> str:
    """The comparison key the registry uses for a project path, so the
    progress cache and `projects` agree on what "the same folder" means
    (Windows path aliases, case, trailing separators)."""
    resolved = Path(path).expanduser().resolve(strict=False)
    return os.path.normcase(os.path.normpath(str(resolved)))


def _is_damage(exc: BaseException) -> bool:
    message = str(exc).lower()
    return isinstance(exc, sqlite3.DatabaseError) and any(marker in message for marker in _DAMAGE_MARKERS)


class WorkspaceRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # #338: None after a healthy open; otherwise what recovery did
        # (the quarantined file's name, restored / rebuilt, what was lost).
        # BridgeEngine reports it on engine.info and project.open; it is
        # never an error.
        self.recovery: dict[str, Any] | None = None
        self.backup_error: str = ""
        self._open_with_recovery()
        self._write_last_good_backup()

    # -- #338: the recovery ladder -------------------------------------------

    @property
    def last_good_backup_path(self) -> Path:
        return self.path.with_name(self.path.stem + LAST_GOOD_BACKUP_SUFFIX)

    def _open_with_recovery(self) -> None:
        """Decided 2026-10-24 (#338, docs/DECISIONS.md), each step only when
        the one before fails: 1. the engine always starts -- a damaged file
        and its -wal/-shm are renamed to a timestamped quarantine name beside
        it, nothing is deleted; 2. the last-good backup is restored if it
        exists and opens cleanly; 4. (the registry rediscovers data\\projects
        on its first list, always); 5. the outcome is reported. Tier 3,
        salvage from the quarantined copy table by table, is not built."""
        try:
            self._migrate()
            return
        except sqlite3.DatabaseError as exc:
            if not _is_damage(exc):
                raise
            damage = str(exc)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        quarantined = self._quarantine(stamp, "")
        recovery: dict[str, Any] = {
            "at": self._now(), "error": damage, "quarantined": quarantined,
            "outcome": "", "backup": "", "backupWrittenAt": "", "backupError": "", "lost": [],
        }
        backup = self.last_good_backup_path
        if backup.is_file():
            recovery["backup"] = backup.name
            try:
                recovery["backupWrittenAt"] = datetime.fromtimestamp(
                    backup.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            except OSError:
                pass
            shutil.copyfile(backup, self.path)
            try:
                self._migrate()
                recovery["outcome"] = "restored"
                recovery["lost"] = [
                    "changes made since the backup was written: bookmarks and recent chapters, "
                    "projects added or renamed, settings changed in that session",
                ]
                self.recovery = recovery
                return
            except sqlite3.DatabaseError as exc:
                if not _is_damage(exc):
                    raise
                recovery["backupError"] = str(exc)
                recovery["backupQuarantined"] = self._quarantine(stamp, "-backup")
        self._migrate()  # a fresh database, built by running the ladder
        recovery["outcome"] = "rebuilt"
        recovery["lost"] = [
            "users and their roles (the local user is created again)",
            "the device id (a new one is minted)",
            "non-secret settings: bookmarks, recent chapters, the reference Bible choice, "
            "the hub address and links",
            "external project paths (projects outside data\\projects must be located again)",
            "the dashboard's progress cache (rebuilt as books are opened)",
        ]
        self.recovery = recovery

    def _quarantine(self, stamp: str, tag: str) -> str:
        """Rename the database and its -wal / -shm beside themselves under a
        quarantine name. Nothing is deleted. Returns the database's new name."""
        target = self.path.with_name(f"{self.path.stem}{QUARANTINE_INFIX}{stamp}{tag}{self.path.suffix}")
        for suffix in ("", "-wal", "-shm"):
            source = Path(str(self.path) + suffix)
            if source.exists():
                try:
                    os.replace(source, Path(str(target) + suffix))
                except OSError:
                    # A file something else holds open cannot be moved; the
                    # fresh database is still built under the ordinary name
                    # once the lock clears, and the next open reports again.
                    pass
        return target.name

    def _write_last_good_backup(self) -> None:
        """VACUUM INTO a sibling file, then replace the previous last-good copy
        atomically. A failure here never fails the open; it is recorded."""
        self.backup_error = ""
        temp = self.last_good_backup_path.with_name(self.last_good_backup_path.name + ".tmp")
        try:
            if temp.exists():
                temp.unlink()
            with self._connect() as conn:
                conn.execute("VACUUM INTO ?", (str(temp),))
            os.replace(temp, self.last_good_backup_path)
        except (sqlite3.DatabaseError, OSError) as exc:
            self.backup_error = str(exc)
            try:
                if temp.exists():
                    temp.unlink()
            except OSError:
                pass

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=5.0)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.execute("PRAGMA synchronous = FULL")
            conn.execute("PRAGMA journal_mode = WAL")
            if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
                raise WorkspaceError("SQLite foreign-key enforcement could not be enabled")
        except Exception:
            # #338: a file that is not a database fails on the first PRAGMA.
            # The handle must close here, or Windows keeps the damaged file
            # open and recovery cannot rename it aside.
            conn.close()
            raise
        try:
            yield conn
        finally:
            conn.close()

    # -- schema ladder, same discipline as WorkbenchRepository ---------------

    def _migrate(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations("
                "version INTEGER PRIMARY KEY, schema_id TEXT NOT NULL, applied_at TEXT NOT NULL)"
            )
            current = int(conn.execute(
                "SELECT COALESCE(MAX(version),0) FROM schema_migrations"
            ).fetchone()[0])
            if current > WORKSPACE_SCHEMA_VERSION:
                raise WorkspaceError(
                    f"Workspace schema {current} is newer than supported v{WORKSPACE_SCHEMA_VERSION}"
                )
            # Decided once, before the ladder runs: a fresh database gains
            # tables at v1, and backing it up before v2 would copy nothing
            # anyone wrote. A database written by the unversioned first cut
            # has current == 0 but real rows, so this tests for tables, not
            # for a version above zero.
            pre_existing = bool(conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name <> 'schema_migrations'"
            ).fetchone()[0])
            for version, script in _MIGRATIONS:
                if version <= current:
                    continue
                if pre_existing:
                    self._backup_before_migration(conn, current, version)
                self._apply_migration(conn, version, script)
                current = version

    def _backup_before_migration(self, conn: sqlite3.Connection, current: int, target: int) -> None:
        """Create a consistent, inspectable backup before upgrading an existing DB.

        Only called for a database that held tables before this open began
        (see `_migrate`), so there is always something worth copying.
        """
        root = self.path.parent / "backups"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        directory = root / f"pre-workspace-v{target}-{stamp}"
        directory.mkdir(parents=True, exist_ok=False)
        backup_db = directory / self.path.name
        destination = sqlite3.connect(str(backup_db))
        try:
            conn.backup(destination)
        finally:
            destination.close()
        digest = hashlib.sha256(backup_db.read_bytes()).hexdigest()
        manifest = {
            "reason": f"automatic backup before workspace schema migration v{current} to v{target}",
            "schemaId": WORKSPACE_SCHEMA_ID,
            "schemaVersion": current,
            "source": str(self.path),
            "targetSchemaVersion": target,
            "sha256": digest,
            "createdAt": self._now(),
        }
        (directory / "backup-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )

    def _apply_migration(self, conn: sqlite3.Connection, version: int, script: str) -> None:
        schema_id = WORKSPACE_SCHEMA_ID.replace("'", "''")
        applied_at = self._now().replace("'", "''")
        conn.executescript(
            "BEGIN IMMEDIATE;\n"
            + script
            + f"\nINSERT INTO schema_migrations(version,schema_id,applied_at) "
              f"VALUES({version},'{schema_id}','{applied_at}');\n"
            + f"PRAGMA user_version = {version};\nCOMMIT;"
        )

    def schema_version(self) -> int:
        with self._connect() as conn:
            return int(
                conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()[0]
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # -- devices and users ----------------------------------------------------

    def get_or_create_device_id(self) -> str:
        """Return this installation's device id, minting one on first call.

        One workspace database is one installation, so the first row wins;
        machine_id/os_user population is #78's job, not this one's.
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT device_id FROM devices ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is not None:
                conn.commit()
                return str(row["device_id"])
            device_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO devices(device_id, machine_id, os_user, created_at) VALUES(?,?,?,?)",
                (device_id, None, None, self._now()),
            )
            conn.commit()
            return device_id

    def user_display_names(self) -> dict[str, str]:
        """user_id -> display name for every user this installation knows
        (#238: the projects list's "last opened by")."""
        with self._connect() as conn:
            rows = conn.execute("SELECT user_id, display_name FROM users").fetchall()
        return {str(row["user_id"]): str(row["display_name"]) for row in rows}

    def get_or_create_local_user(self, display_name: str, current_user_id: str = "") -> dict[str, str]:
        """Return this installation's local user, minting one on first call.

        The ``user_id`` is stable for the life of the workspace database and
        is what every workbench write stamps. ``display_name`` is refreshed
        from the caller on every call -- renaming yourself in Settings must
        change how you are shown everywhere, past rows included, *without*
        detaching you from the history you already wrote. That is the whole
        reason the two are separate columns.

        One workspace database is one installation, so the first (oldest)
        active row wins. Choosing between several users is #78's job.
        """
        name = str(display_name or "").strip() or "Unnamed Reviewer"
        now = self._now()
        chosen = str(current_user_id or "").strip()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = None
            if chosen:
                # #237: the user chosen at startup or on the Users screen, if
                # still active; otherwise the oldest active row as before.
                row = conn.execute(
                    "SELECT user_id, display_name, role FROM users WHERE user_id=? AND active=1", (chosen,)
                ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT user_id, display_name, role FROM users WHERE active=1 ORDER BY created_at LIMIT 1"
                ).fetchone()
            if row is not None:
                user_id = str(row["user_id"])
                if str(row["display_name"]) != name:
                    conn.execute(
                        "UPDATE users SET display_name=?, updated_at=? WHERE user_id=?",
                        (name, now, user_id),
                    )
                conn.commit()
                return {"userId": user_id, "displayName": name, "role": str(row["role"] or "project_admin")}
            user_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO users(user_id, display_name, created_at, updated_at, active, role) "
                "VALUES(?,?,?,?,1,'project_admin')",
                (user_id, name, now, now),
            )
            conn.commit()
            return {"userId": user_id, "displayName": name, "role": "project_admin"}

    def list_users(self) -> list[dict[str, Any]]:
        """Every user this installation knows, active or not, oldest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT user_id, display_name, role, active, created_at, updated_at FROM users ORDER BY created_at, user_id"
            ).fetchall()
        return [self._user_row(row) for row in rows]

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, display_name, role, active, created_at, updated_at FROM users WHERE user_id=?",
                (str(user_id),),
            ).fetchone()
        return self._user_row(row) if row is not None else None

    @staticmethod
    def _user_row(row: Any) -> dict[str, Any]:
        return {
            "userId": str(row["user_id"]), "displayName": str(row["display_name"]),
            "role": str(row["role"] or "project_admin"), "active": bool(row["active"]),
            "createdAt": str(row["created_at"]), "updatedAt": str(row["updated_at"]),
        }

    def create_user(self, display_name: str, role: str) -> dict[str, Any]:
        name = str(display_name or "").strip()
        if not name:
            raise WorkspaceError("A user needs a display name.")
        now = self._now()
        user_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO users(user_id, display_name, created_at, updated_at, active, role) VALUES(?,?,?,?,1,?)",
                (user_id, name, now, now, str(role)),
            )
            conn.commit()
        return self.get_user(user_id) or {}

    def rename_user(self, user_id: str, display_name: str) -> dict[str, Any]:
        """The id never changes: every row this person wrote re-labels."""
        name = str(display_name or "").strip()
        if not name:
            raise WorkspaceError("A user needs a display name.")
        with self._connect() as conn:
            changed = conn.execute(
                "UPDATE users SET display_name=?, updated_at=? WHERE user_id=?", (name, self._now(), str(user_id)),
            ).rowcount
            conn.commit()
        if not changed:
            raise WorkspaceError("Unknown user.")
        return self.get_user(user_id) or {}

    def set_user_active(self, user_id: str, active: bool) -> dict[str, Any]:
        with self._connect() as conn:
            changed = conn.execute(
                "UPDATE users SET active=?, updated_at=? WHERE user_id=?", (1 if active else 0, self._now(), str(user_id)),
            ).rowcount
            conn.commit()
        if not changed:
            raise WorkspaceError("Unknown user.")
        return self.get_user(user_id) or {}

    def upsert_user(self, user_id: str, display_name: str, role: str) -> None:
        """A user the hub knows, written under the hub's own id (#338: after a
        recovery the hub is the source for who the users are and what role
        each holds). An existing row keeps its created_at and active flag."""
        now = self._now()
        name = str(display_name or "").strip() or "Unnamed Reviewer"
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO users(user_id, display_name, created_at, updated_at, active, role) "
                "VALUES(?,?,?,?,1,?) ON CONFLICT(user_id) DO UPDATE SET display_name=excluded.display_name, "
                "role=excluded.role, updated_at=excluded.updated_at",
                (str(user_id), name, now, now, str(role)),
            )
            conn.commit()

    def set_user_role(self, user_id: str, role: str) -> None:
        """#236: give a user one of the three roles. The caller has checked
        the value against `authorization.Role`."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET role=?, updated_at=? WHERE user_id=?", (str(role), self._now(), str(user_id)),
            )
            conn.commit()

    # -- per-project progress rollup cache (TEAM_ARCHITECTURE.md section 4) --
    #
    # The multi-book dashboard needs one number per book for every sibling in
    # a collection, most of which have never been opened this session. Each
    # book's rollup lives in its own workbench database, and opening 66 of
    # those to answer "how far along is this Bible" is worse than the 66 file
    # reads it replaces. So the totals are cached here, keyed by project
    # folder, refreshed by the project that wrote them and repaired on its
    # next open when `source_seq` disagrees with the workbench change_log.

    def upsert_progress_cache(
        self,
        project_path: str | Path,
        *,
        project_id: str,
        book_id: str,
        totals: dict[str, Any],
        updated_at: str | None,
        source_seq: int,
    ) -> None:
        self.upsert_progress_cache_many([{
            "projectPath": project_path, "projectId": project_id, "bookId": book_id,
            "totals": totals, "updatedAt": updated_at, "sourceSeq": source_seq,
        }])

    def upsert_progress_cache_many(self, entries: list[dict[str, Any]]) -> None:
        """Several entries in one commit. The dashboard's cold-cache refill
        peeks every sibling with no entry and writes them all back; one
        transaction is one fsync instead of one per book."""
        if not entries:
            return
        now = self._now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for entry in entries:
                conn.execute(
                    "INSERT INTO project_progress_cache(path_key, project_path, project_id, book_id, "
                    "totals_json, updated_at, source_seq, refreshed_at) VALUES(?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(path_key) DO UPDATE SET project_path=excluded.project_path, "
                    "project_id=excluded.project_id, book_id=excluded.book_id, "
                    "totals_json=excluded.totals_json, updated_at=excluded.updated_at, "
                    "source_seq=excluded.source_seq, refreshed_at=excluded.refreshed_at",
                    (
                        project_path_key(entry["projectPath"]), str(Path(entry["projectPath"])),
                        str(entry["projectId"]), str(entry["bookId"]),
                        json.dumps(entry["totals"], ensure_ascii=False), entry.get("updatedAt"),
                        int(entry["sourceSeq"]), now,
                    ),
                )
            conn.commit()

    def progress_cache_entry(self, project_path: str | Path) -> dict[str, Any] | None:
        found = self.progress_cache_for_paths([project_path])
        return found.get(project_path_key(project_path))

    def progress_cache_for_paths(self, paths: list[str | Path]) -> dict[str, dict[str, Any]]:
        """Cached rollups for several project folders in one query, keyed by
        :func:`project_path_key`. Folders with no entry are simply absent."""
        return self.progress_cache_by_keys([project_path_key(path) for path in paths])

    def progress_cache_by_keys(self, keys: list[str]) -> dict[str, dict[str, Any]]:
        """:meth:`progress_cache_for_paths` for callers that already hold the
        keys -- `project_path_key` resolves the path, and the dashboard has
        66 of them to resolve exactly once."""
        if not keys:
            return {}
        out: dict[str, dict[str, Any]] = {}
        with self._connect() as conn:
            for start in range(0, len(keys), 500):
                chunk = keys[start:start + 500]
                rows = conn.execute(
                    "SELECT * FROM project_progress_cache WHERE path_key IN ("
                    + ",".join("?" for _ in chunk) + ")",
                    chunk,
                ).fetchall()
                for row in rows:
                    try:
                        totals = json.loads(row["totals_json"])
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(totals, dict):
                        continue
                    out[str(row["path_key"])] = {
                        "projectPath": str(row["project_path"]),
                        "projectId": str(row["project_id"]),
                        "bookId": str(row["book_id"]),
                        "totals": totals,
                        "updatedAt": row["updated_at"],
                        "sourceSeq": int(row["source_seq"]),
                        "refreshedAt": str(row["refreshed_at"]),
                    }
        return out

    # -- per-book assignments cache (#240) --------------------------------

    def upsert_assignments_cache(self, project_path: str | Path, *, project_id: str, book_id: str,
                                 assignments: list[dict[str, Any]], source_seq: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO project_assignments_cache(path_key, project_path, project_id, book_id, "
                "assignments_json, source_seq, refreshed_at) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(path_key) DO UPDATE SET project_path=excluded.project_path, "
                "project_id=excluded.project_id, book_id=excluded.book_id, "
                "assignments_json=excluded.assignments_json, source_seq=excluded.source_seq, "
                "refreshed_at=excluded.refreshed_at",
                (
                    project_path_key(project_path), str(project_path), str(project_id), str(book_id),
                    json.dumps(list(assignments), ensure_ascii=False), int(source_seq), self._now(),
                ),
            )
            conn.commit()

    def assignments_cache_by_keys(self, keys: list[str]) -> dict[str, dict[str, Any]]:
        if not keys:
            return {}
        out: dict[str, dict[str, Any]] = {}
        with self._connect() as conn:
            for i in range(0, len(keys), 500):
                chunk = keys[i:i + 500]
                rows = conn.execute(
                    "SELECT path_key, project_id, book_id, assignments_json, source_seq FROM project_assignments_cache "
                    f"WHERE path_key IN ({','.join('?' * len(chunk))})", chunk,
                ).fetchall()
                for row in rows:
                    try:
                        assignments = json.loads(row["assignments_json"])
                    except (TypeError, ValueError):
                        assignments = []
                    out[str(row["path_key"])] = {
                        "projectId": str(row["project_id"]), "bookId": str(row["book_id"]),
                        "assignments": assignments if isinstance(assignments, list) else [],
                        "sourceSeq": int(row["source_seq"]),
                    }
        return out

    def assignments_cache_entry(self, project_path: str | Path) -> dict[str, Any] | None:
        return self.assignments_cache_by_keys([project_path_key(project_path)]).get(project_path_key(project_path))

    def forget_assignments_cache(self, paths: list[str | Path]) -> int:
        keys = [project_path_key(path) for path in paths]
        if not keys:
            return 0
        with self._connect() as conn:
            cur = conn.execute(
                f"DELETE FROM project_assignments_cache WHERE path_key IN ({','.join('?' * len(keys))})", keys,
            )
            conn.commit()
            return int(cur.rowcount)

    def forget_progress_cache(self, paths: list[str | Path]) -> int:
        """Drop cache entries for folders that are being deleted, forgotten or
        re-imported, so a stale rollup cannot outlive the project it described."""
        keys = [project_path_key(path) for path in paths]
        if not keys:
            return 0
        removed = 0
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for start in range(0, len(keys), 500):
                chunk = keys[start:start + 500]
                removed += conn.execute(
                    "DELETE FROM project_progress_cache WHERE path_key IN ("
                    + ",".join("?" for _ in chunk) + ")",
                    chunk,
                ).rowcount
            conn.commit()
        return removed

    # -- project registry (formerly project-registry.json) -------------------
    #
    # `ProjectRegistry` keeps its whole-list-in-memory model; these two calls
    # are its load and save. `entry_json` holds each entry exactly as the file
    # did, so `list_projects()` returns the same dicts; the lifted columns are
    # the ones the registry looks rows up by.

    def load_project_entries(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT entry_json FROM projects ORDER BY position, rowid").fetchall()
        entries: list[dict[str, Any]] = []
        for row in rows:
            try:
                value = json.loads(row["entry_json"])
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                entries.append(value)
        return entries

    def save_project_entries(self, entries: list[dict[str, Any]]) -> None:
        """Replace the registry with `entries`, in one transaction -- the
        semantics the atomic file rewrite had."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM projects")
            for position, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    continue
                conn.execute(
                    "INSERT INTO projects(project_id, collection_id, path, path_key, managed, missing, "
                    "last_opened_at, position, entry_json, archived_at, last_opened_by) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(entry.get("projectId") or ""), str(entry.get("collectionId") or "") or None,
                        str(entry.get("path") or ""), str(entry.get("pathKey") or ""),
                        1 if entry.get("managed") else 0, 1 if entry.get("missing") else 0,
                        str(entry.get("lastOpenedAt") or "") or None, position,
                        json.dumps(entry, ensure_ascii=False),
                        str(entry.get("archivedAt") or "") or None,
                        str(entry.get("lastOpenedBy") or "") or None,
                    ),
                )
            conn.commit()

    # -- non-secret settings ---------------------------------------------------
    #
    # DPAPI-wrapped secrets stay in settings.json (`secret_store.py`); every
    # other setting is a row here. `AppSettings` loads the whole map once and
    # replaces it on every save, which is what the file write did.

    def load_settings(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value_json FROM settings_kv").fetchall()
        out: dict[str, Any] = {}
        for row in rows:
            try:
                out[str(row["key"])] = json.loads(row["value_json"])
            except (TypeError, ValueError):
                continue
        return out

    def replace_settings(self, values: dict[str, Any]) -> None:
        now = self._now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            keys = list(values.keys())
            if keys:
                conn.execute(
                    "DELETE FROM settings_kv WHERE key NOT IN (" + ",".join("?" for _ in keys) + ")", keys,
                )
            else:
                conn.execute("DELETE FROM settings_kv")
            for key, value in values.items():
                conn.execute(
                    "INSERT INTO settings_kv(key, value_json, updated_at) VALUES(?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, "
                    "updated_at=excluded.updated_at",
                    (str(key), json.dumps(value, ensure_ascii=False), now),
                )
            conn.commit()
