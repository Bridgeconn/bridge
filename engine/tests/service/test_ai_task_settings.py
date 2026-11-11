"""#473: a model and a reasoning effort per AI task (review / alignment /
triage), with "use one model for everything" keeping today's behaviour.

Drives `settings.get` / `settings.set` and the engine's `_ai_client(task)`,
so it lives in tests/service (CLAUDE.md rule 1).
"""
from __future__ import annotations

import json

import pytest
from bridge_service import BridgeEngine
from tc_ai_bridge.model_router import AI_TASKS, DEFAULT_REVIEW_MODEL, cheapest_model, default_task_models
from tc_ai_bridge.secret_store import AppSettings
from tests.support.projects import call


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = AppSettings(path=tmp_path / "settings.json")
    settings.set_api_key("sk-test-123")
    settings.model = "gpt-5.6"
    return BridgeEngine(settings=settings, ai_transport=lambda *a: (200, b"{}"))


def test_the_review_default_is_terra_and_a_saved_model_is_kept(tmp_path, monkeypatch):
    """#479: a fresh install reviews with gpt-5.6-terra at medium; an install
    that saved a model keeps it; a blank save falls back to the default."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    fresh = AppSettings(path=tmp_path / "settings.json")
    fresh.set_api_key("sk-test-123")
    assert fresh.model == DEFAULT_REVIEW_MODEL == "gpt-5.6-terra"
    engine = BridgeEngine(settings=fresh, ai_transport=lambda *a: (200, b"{}"))
    client = engine._ai_client("review")
    assert (client.model, client.reasoning_effort) == ("gpt-5.6-terra", "medium")
    assert call(engine, "settings.get")["result"]["model"] == "gpt-5.6-terra"

    fresh.model = "gpt-5.6"
    assert AppSettings(path=tmp_path / "settings.json").model == "gpt-5.6"
    assert engine._ai_client("review").model == "gpt-5.6"
    fresh.model = "   "
    assert AppSettings(path=tmp_path / "settings.json").model == "gpt-5.6-terra"


def test_defaults_are_one_model_for_everything_at_medium(engine):
    got = call(engine, "settings.get")["result"]["aiTasks"]
    assert got["useOneModel"] is True
    assert set(got["tasks"]) == set(AI_TASKS)
    assert got["tasks"] == default_task_models()
    assert got["tasks"]["review"] == {"model": "", "reasoningEffort": "medium"}
    assert got["tasks"]["alignment"] == {"model": cheapest_model(), "reasoningEffort": "low"}
    assert cheapest_model() == "gpt-5.6-luna"

    for task in AI_TASKS:
        client = engine._ai_client(task)
        assert (client.model, client.reasoning_effort) == ("gpt-5.6", "medium"), task


def test_per_task_rows_apply_only_when_one_model_mode_is_off(engine):
    changed = call(engine, "settings.set", {"aiTasks": {
        "tasks": {"triage": {"model": "gpt-5.6-luna", "reasoningEffort": "low"},
                  "alignment": {"model": "gpt-5.6-terra", "reasoningEffort": "high"}},
    }})
    assert changed["success"] is True, changed
    # Still one-model mode: the rows are stored but not used.
    assert changed["result"]["aiTasks"]["useOneModel"] is True
    assert engine._ai_client("triage").model == "gpt-5.6"

    changed = call(engine, "settings.set", {"aiTasks": {"useOneModel": False}})
    assert changed["success"] is True
    tasks = changed["result"]["aiTasks"]["tasks"]
    # A partial set kept the rows it did not name.
    assert tasks["triage"] == {"model": "gpt-5.6-luna", "reasoningEffort": "low"}
    assert tasks["alignment"] == {"model": "gpt-5.6-terra", "reasoningEffort": "high"}
    assert tasks["review"] == {"model": "", "reasoningEffort": "medium"}

    triage = engine._ai_client("triage")
    alignment = engine._ai_client("alignment")
    review = engine._ai_client("review")
    assert (triage.model, triage.reasoning_effort) == ("gpt-5.6-luna", "low")
    assert (alignment.model, alignment.reasoning_effort) == ("gpt-5.6-terra", "high")
    # The review row's blank model is the configured model; its tier is not
    # changed here (that waits on the #469 comparison).
    assert (review.model, review.reasoning_effort) == ("gpt-5.6", "medium")

    # The choice survives a restart and is what the estimate prices.
    restarted = BridgeEngine(settings=AppSettings(path=engine.settings.path))
    assert restarted.settings.ai_task_choice("alignment") == ("gpt-5.6-terra", "high")


def test_invalid_task_or_effort_is_rejected_and_nothing_changes(engine):
    before = call(engine, "settings.get")["result"]["aiTasks"]
    for bad in (
        {"tasks": {"summaries": {"model": "x"}}},
        {"tasks": {"triage": {"reasoningEffort": "max"}}},
        {"useOneModel": "no"},
        ["review"],
    ):
        result = call(engine, "settings.set", {"aiTasks": bad})
        assert result["success"] is False, bad
    assert call(engine, "settings.get")["result"]["aiTasks"] == before


def test_the_task_model_is_what_the_request_carries(tmp_path, monkeypatch):
    """The triage client really sends the triage row's model and effort."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    requests: list[dict] = []

    def transport(url, headers, body, timeout):
        requests.append(json.loads(body))
        return 200, json.dumps({"output_text": json.dumps({"results": []}),
                                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}).encode()

    settings = AppSettings(path=tmp_path / "settings.json")
    settings.set_api_key("sk-test-123")
    settings.model = "gpt-5.6"
    settings.ai_tasks = {"useOneModel": False, "tasks": {"triage": {"model": "gpt-5.6-luna", "reasoningEffort": "low"}}}
    engine = BridgeEngine(settings=settings, ai_transport=transport)

    engine._ai_client("triage").triage_batch("i", "x")
    engine._ai_client("review")._post_text("i", "x", "s", {"type": "object"})
    assert requests[0]["model"] == "gpt-5.6-luna" and requests[0]["reasoning"] == {"effort": "low"}
    assert requests[1]["model"] == "gpt-5.6" and requests[1]["reasoning"] == {"effort": "medium"}
