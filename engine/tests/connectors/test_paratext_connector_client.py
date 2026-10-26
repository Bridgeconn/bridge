"""Connector 0.8.0 (#358): the Python client's wire shapes for the plugin's
project list, note creation by project id, and the thread calls (list, reply,
resolve), and what the plugin source promises. No Paratext runs here: the
pipe exchange is replaced, and the C# is read as text."""

from __future__ import annotations

import re

from tc_ai_bridge import paratext_install
from tc_ai_bridge.paratext_connector import ConnectorState, ParatextConnectorClient
from tests.support.paths import REPO_ROOT

PLUGIN = REPO_ROOT / "paratext_plugin" / "AiBridgeConnectorPlugin.cs"
PROTOCOL = REPO_ROOT / "paratext_plugin" / "BridgeProtocol.cs"


class Recording(ParatextConnectorClient):
    """The client with the pipe replaced: each call records (action, payload)."""

    def __init__(self):
        super().__init__()
        self.calls: list[tuple[str, dict]] = []

    def _exchange(self, action, payload=None):
        self.calls.append((action, dict(payload or {})))
        return {"ok": True, "author": "Yesu Selva Benz", "created": "2026-10-26T10:00:00.1234567+05:30",
                "anchor": {"verse_ref": "TIT 1:1", "offset": 0, "selected_text": ""}}


def test_state_carries_the_project_list_and_finds_one_by_id_case_insensitively():
    state = ConnectorState.from_response({
        "ok": True, "project_id": "AAA", "project_name": "DVT", "capabilities": ["state", "list_notes"],
        "projects": [{"id": "AAA", "short_name": "DVT", "editable": True},
                     {"id": "c2d042a9-linked", "short_name": "IRVTam", "editable": True}, "junk"],
    })
    assert [p["short_name"] for p in state.projects] == ["DVT", "IRVTam"]
    assert state.project_named("C2D042A9-LINKED")["short_name"] == "IRVTam"
    assert state.project_named("missing") is None
    # An older companion sends no list: an empty one, not a crash.
    assert ConnectorState.from_response({"ok": True}).projects == []


def test_create_note_is_addressed_by_project_id_and_writes_the_body_as_given():
    client = Recording()
    answer = client.create_note("TIT 1:1", "", "Please look at this.\n\n[Bridge ref bridge-r1-abc]",
                                project_id="c2d042a9-linked", message_id="bridge-r1-abc")
    [(action, payload)] = client.calls
    assert action == "create_note"
    assert payload["project_id"] == "c2d042a9-linked"
    assert payload["comment"].endswith("[Bridge ref bridge-r1-abc]")
    # No "[AI Suggestion]" prefix is asked for any more (decision 1 on #358).
    assert payload["external_author"] == ""
    assert answer["author"] == "Yesu Selva Benz" and answer["created"].endswith("+05:30")


def test_thread_calls_name_the_project_the_chapter_and_the_key():
    client = Recording()
    key = {"verse_ref": "TIT 1:1", "offset": 0, "selected_text": "",
           "first_author": "Yesu Selva Benz", "first_created": "2026-10-26T10:00:00.1234567+05:30"}
    client.list_notes("c2d042a9-linked", "TIT", 1, unresolved_only=True)
    client.add_comment("c2d042a9-linked", "TIT", "1", key, "Done in Bridge.\n\n[Bridge ref bridge-r1-def]")
    client.resolve_note("c2d042a9-linked", "TIT", "1", key)
    actions = [action for action, _ in client.calls]
    assert actions == ["list_notes", "add_comment", "resolve_note"]
    listed, added, resolved = (payload for _, payload in client.calls)
    assert listed == {"project_id": "c2d042a9-linked", "book": "TIT", "chapter": "1", "unresolved_only": True}
    assert added["key"] == key and added["text"].endswith("[Bridge ref bridge-r1-def]") and added["assignee"] == ""
    assert resolved == {"project_id": "c2d042a9-linked", "book": "TIT", "chapter": "1", "key": key}


def test_the_bundled_plugin_is_0_8_0_and_serves_the_six_actions_without_any_scripture_write():
    assert paratext_install.bundled_version() == "0.8.0"
    source = PLUGIN.read_text(encoding="utf-8")
    for action in ("get_state", "set_reference", "create_note", "list_notes", "add_comment", "resolve_note"):
        assert f'action == "{action}"' in source, action
    # The write boundary: Project Notes only, through the write lock; no Scripture write, no delete.
    assert "WriteLockScope.ProjectNotes" in source
    assert not re.search(r"\.(PutUSFM|PutUSX|PutUSFMTokens|DeleteNote|Delete)\(", source)
    # A note is addressed by project id; the active window never decides the destination.
    assert "GetAllProjects()" in source
    assert 'project_id is required' in source
    # The answer carries the note's only identity.
    protocol = PROTOCOL.read_text(encoding="utf-8")
    for field in ("projects", "author", "created", "anchor", "notes", "comment_added", "resolved"):
        assert f" {field} {{ get; set; }}" in protocol, field
