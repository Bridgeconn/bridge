"""The team hub: `bridge-engine --serve` (#79 transport, #80 first slice).

An optional `[server]` extra (FastAPI, uvicorn), imported only by `main.py`
when `--serve` is given and never imported by `bridge_service.py` (a test
pins that), so the stdio path has no server and no network path (DECISIONS
2026-09-11). Since 2026-10-23 (#46) the frozen sidecar carries it, and
Settings > Team > Start a hub runs it as a child of the desktop engine with
`--parent-pid`, so it never outlives the app.

**Identity.** A name and a device, never a password (DECISIONS 2026-09-11).
An administrator hands out a join code; a device posts it with a display
name and gets a device token. The hub stores only the token's sha256. The
first start writes one project_admin join code to `admin-join-code.txt` in
the data dir, so the first administrator can join without a second tool.

**`/rpc`** carries the stdio envelope (`{id, method, params, session}`) and
needs a device token; the engine runs the request as that token's user, so
`authorize()` refuses a reporter's write exactly as on the desktop.

**Sync** (`/hub/projects/link`, `/sync/push`, `/sync/pull`) is an append-only
event store per hub project. The hub never applies events and never merges:
devices apply what they pull through their own revision check and keep any
conflict for a human (`tc_ai_bridge/hub_sync.py`). Pushing is an editor's or
admin's; pulling is anyone's who has joined. A push is idempotent on
`event_id`, and only the tables in `SYNCED_TABLES` are accepted.

Requests are serialised by one lock: the engine swaps per-session state per
request and its dispatcher assumes one at a time, as the stdio loop does.
The server binds to 127.0.0.1 unless `--host` says otherwise.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest, EngineResponse
from tc_ai_bridge.authorization import Action, AuthorizationError, Role, authorize, effective_role, parse_role
from tc_ai_bridge.hub_sync import SYNCED_TABLES
from tc_ai_bridge.secret_store import AppSettings

PULL_PAGE = 1000
HUB_SCHEMA = r"""
CREATE TABLE IF NOT EXISTS join_codes (
    code_hash TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS devices (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT
);
CREATE TABLE IF NOT EXISTS projects (
    hub_project_id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    hub_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    hub_project_id TEXT NOT NULL,
    pushed_by TEXT NOT NULL,
    received_at TEXT NOT NULL,
    event_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_project ON events(hub_project_id, hub_seq);
CREATE TABLE IF NOT EXISTS progress (
    hub_project_id TEXT PRIMARY KEY,
    snapshot_json TEXT NOT NULL,
    posted_by TEXT NOT NULL,
    posted_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class HubStore:
    """The hub's own SQLite file. Append-only for events; the hub is a copy
    of what every device holds, so losing it costs a re-sync, not data."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(HUB_SCHEMA)
            conn.commit()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        try:
            yield conn
        finally:
            conn.close()

    # -- join codes and devices ------------------------------------------------

    def create_join_code(self, role: str, created_by: str) -> str:
        code = "-".join(secrets.token_hex(2).upper() for _ in range(3))
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO join_codes(code_hash, role, created_at, created_by) VALUES(?,?,?,?)",
                (_hash(code), parse_role(role).value, _now(), created_by),
            )
            conn.commit()
        return code

    def join(self, code: str, display_name: str, device_id: str, user_id: str = "") -> dict[str, Any]:
        name = str(display_name or "").strip()
        if not name:
            raise HTTPException(400, "A display name is needed to join.")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT role FROM join_codes WHERE code_hash=? AND revoked_at IS NULL",
                (_hash(str(code or "").strip().upper()),),
            ).fetchone()
            if row is None:
                raise HTTPException(403, "That join code is not valid on this hub.")
            token = secrets.token_urlsafe(32)
            # #81: a desktop joins under its own stable user id so the same
            # person is the same id here and on the device ("My work"); a
            # browser has none and gets a fresh one. The join code is the
            # trust: it grants the role, whatever id the holder brings.
            user_id = str(user_id or "").strip() or str(uuid.uuid4())
            conn.execute(
                "INSERT INTO devices(token_hash, user_id, display_name, role, device_id, created_at) VALUES(?,?,?,?,?,?)",
                (_hash(token), user_id, name, row["role"], str(device_id or ""), _now()),
            )
            conn.execute("UPDATE join_codes SET uses = uses + 1 WHERE code_hash=?", (_hash(str(code).strip().upper()),))
            conn.commit()
        return {"token": token, "userId": user_id, "displayName": name, "role": row["role"]}

    def device(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM devices WHERE token_hash=?", (_hash(token),)).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE devices SET last_seen_at=? WHERE token_hash=?", (_now(), row["token_hash"]))
            conn.commit()
        return {"userId": row["user_id"], "displayName": row["display_name"], "role": row["role"],
                "deviceId": row["device_id"], "lastSeenAt": row["last_seen_at"]}

    def users(self) -> list[dict[str, Any]]:
        """One row per person (a user id may hold several device tokens)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT user_id, display_name, role, MAX(last_seen_at) AS last_seen_at, COUNT(*) AS devices "
                "FROM devices GROUP BY user_id ORDER BY display_name"
            ).fetchall()
        return [{"userId": r["user_id"], "displayName": r["display_name"], "role": r["role"],
                 "lastSeenAt": r["last_seen_at"], "devices": int(r["devices"])} for r in rows]

    def presence(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT display_name, role, device_id, last_seen_at FROM devices ORDER BY last_seen_at DESC"
            ).fetchall()
        return [{"displayName": r["display_name"], "role": r["role"], "deviceId": r["device_id"],
                 "lastSeenAt": r["last_seen_at"]} for r in rows]

    # -- projects --------------------------------------------------------------

    def link(self, book_id: str, source_sha256: str, local_project_id: str, user_id: str) -> dict[str, Any]:
        """The first device to link a book registers it under its own local id;
        every later device with the same book and source joins that one."""
        book = str(book_id or "").lower()
        sha = str(source_sha256 or "")
        if not book or not sha or not local_project_id:
            raise HTTPException(400, "Linking needs the book, its source sha256 and the local project id.")
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM projects WHERE book_id=? AND source_sha256=? ORDER BY created_at LIMIT 1", (book, sha),
            ).fetchone()
            if existing is not None:
                return {"hubProjectId": existing["hub_project_id"], "created": False}
            taken = conn.execute("SELECT 1 FROM projects WHERE hub_project_id=?", (local_project_id,)).fetchone()
            if taken is not None:
                raise HTTPException(409, "That project id is already linked to a different book or source.")
            conn.execute(
                "INSERT INTO projects(hub_project_id, book_id, source_sha256, created_at, created_by) VALUES(?,?,?,?,?)",
                (local_project_id, book, sha, _now(), user_id),
            )
            conn.commit()
        return {"hubProjectId": local_project_id, "created": True}

    def post_progress(self, hub_project_id: str, snapshot: dict[str, Any], posted_by: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO progress(hub_project_id, snapshot_json, posted_by, posted_at) VALUES(?,?,?,?) "
                "ON CONFLICT(hub_project_id) DO UPDATE SET snapshot_json=excluded.snapshot_json, "
                "posted_by=excluded.posted_by, posted_at=excluded.posted_at",
                (hub_project_id, json.dumps(snapshot, ensure_ascii=False), posted_by, _now()),
            )
            conn.commit()

    def _assignment_rows(self, conn: sqlite3.Connection, hub_project_id: str) -> dict[str, dict[str, Any]]:
        return self._folded_rows(conn, hub_project_id, "team_assignments")

    def team_roles(self, hub_project_id: str) -> dict[str, str]:
        """#279: {user id: role} on one project, folded from its team_members events."""
        with self._connect() as conn:
            rows = self._folded_rows(conn, hub_project_id, "team_members")
        return {str(r["payload"].get("userId") or ""): str(r["payload"].get("role") or "")
                for r in rows.values() if r["payload"].get("userId") and r["payload"].get("role")}

    def _folded_rows(self, conn: sqlite3.Connection, hub_project_id: str, table: str) -> dict[str, dict[str, Any]]:
        """row_key -> {revision, payload} of one table, folded from the event log in order."""
        rows: dict[str, dict[str, Any]] = {}
        for row in conn.execute(
            "SELECT event_json FROM events WHERE hub_project_id=? ORDER BY hub_seq", (hub_project_id,),
        ):
            event = json.loads(row["event_json"])
            if event.get("table_name") != table:
                continue
            key = str(event.get("row_key") or "")
            if event.get("op") == "delete":
                rows.pop(key, None)
                continue
            if event.get("new_revision") is None:
                continue
            try:
                payload = json.loads(event.get("payload_json") or "{}")
            except ValueError:
                payload = {}
            rows[key] = {"revision": int(event["new_revision"]), "payload": payload}
        return rows

    def projects(self) -> list[dict[str, Any]]:
        names = {u["userId"]: u["displayName"] for u in self.users()}
        out = []
        with self._connect() as conn:
            for project in conn.execute("SELECT * FROM projects ORDER BY book_id").fetchall():
                hub_id = project["hub_project_id"]
                progress = conn.execute("SELECT * FROM progress WHERE hub_project_id=?", (hub_id,)).fetchone()
                snapshot = json.loads(progress["snapshot_json"]) if progress is not None else {}
                last = conn.execute(
                    "SELECT MAX(received_at) AS at, COUNT(*) AS n FROM events WHERE hub_project_id=?", (hub_id,),
                ).fetchone()
                assignments = []
                for item in self._assignment_rows(conn, hub_id).values():
                    payload = item["payload"]
                    assignee = str(payload.get("assigneeId") or "")
                    assignments.append({
                        "chapter": str(payload.get("chapter") or ""), "assigneeId": assignee,
                        "assigneeName": names.get(assignee) or str(payload.get("assigneeName") or ""),
                        "assignedBy": str(payload.get("assignedBy") or ""),
                        "assignedAt": str(payload.get("assignedAt") or ""),
                    })
                assignments.sort(key=lambda a: (a["chapter"] != "", a["chapter"].zfill(4)))
                out.append({
                    "hubProjectId": hub_id, "bookId": project["book_id"],
                    "bookName": str(snapshot.get("bookName") or project["book_id"].upper()),
                    "projectName": str(snapshot.get("projectName") or ""),
                    "chapters": list(snapshot.get("chapters") or []),
                    "totals": dict(snapshot.get("totals") or {}),
                    "progressPostedAt": progress["posted_at"] if progress is not None else None,
                    "lastActivityAt": last["at"], "events": int(last["n"]),
                    "assignments": assignments,
                })
        return out

    def author_assignment(self, hub_project_id: str, chapter: str, assignee: dict[str, Any] | None,
                          admin: dict[str, Any]) -> dict[str, Any]:
        """A dashboard assignment is an ordinary `team_assignments` event the
        hub writes on the admin's behalf; devices apply it through their own
        revision check, like any pulled event. `assignee` None clears."""
        from tc_ai_bridge.workbench_repository import natural_row_id

        with self._connect() as conn:
            project = conn.execute("SELECT * FROM projects WHERE hub_project_id=?", (hub_project_id,)).fetchone()
            if project is None:
                raise HTTPException(404, "That project is not linked on this hub.")
            progress = conn.execute("SELECT snapshot_json FROM progress WHERE hub_project_id=?", (hub_project_id,)).fetchone()
            chapters = list(json.loads(progress["snapshot_json"]).get("chapters") or []) if progress else []
            chapter_key = str(chapter or "")
            if chapter_key and chapters and chapter_key not in chapters:
                raise HTTPException(400, f"Chapter {chapter_key} does not exist in this book.")
            book_id = project["book_id"]
            row_key = natural_row_id(hub_project_id, book_id, "assignment", chapter_key or "book")
            current = self._assignment_rows(conn, hub_project_id).get(row_key)
            now = _now()
            event: dict[str, Any] = {
                "event_id": str(uuid.uuid4()), "project_id": hub_project_id, "book_id": book_id,
                "table_name": "team_assignments", "row_key": row_key,
                "actor_id": admin["userId"], "device_id": "hub", "created_at": now, "journal_tx_id": None,
            }
            if assignee is None:
                if current is None:
                    return {"changed": False}
                event.update(op="delete", base_revision=current["revision"], new_revision=None,
                             payload_json=json.dumps(current["payload"], ensure_ascii=False), columns_json=None)
            else:
                payload = {"chapter": chapter_key, "assigneeId": assignee["userId"], "assignedBy": admin["userId"],
                           "assignedAt": now, "assigneeName": assignee["displayName"]}
                base = current["revision"] if current is not None else None
                event.update(
                    op="upsert", base_revision=base, new_revision=(base or 0) + 1,
                    payload_json=json.dumps(payload, ensure_ascii=False),
                    columns_json=json.dumps({"chapter": chapter_key, "assignee_id": assignee["userId"],
                                             "assigned_by": admin["userId"], "assigned_at": now}),
                )
            conn.execute(
                "INSERT INTO events(event_id, hub_project_id, pushed_by, received_at, event_json) VALUES(?,?,?,?,?)",
                (event["event_id"], hub_project_id, admin["userId"], now, json.dumps(event, ensure_ascii=False)),
            )
            conn.commit()
        return {"changed": True, "eventId": event["event_id"]}

    def author_team_role(self, hub_project_id: str, user: dict[str, Any], role: str | None,
                         admin: dict[str, Any]) -> dict[str, Any]:
        """#279: a user's role on one project, as a `team_members` event the hub
        writes on the admin's behalf, exactly as author_assignment does. None
        returns the user to their token role."""
        from tc_ai_bridge.workbench_repository import natural_row_id

        with self._connect() as conn:
            project = conn.execute("SELECT * FROM projects WHERE hub_project_id=?", (hub_project_id,)).fetchone()
            if project is None:
                raise HTTPException(404, "That project is not linked on this hub.")
            book_id = project["book_id"]
            row_key = natural_row_id(hub_project_id, book_id, "team_member", user["userId"])
            current = self._folded_rows(conn, hub_project_id, "team_members").get(row_key)
            now = _now()
            event: dict[str, Any] = {
                "event_id": str(uuid.uuid4()), "project_id": hub_project_id, "book_id": book_id,
                "table_name": "team_members", "row_key": row_key,
                "actor_id": admin["userId"], "device_id": "hub", "created_at": now, "journal_tx_id": None,
            }
            if role is None:
                if current is None:
                    return {"changed": False}
                event.update(op="delete", base_revision=current["revision"], new_revision=None,
                             payload_json=json.dumps(current["payload"], ensure_ascii=False), columns_json=None)
            else:
                if current is not None and current["payload"].get("role") == role:
                    return {"changed": False}
                base = current["revision"] if current is not None else None
                event.update(
                    op="upsert", base_revision=base, new_revision=(base or 0) + 1,
                    payload_json=json.dumps({"userId": user["userId"], "role": role, "setBy": admin["userId"],
                                             "setAt": now}, ensure_ascii=False),
                    columns_json=json.dumps({"user_id": user["userId"], "role": role}),
                )
            conn.execute(
                "INSERT INTO events(event_id, hub_project_id, pushed_by, received_at, event_json) VALUES(?,?,?,?,?)",
                (event["event_id"], hub_project_id, admin["userId"], now, json.dumps(event, ensure_ascii=False)),
            )
            conn.commit()
        return {"changed": True, "eventId": event["event_id"]}

    def project_exists(self, hub_project_id: str) -> bool:
        with self._connect() as conn:
            return conn.execute("SELECT 1 FROM projects WHERE hub_project_id=?", (hub_project_id,)).fetchone() is not None

    # -- events ------------------------------------------------------------------

    def push(self, hub_project_id: str, events: list[dict[str, Any]], pushed_by: str) -> dict[str, Any]:
        accepted = duplicates = 0
        received = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for event in events:
                if not isinstance(event, dict) or not event.get("event_id"):
                    raise HTTPException(400, "Every event needs an event_id.")
                if event.get("table_name") not in SYNCED_TABLES:
                    raise HTTPException(400, f"Table {event.get('table_name')!r} does not travel through the hub.")
                if str(event.get("project_id") or "") != hub_project_id:
                    raise HTTPException(400, "An event belongs to a different project than the push names.")
                cur = conn.execute(
                    "INSERT OR IGNORE INTO events(event_id, hub_project_id, pushed_by, received_at, event_json) "
                    "VALUES(?,?,?,?,?)",
                    (str(event["event_id"]), hub_project_id, pushed_by, received, json.dumps(event, ensure_ascii=False)),
                )
                if cur.rowcount:
                    accepted += 1
                else:
                    duplicates += 1
            conn.commit()
        return {"accepted": accepted, "duplicates": duplicates}

    def pull(self, hub_project_id: str, after: int) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT hub_seq, event_json FROM events WHERE hub_project_id=? AND hub_seq>? ORDER BY hub_seq LIMIT ?",
                (hub_project_id, int(after), PULL_PAGE + 1),
            ).fetchall()
        more = len(rows) > PULL_PAGE
        rows = rows[:PULL_PAGE]
        return {"events": [{"hubSeq": int(r["hub_seq"]), "event": json.loads(r["event_json"])} for r in rows],
                "more": more}


