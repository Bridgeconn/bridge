"""The device side of the team hub's first slice (#80).

What travels, decided in the #227 review (DECISIONS 2026-10-15): the twelve
human-owned workbench tables in `SYNCED_TABLES`. The other `MUTABLE_TABLES`
entries are derived or device-local (`NOT_SYNCED_TABLES`) and are rebuilt by
each device; a test pins the two against `MUTABLE_TABLES` so a new table is
classified on purpose. Scripture text and `.apps/translationCore/**` never
travel: no synced table holds verse text.

One pass (`sync_project`) pushes this device's unsynced events for the
synced tables and acknowledges the rest locally (they never travel), then
pulls everything after its cursor and applies it through
`WorkbenchRepository.import_event_lines`, the same revision check every
local write uses. An event whose base is not the local row is a conflict:
it is kept in `sync_conflicts` verbatim and the local row is left alone.
A human decision is never overwritten automatically.

The client is plain urllib with a short timeout. It runs only when a hub is
configured, on the engine's sync thread or on an explicit setup click, never
on a path a translator waits for (the offline invariant; the hub is its one
agreed exception, DECISIONS 2026-10-12).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

from .workbench_repository import MUTABLE_TABLES, WorkbenchRepository

SYNCED_TABLES: tuple[str, ...] = (
    "human_decisions",
    "issue_resolutions",
    "alignment_cross_verse_links",
    "alignment_null_decisions",
    "alignment_history",
    "team_assignments",
    "team_members",
    "language_qa_batches",
    "language_qa_flags",
    "language_qa_learned_fixes",
    "project_state",
    "ai_review_results",
)

NOT_SYNCED_TABLES: tuple[str, ...] = tuple(t for t in MUTABLE_TABLES if t not in SYNCED_TABLES)

PUSH_BATCH = 500
HTTP_TIMEOUT_SECONDS = 10.0


class HubError(RuntimeError):
    """The hub refused, or could not be reached. The message is for the screen."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


Transport = Callable[[str, str, dict[str, str], bytes | None, float], tuple[int, bytes]]


def _urllib_transport(method: str, url: str, headers: dict[str, str], body: bytes | None,
                      timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 -- the admin's own hub URL
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()


class HubClient:
    """JSON over HTTP to one hub. `transport` is injectable so tests drive an
    in-process hub (FastAPI's test client) without a socket."""

    def __init__(self, base_url: str, token: str = "", *, transport: Transport | None = None,
                 timeout: float = HTTP_TIMEOUT_SECONDS) -> None:
        self.base_url = str(base_url or "").rstrip("/")
        if not self.base_url.startswith(("http://", "https://")):
            raise HubError("The hub address must start with http:// or https://.")
        self.token = token
        self._transport = transport or _urllib_transport
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        try:
            status, raw = self._transport(method, self.base_url + path, headers, body, self.timeout)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise HubError(f"The hub at {self.base_url} could not be reached ({exc}).") from exc
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            data = {}
        if status >= 400:
            message = data.get("detail") if isinstance(data, dict) else None
            raise HubError(str(message or f"The hub answered {status}."))
        return data if isinstance(data, dict) else {}

    def join(self, join_code: str, display_name: str, device_id: str, *, user_id: str = "") -> dict[str, Any]:
        return self._request("POST", "/hub/join", {
            "joinCode": join_code, "displayName": display_name, "deviceId": device_id, "userId": user_id,
        })

    def post_progress(self, hub_project_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/hub/progress", {"hubProjectId": hub_project_id, **snapshot})

    def link(self, book_id: str, source_sha256: str, local_project_id: str) -> dict[str, Any]:
        return self._request("POST", "/hub/projects/link", {
            "bookId": book_id, "sourceSha256": source_sha256, "localProjectId": local_project_id,
        })

    def push(self, hub_project_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        return self._request("POST", "/sync/push", {"hubProjectId": hub_project_id, "events": events})

    def pull(self, hub_project_id: str, after: int) -> dict[str, Any]:
        return self._request("GET", f"/sync/pull?hubProjectId={hub_project_id}&after={int(after)}")


def sync_project(workbench: WorkbenchRepository, client: HubClient, hub_project_id: str) -> dict[str, Any]:
    """One push then one pull for one linked book. Returns what happened;
    raises HubError when the hub cannot be reached or refuses, after
    recording the error on the book's sync state."""
    try:
        pushed, acknowledged = _push(workbench, client, hub_project_id)
        workbench.update_sync_state(hub_project_id, last_push_at=_now())
        pulled = _pull(workbench, client, hub_project_id)
    except HubError as exc:
        workbench.update_sync_state(hub_project_id, last_error=str(exc))
        raise
    workbench.update_sync_state(hub_project_id, last_pull_at=_now(), clear_error=True)
    return {"pushed": pushed, "acknowledgedLocally": acknowledged, **pulled}


def _push(workbench: WorkbenchRepository, client: HubClient, hub_project_id: str) -> tuple[int, int]:
    pushed = 0
    local_only = 0
    while True:
        events = workbench.unsynced(project_id=hub_project_id, limit=PUSH_BATCH)
        if not events:
            return pushed, local_only
        travelling = [e for e in events if e["table_name"] in SYNCED_TABLES]
        staying = [str(e["event_id"]) for e in events if e["table_name"] not in SYNCED_TABLES]
        if travelling:
            client.push(hub_project_id, travelling)
            workbench.mark_synced([str(e["event_id"]) for e in travelling])
            pushed += len(travelling)
        if staying:
            # Derived and device-local events never travel; acknowledging them
            # keeps the unsynced cursor from growing without bound.
            workbench.mark_synced(staying)
            local_only += len(staying)


def _pull(workbench: WorkbenchRepository, client: HubClient, hub_project_id: str) -> dict[str, Any]:
    cursor = workbench.sync_state(hub_project_id)["pullCursor"]
    applied = duplicates = malformed = 0
    conflicts_added = 0
    while True:
        page = client.pull(hub_project_id, cursor)
        events = [e for e in page.get("events") or [] if isinstance(e, dict)]
        if not events:
            break
        lines = []
        by_id: dict[str, str] = {}
        for item in events:
            event = item.get("event") if isinstance(item.get("event"), dict) else {}
            if event.get("table_name") not in SYNCED_TABLES:
                continue  # a hub never sends these; refuse them if one did
            line = json.dumps(event, ensure_ascii=False)
            lines.append(line)
            by_id[str(event.get("event_id") or "")] = line
        result = workbench.import_event_lines(lines)
        applied += result["applied"]
        duplicates += result["duplicates"]
        malformed += result["malformed"]
        conflicts_added += workbench.record_sync_conflicts(hub_project_id, result["conflicts"], by_id)
        cursor = max(int(item.get("hubSeq") or 0) for item in events)
        workbench.update_sync_state(hub_project_id, pull_cursor=cursor)
        if not page.get("more"):
            break
    return {"applied": applied, "duplicates": duplicates, "malformed": malformed,
            "conflicts": conflicts_added, "pullCursor": cursor}
