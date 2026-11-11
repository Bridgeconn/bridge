"""#477: the lifetime AI usage counter is readable and resettable through
settings. `settings.get` returns it (tokens, estimated cost, the UTC time the
counter started) and `settings.set {resetAiUsage: true}` zeroes it and dates
the reset. Drives the RPCs, so it lives in tests/service (CLAUDE.md rule 1).
"""
from __future__ import annotations

from datetime import datetime

from bridge_service import BridgeEngine
from tc_ai_bridge.secret_store import AppSettings
from tests.support.projects import call


def _engine(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = AppSettings(path=tmp_path / "settings.json")
    return BridgeEngine(settings=settings), settings


def test_settings_get_reports_the_counter_and_when_it_started(tmp_path, monkeypatch):
    engine, settings = _engine(tmp_path, monkeypatch)
    assert call(engine, "settings.get")["result"]["aiUsage"] == {
        "tokens": 0, "estimatedCostUSD": 0.0, "since": None,
    }
    settings.record_ai_usage(1_500, 0.0125)
    settings.record_ai_usage(500, 0.0025)
    usage = call(engine, "settings.get")["result"]["aiUsage"]
    assert usage["tokens"] == 2_000
    assert abs(usage["estimatedCostUSD"] - 0.015) < 1e-9
    started = datetime.fromisoformat(usage["since"])
    assert started.tzinfo is not None
    # The start is the first counted call, not the latest.
    settings.record_ai_usage(1, 0.0)
    assert call(engine, "settings.get")["result"]["aiUsage"]["since"] == usage["since"]


def test_settings_set_reset_zeroes_the_counter_and_dates_the_reset(tmp_path, monkeypatch):
    engine, settings = _engine(tmp_path, monkeypatch)
    settings.record_ai_usage(7_159_086, 45.38)
    before = call(engine, "settings.get")["result"]["aiUsage"]
    reply = call(engine, "settings.set", {"resetAiUsage": True})
    assert reply["success"] is True, reply
    after = reply["result"]["aiUsage"]
    assert after["tokens"] == 0 and after["estimatedCostUSD"] == 0.0
    assert after["since"] is not None and after["since"] >= before["since"]
    # Survives a reload of the settings file, and counts on from zero.
    reloaded = AppSettings(path=settings.path)
    assert reloaded.get_ai_usage_totals() == after
    reloaded.record_ai_usage(10, 0.001)
    assert reloaded.get_ai_usage_totals()["tokens"] == 10
    assert reloaded.get_ai_usage_totals()["since"] == after["since"]
    # Anything but an explicit true is ignored.
    settings.record_ai_usage(5, 0.0)
    assert call(engine, "settings.set", {"resetAiUsage": "yes"})["result"]["aiUsage"]["tokens"] == 5


def test_a_counter_from_before_477_has_no_start_until_reset(tmp_path, monkeypatch):
    engine, settings = _engine(tmp_path, monkeypatch)
    settings.data["ai_usage_totals"] = {"tokens": 100, "estimatedCostUSD": 0.5}
    settings.record_ai_usage(1, 0.0)
    assert call(engine, "settings.get")["result"]["aiUsage"] == {
        "tokens": 101, "estimatedCostUSD": 0.5, "since": None,
    }
