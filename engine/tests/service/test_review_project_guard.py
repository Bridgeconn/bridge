"""A stale detached queue must never act against the engine's new book."""
import json
import pytest

from bridge_service import BridgeEngine
from tests.support.projects import call, fixture_project, _write_minimal_book


@pytest.mark.parametrize("expected", ["", None, "C:/a-different-project"])
def test_invalid_review_project_precondition_refuses_before_dispatch(fixture_project, expected):
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(fixture_project)})["success"]
    before = (fixture_project / "rut" / "1.json").read_bytes()
    result = call(engine, "verse.edit", {
        "chapter": "1", "verse": "1", "newText": "must not be written",
        "_expectedProjectPath": expected,
    })
    assert result["error"]["code"] == "project_changed"
    assert (fixture_project / "rut" / "1.json").read_bytes() == before


def test_old_queue_cannot_write_after_switch_even_with_same_reference(fixture_project, tmp_path):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    other = tmp_path / "other"
    _write_minimal_book(other, "tit", "another book")
    call(engine, "project.open", {"path": str(other)})
    result = call(engine, "verse.edit", {
        "chapter": "1", "verse": "1", "newText": "old queue text",
        "_expectedProjectPath": str(fixture_project),
    })
    assert result["error"]["code"] == "project_changed"
    assert json.loads((other / "tit" / "1.json").read_text(encoding="utf-8"))["1"] == "another book"


def test_current_review_project_can_use_existing_writer(fixture_project):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    result = call(engine, "verse.edit", {
        "chapter": "1", "verse": "1", "newText": "current queue text",
        "_expectedProjectPath": str(fixture_project),
    })
    assert result["success"]


def test_guarded_request_without_open_project_is_refused():
    result = call(BridgeEngine(), "paratextReview.saveState", {
        "_expectedProjectPath": "C:/a-project", "state": {"position": "old"},
    })
    assert result["error"]["code"] == "project_changed"