def _token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else ""


def create_app(engine: BridgeEngine, store: HubStore | None = None,
               dashboard_dir: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="Bridge hub", docs_url=None, redoc_url=None, openapi_url=None)
    lock = threading.Lock()
    hub = store

    def device_for(request: Request) -> dict[str, Any]:
        if hub is None:
            raise HTTPException(503, "This server has no hub store.")
        device = hub.device(_token(request))
        if device is None:
            raise HTTPException(401, "Join this hub first: the device token is missing or unknown.")
        return device

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok"}

    @app.post("/rpc")
    async def rpc(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            engine_request = EngineRequest.from_dict(body)
        except Exception as exc:  # noqa: BLE001 -- a bad body is the client's error
            return JSONResponse(EngineResponse.fail("__unknown__", "bad_request", str(exc)).to_dict())
        user = device_for(request) if hub is not None else None
        with lock:
            try:
                response = engine.handle_request_as(engine_request, user)
            except Exception as exc:  # noqa: BLE001 -- same defence as the stdio loop
                response = EngineResponse.fail(engine_request.id, "internal_error", str(exc))
        return JSONResponse(response.to_dict())

    @app.post("/hub/join")
    async def join(request: Request) -> dict[str, Any]:
        if hub is None:
            raise HTTPException(503, "This server has no hub store.")
        body = await request.json()
        return hub.join(str(body.get("joinCode") or ""), str(body.get("displayName") or ""),
                        str(body.get("deviceId") or ""), str(body.get("userId") or ""))

    # -- the dashboard's reads and writes (#81) --------------------------------

    def require_admin(device: dict[str, Any], what: str) -> None:
        if parse_role(device["role"]) is not Role.PROJECT_ADMIN:
            raise HTTPException(403, f"{device['displayName']} is not a project admin and cannot {what}.")

    @app.get("/hub/me")
    def me(request: Request) -> dict[str, Any]:
        device = device_for(request)
        return {"userId": device["userId"], "displayName": device["displayName"], "role": device["role"]}

    class _HubProject:
        """#279: one linked project as authorize() sees it, its per-project
        roles folded from the hub's event log, so the dashboard's checks are
        the same rule as every RPC's."""

        def __init__(self, hub_project_id: str) -> None:
            self.hub_project_id = hub_project_id

        def team_role(self, user_id: str) -> str | None:
            return hub.team_roles(self.hub_project_id).get(user_id)  # type: ignore[union-attr]

    def project_role(device: dict[str, Any], hub_project_id: str) -> Role:
        return effective_role(device, _HubProject(hub_project_id), Action.MANAGE_PROJECTS)

    @app.get("/hub/projects")
    def projects(request: Request) -> dict[str, Any]:
        device = device_for(request)
        listed = hub.projects()  # type: ignore[union-attr]
        for project in listed:
            hub_id = str(project.get("hubProjectId") or "")
            project["myRole"] = project_role(device, hub_id).value
            project["roles"] = hub.team_roles(hub_id)  # type: ignore[union-attr]
        return {"projects": listed}

    @app.post("/hub/team-roles")
    async def set_team_role(request: Request) -> dict[str, Any]:
        """#279: a user's role on one project. Managing users stays with the
        token role, as on the desktop."""
        device = device_for(request)
        require_admin(device, "change someone's role on a project")
        body = await request.json()
        user = next((u for u in hub.users() if u["userId"] == str(body.get("userId") or "")), None)  # type: ignore[union-attr]
        if user is None:
            raise HTTPException(400, "Give a role to someone who has joined this hub.")
        role = body.get("role")
        if role is not None:
            try:
                role = Role(str(role)).value
            except ValueError:
                raise HTTPException(400, f"Unknown role: {role}") from None
        return hub.author_team_role(str(body.get("hubProjectId") or ""), user, role, device)  # type: ignore[union-attr]

    @app.post("/hub/progress")
    async def progress(request: Request) -> dict[str, Any]:
        device = device_for(request)
        body = await request.json()
        hub_project_id = str(body.get("hubProjectId") or "")
        if not hub.project_exists(hub_project_id):  # type: ignore[union-attr]
            raise HTTPException(404, "Link the project to this hub first.")
        snapshot = {key: body.get(key) for key in ("bookId", "bookName", "projectName", "chapters", "totals")}
        hub.post_progress(hub_project_id, snapshot, device["userId"])  # type: ignore[union-attr]
        return {"ok": True}

    @app.get("/hub/users")
    def users(request: Request) -> dict[str, Any]:
        device = device_for(request)
        # #279: a project admin on any project needs the list to assign work there.
        if not any(project_role(device, str(p.get("hubProjectId") or "")) is Role.PROJECT_ADMIN
                   for p in hub.projects()):  # type: ignore[union-attr]
            require_admin(device, "see the team's users")
        return {"users": hub.users()}  # type: ignore[union-attr]

    @app.post("/hub/assignments")
    async def assign(request: Request) -> dict[str, Any]:
        device = device_for(request)
        body = await request.json()
        # #279: assigning is managing the project, decided by the role on it.
        try:
            authorize(device, _HubProject(str(body.get("hubProjectId") or "")), Action.MANAGE_PROJECTS)
        except AuthorizationError as exc:
            raise HTTPException(403, str(exc)) from None
        assignee_id = str(body.get("userId") or "")
        assignee = None
        if assignee_id:
            assignee = next((u for u in hub.users() if u["userId"] == assignee_id), None)  # type: ignore[union-attr]
            if assignee is None:
                raise HTTPException(400, "Assign to someone who has joined this hub.")
        return hub.author_assignment(str(body.get("hubProjectId") or ""), str(body.get("chapter") or ""),  # type: ignore[union-attr]
                                     assignee, device)

    @app.post("/hub/join-codes")
    async def new_join_code(request: Request) -> dict[str, Any]:
        device = device_for(request)
        require_admin(device, "invite")
        body = await request.json()
        role = parse_role(body.get("role"), default=Role.EDITOR)
        return {"joinCode": hub.create_join_code(role.value, device["userId"]), "role": role.value}  # type: ignore[union-attr]

    @app.get("/hub/presence")
    def presence(request: Request) -> dict[str, Any]:
        device_for(request)
        return {"devices": hub.presence()}  # type: ignore[union-attr]

    @app.post("/hub/projects/link")
    async def link(request: Request) -> dict[str, Any]:
        device = device_for(request)
        body = await request.json()
        return hub.link(str(body.get("bookId") or ""), str(body.get("sourceSha256") or ""),  # type: ignore[union-attr]
                        str(body.get("localProjectId") or ""), device["userId"])

    @app.post("/sync/push")
    async def push(request: Request) -> dict[str, Any]:
        device = device_for(request)
        body = await request.json()
        hub_project_id = str(body.get("hubProjectId") or "")
        # A reporter, by token or on this project (#279), pushes nothing.
        try:
            authorize(device, _HubProject(hub_project_id), Action.WRITE)
        except AuthorizationError as exc:
            raise HTTPException(403, str(exc)) from None
        if not hub.project_exists(hub_project_id):  # type: ignore[union-attr]
            raise HTTPException(404, "Link the project to this hub before pushing.")
        events = body.get("events") if isinstance(body.get("events"), list) else []
        return hub.push(hub_project_id, events, device["userId"])  # type: ignore[union-attr]

    @app.get("/sync/pull")
    def pull(request: Request, hubProjectId: str, after: int = 0) -> dict[str, Any]:  # noqa: N803 -- the wire name
        device_for(request)
        if not hub.project_exists(hubProjectId):  # type: ignore[union-attr]
            raise HTTPException(404, "That project is not linked on this hub.")
        return hub.pull(hubProjectId, after)  # type: ignore[union-attr]

    if dashboard_dir is not None and (Path(dashboard_dir) / "index.html").is_file():
        from fastapi.staticfiles import StaticFiles

        # Mounted last, at "/", so every API route above wins (#81).
        app.mount("/", StaticFiles(directory=str(dashboard_dir), html=True), name="dashboard")

    return app


def default_dashboard_dir() -> Path:
    """The dashboard bundle `npm run build:dashboard` writes, beside the engine
    in a source checkout."""
    return Path(__file__).resolve().parent.parent / "dist-dashboard"


def build_engine(data_dir: str | Path = "") -> BridgeEngine:
    """An engine whose settings, workspace and managed projects live under
    `data_dir` (the hub's own folder), or the desktop default when empty."""
    if data_dir:
        root = Path(data_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return BridgeEngine(settings=AppSettings(path=root / "settings.json"))
    return BridgeEngine()


def build_store(data_dir: str | Path) -> HubStore:
    """The hub store, and on a first start one admin join code written beside
    it for the first administrator."""
    root = Path(data_dir).resolve()
    store = HubStore(root / "hub.sqlite3")
    marker = root / "admin-join-code.txt"
    if not marker.exists() and not store.presence():
        code = store.create_join_code(Role.PROJECT_ADMIN.value, "hub")
        marker.write_text(
            f"{code}\nJoin with this code to become the hub's first project admin. Delete this file afterwards.\n",
            encoding="utf-8",
        )
    return store


def serve(data_dir: str = "", host: str = "127.0.0.1", port: int = 8765, parent_pid: int | None = None) -> None:
    import uvicorn

    if parent_pid:
        # Started by the desktop engine (#46): never outlive it.
        from tc_ai_bridge.process_watch import watch_parent

        watch_parent(parent_pid, lambda: os._exit(0))
    root = Path(data_dir or Path.cwd() / "bridge-hub").resolve()
    app = create_app(build_engine(root), build_store(root), dashboard_dir=default_dashboard_dir())
    print(f"Bridge hub on http://{host}:{port} -- data in {root}", flush=True)
    uvicorn.run(app, host=host, port=int(port), log_level="warning")
