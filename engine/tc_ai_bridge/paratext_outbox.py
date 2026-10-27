"""Paratext write-back: this device's outbox and the team's thread links (#358).

Bridge writes Paratext Project Notes only through the companion plugin
(connector 0.8.0), never into a ``Notes_*.xml`` file. Each write is a row in
``paratext_outbox`` (workbench v11, device-local, never synced) before it is
attempted, so a write that cannot be made now -- Paratext closed, the linked
project not on this PC, an older connector -- waits and is retried, and a
crash between "sent" and "recorded" cannot make it twice:

* every Bridge note or comment ends with ``[Bridge ref <message_id>]``, and
  before any send the linked project's notes index (#357) is searched for that
  footer; a hit means the write already happened (here or on another device)
  and the row is marked sent from what the file holds, without a send;
* a send is attempted only while that index matches the notes files on disk
  ("ready"), so a footer cannot be missed because the index is behind.

``paratext_links`` (synced, human-owned) records that a Bridge record and a
Paratext thread point at each other. A thread created from Bridge gets its
link once the index shows the thread (the plugin's answer carries no thread
id; Paratext notes have none in the plugin API).

What Paratext says back -- a reply, a ``done`` -- is read from the index and
shown; nothing here ever applies it to a Bridge record (decision 3 on #358).
Scripture is never written by any path in this module.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from .paratext_connector import ConnectorState, ParatextConnectorError
from .usfm_verse import lift_verse
from .workbench_repository import WorkbenchIdentity, WorkbenchRepository, natural_row_id

OUTBOX = "paratext_outbox"
LINKS = "paratext_links"

OP_CREATE = "create_thread"
OP_COMMENT = "add_comment"
OP_RESOLVE = "resolve"
OPS = (OP_CREATE, OP_COMMENT, OP_RESOLVE)

QUEUED = "queued"
SENT = "sent"

KINDS = ("issue_resolution", "finding", "correction_proposal")
TO_PARATEXT = "bridge_to_paratext"
FROM_PARATEXT = "paratext_to_bridge"

# The plugin calls each op needs; 0.7.4 has none of them.
_NEEDS = {OP_CREATE: "create_note", OP_COMMENT: "add_comment", OP_RESOLVE: "resolve_note"}

WAITING_FOR_INDEX = "Waiting for Bridge to read the Paratext notes files before sending (so nothing is sent twice)."
NOT_LINKED = ("This book is not linked to a Paratext project, so Bridge cannot tell which project "
              "the note belongs to; it stays queued.")


def footer(message_id: str) -> str:
    return f"[Bridge ref {message_id}]"


def with_footer(text: str, message_id: str) -> str:
    return f"{str(text or '').rstrip()}\n\n{footer(message_id)}"


def selection_context(raw_verse: str, selected_text: str) -> tuple[str, str]:
    """The word before and the word after `selected_text` in the verse's plain
    text (notes removed), for the plugin to tell one Paratext match from
    another: a word repeated in its own footnote is two matches there and the
    note was refused for ever (#358 h). ("", "") unless the selection occurs
    exactly once here -- a repeat in the verse itself is the reviewer's to
    choose in Paratext, never Bridge's guess."""
    if not selected_text:
        return "", ""
    plain = lift_verse(raw_verse or "").plain
    if plain.count(selected_text) != 1:
        return "", ""
    start = plain.index(selected_text)
    return (_edge_word(plain[:start].split(), reverse=True),
            _edge_word(plain[start + len(selected_text):].split(), reverse=False))


def _edge_word(tokens: list[str], *, reverse: bool) -> str:
    """The tokens nearest the selection up to and including the first with a
    letter or digit, so bare punctuation is never the whole context."""
    taken: list[str] = []
    for token in reversed(tokens) if reverse else tokens:
        taken.append(token)
        if any(ch.isalnum() for ch in token):
            break
    return " ".join(reversed(taken) if reverse else taken)


def new_message_id(prefix: str = "bridge") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OutboxError(ValueError):
    """A request the outbox cannot accept (unknown op or kind, empty text)."""


class ParatextOutbox:
    """The outbox and link rows of one book, written as ``identity``."""

    def __init__(self, workbench: WorkbenchRepository, identity: WorkbenchIdentity, book_id: str):
        self.workbench = workbench
        self.identity = identity
        self.book_id = book_id

    # -- rows -----------------------------------------------------------------

    def _write(self, table: str, row_id: str, payload: dict[str, Any], columns: dict[str, Any]) -> None:
        self.workbench._write(
            table, row_id, project_id=self.identity.project_id, book_id=self.book_id, payload=payload,
            actor_id=self.identity.actor_id, device_id=self.identity.device_id,
            expected_revision=None, extra_columns=columns,
        )

    @staticmethod
    def _item(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        payload = json.loads(row.get("payload_json") or "{}")
        return {
            "messageId": row["id"], "op": row.get("op") or "", "threadId": row.get("thread_id") or "",
            "status": row.get("status") or QUEUED, "attempts": int(row.get("attempts") or 0),
            "lastError": row.get("last_error") or "", "sentAt": row.get("sent_at") or "",
            "resultKey": row.get("result_key") or "", "createdAt": row.get("created_at") or "",
            **{k: v for k, v in payload.items() if k not in {"messageId", "op", "status"}},
        }

    def get(self, message_id: str) -> dict[str, Any] | None:
        return self._item(self.workbench.get(OUTBOX, message_id))

    def items(self, status: str | None = None) -> list[dict[str, Any]]:
        equals = {"status": status} if status else None
        rows = self.workbench.rows(OUTBOX, project_id=self.identity.project_id, book_id=self.book_id, equals=equals)
        return [item for item in (self._item(row) for row in rows) if item is not None]

    def enqueue(self, op: str, *, message_id: str, kind: str, local_id: str, text: str = "",
                reference: str = "", selected_text: str = "", before_context: str = "",
                after_context: str = "", thread_id: str = "",
                key: dict[str, Any] | None = None, book: str = "", chapter: str = "",
                record: dict[str, Any] | None = None) -> dict[str, Any]:
        """Put one write in the queue. A message id already sent is returned as
        it is (the same message is never queued twice); one still queued has
        its content refreshed, keeping its attempts."""
        if op not in OPS:
            raise OutboxError(f"op must be one of {list(OPS)}")
        if kind not in KINDS:
            raise OutboxError(f"kind must be one of {list(KINDS)}")
        if op != OP_RESOLVE and not str(text or "").strip():
            raise OutboxError("The note text is empty.")
        if op != OP_CREATE and not thread_id:
            raise OutboxError("A reply or resolve names the Paratext thread it goes to.")
        existing = self.get(message_id)
        if existing is not None and existing["status"] == SENT:
            return existing
        payload = {
            "kind": kind, "localId": local_id, "book": book.upper(), "chapter": str(chapter),
            "reference": reference, "selectedText": selected_text,
            "beforeContext": before_context, "afterContext": after_context,
            "text": with_footer(text, message_id) if op != OP_RESOLVE else "",
            "key": dict(key or {}), "record": dict(record or {}),
        }
        self._write(OUTBOX, message_id, payload, {
            "op": op, "thread_id": thread_id or None, "status": QUEUED,
            "attempts": existing["attempts"] if existing else 0,
            "last_error": existing["lastError"] if existing else None,
        })
        return self.get(message_id)  # type: ignore[return-value]

    def _mark(self, item: dict[str, Any], **changes: Any) -> dict[str, Any]:
        merged = {**item, **changes}
        payload = {k: merged.get(k) for k in ("kind", "localId", "book", "chapter", "reference", "selectedText",
                                              "beforeContext", "afterContext", "text", "key", "record", "anchor", "author", "created")
                   if merged.get(k) not in (None, "")}
        self._write(OUTBOX, item["messageId"], payload, {
            "op": merged["op"], "thread_id": merged.get("threadId") or None, "status": merged["status"],
            "attempts": int(merged.get("attempts") or 0), "last_error": merged.get("lastError") or None,
            "sent_at": merged.get("sentAt") or None, "result_key": merged.get("resultKey") or None,
        })
        return self.get(item["messageId"])  # type: ignore[return-value]

    # -- links ------------------------------------------------------------------

    def link(self, kind: str, local_id: str, thread_id: str, *, message_id: str = "",
             direction: str = TO_PARATEXT) -> dict[str, Any]:
        if kind not in KINDS:
            raise OutboxError(f"kind must be one of {list(KINDS)}")
        if not thread_id or not local_id:
            raise OutboxError("A link names a Bridge record and a Paratext thread.")
        row_id = natural_row_id(self.identity.project_id, self.book_id, kind, local_id, thread_id)
        existing = self.workbench.get(LINKS, row_id)
        if existing is None:
            self._write(LINKS, row_id, {"threadId": thread_id, "messageId": message_id, "direction": direction}, {
                "kind": kind, "local_id": local_id, "thread_id": thread_id,
                "message_id": message_id or None, "direction": direction,
            })
        return next(link for link in self.links_for(kind, local_id) if link["threadId"] == thread_id)

    def links_for(self, kind: str, local_id: str) -> list[dict[str, Any]]:
        rows = self.workbench.rows(LINKS, project_id=self.identity.project_id, book_id=self.book_id,
                                   equals={"kind": kind, "local_id": local_id})
        return [{"kind": r.get("kind"), "localId": r.get("local_id"), "threadId": r.get("thread_id"),
                 "messageId": r.get("message_id") or "", "direction": r.get("direction") or "",
                 "createdAt": r.get("created_at") or ""} for r in rows]

    def links(self) -> list[dict[str, Any]]:
        rows = self.workbench.rows(LINKS, project_id=self.identity.project_id, book_id=self.book_id)
        return [{"kind": r.get("kind"), "localId": r.get("local_id"), "threadId": r.get("thread_id"),
                 "messageId": r.get("message_id") or "", "direction": r.get("direction") or ""} for r in rows]

    # -- flush ------------------------------------------------------------------

    def flush(
        self,
        *,
        client_factory: Callable[[], Any],
        expected: dict[str, Any],
        find_ref: Callable[[str], dict[str, Any] | None],
        index_ready: Callable[[], bool],
        waiting_reason: Callable[[], str] | None = None,
        only: Iterable[str] | None = None,
        on_change: Callable[[dict[str, Any]], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Try every queued write (or those in ``only``), and fill in the thread
        of every sent one whose thread the index now shows. Returns the items
        touched. Never raises for Paratext being unavailable: that is a
        ``lastError`` on the item, which stays queued."""
        wanted = set(only) if only is not None else None
        touched: list[dict[str, Any]] = []

        def changed(item: dict[str, Any]) -> None:
            touched.append(item)
            if on_change is not None:
                on_change(item)

        for item in self.items(SENT):
            if wanted is not None and item["messageId"] not in wanted:
                continue
            if item["op"] == OP_CREATE and not item["threadId"]:
                found = find_ref(item["messageId"])
                if found:
                    item = self._mark(item, threadId=found["threadId"])
                    self.link(item["kind"], item["localId"], found["threadId"], message_id=item["messageId"])
                    changed(item)

        queued = [i for i in self.items(QUEUED) if wanted is None or i["messageId"] in wanted]
        if not queued:
            return touched
        expected_id = str((expected or {}).get("id") or "")
        state: ConnectorState | None = None
        state_error = ""
        for item in queued:
            attempts = item["attempts"] + 1
            if not expected_id:
                changed(self._mark(item, attempts=attempts, lastError=NOT_LINKED))
                continue
            if not index_ready():
                changed(self._mark(item, attempts=attempts,
                                   lastError=(waiting_reason() if waiting_reason else "") or WAITING_FOR_INDEX))
                continue
            if item["op"] != OP_RESOLVE:
                found = find_ref(item["messageId"])
                if found:
                    # Already in Paratext: sent earlier (a crash before the
                    # record was saved, or another device). Record it, send nothing.
                    item = self._mark(item, attempts=attempts, status=SENT, lastError="",
                                      sentAt=item.get("sentAt") or _now(),
                                      resultKey=f"{found.get('user', '')}|{found.get('date', '')}",
                                      threadId=item.get("threadId") or found["threadId"])
                    self.link(item["kind"], item["localId"], found["threadId"], message_id=item["messageId"])
                    changed(item)
                    continue
            try:
                if state is None and not state_error:
                    try:
                        state = client_factory().get_state()
                    except ParatextConnectorError as exc:
                        state_error = str(exc)
                if state_error:
                    raise ParatextConnectorError(state_error)
                assert state is not None
                need = _NEEDS[item["op"]]
                if need not in {c.strip().casefold() for c in state.capabilities}:
                    raise ParatextConnectorError(
                        f"The Paratext connector {state.plugin_version or 'installed'} cannot {item['op'].replace('_', ' ')}; "
                        "update it to 0.8.0 in Settings › Connections (Paratext closed).")
                project = state.project_named(expected_id)
                if project is None:
                    name = str(expected.get("name") or expected_id[:8])
                    raise ParatextConnectorError(
                        f"Paratext has no project {name} ({expected_id[:8]}…) on this computer; the note stays queued.")
                item = self._send(client_factory(), item, expected_id, attempts)
                changed(item)
            except ParatextConnectorError as exc:
                changed(self._mark(item, attempts=attempts, lastError=str(exc)))
        return touched

    def _send(self, client: Any, item: dict[str, Any], project_id: str, attempts: int) -> dict[str, Any]:
        if item["op"] == OP_CREATE:
            answer = client.create_note(
                item.get("reference", ""), item.get("selectedText", ""), item.get("text", ""),
                project_id=project_id, message_id=item["messageId"],
                before_context=item.get("beforeContext", ""), after_context=item.get("afterContext", ""),
            )
            result = self._mark(item, attempts=attempts, status=SENT, lastError="", sentAt=_now(),
                                resultKey=f"{answer.get('author', '')}|{answer.get('created', '')}",
                                author=answer.get("author", ""), created=answer.get("created", ""),
                                anchor=answer.get("anchor") or {})
            return result
        key = dict(item.get("key") or {})
        book, chapter = item.get("book", ""), item.get("chapter", "")
        if item["op"] == OP_COMMENT:
            answer = client.add_comment(project_id, book, chapter, key, item.get("text", ""))
        else:
            answer = client.resolve_note(project_id, book, chapter, key)
        sent = self._mark(item, attempts=attempts, status=SENT, lastError="", sentAt=_now(),
                          resultKey=f"{answer.get('author', '')}|{answer.get('created', '')}")
        self.link(item["kind"], item["localId"], item["threadId"], message_id=item["messageId"])
        return sent
