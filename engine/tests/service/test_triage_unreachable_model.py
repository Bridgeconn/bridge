"""#318: AI triage against a model it cannot reach stores nothing.

A batch that never reached the model (connection refused, DNS, timeout) used
to leave an "Uncertain · 0%" record for every finding in it, which the report
then counted as scored. Now those findings stay untriaged, the job reports the
failure, and only a model that answered without a usable verdict still yields
an uncertain record.

No network is touched: the real OpenAIResponsesClient is used with
`ai_http.urlopen` patched to raise the URLError that a refused connection
produces, so the failure is classified by the client's own transport.
"""
import json
import time
import urllib.error
import uuid

from bridge_service import BridgeEngine
from tc_ai_bridge import ai_http
from tc_ai_bridge.ai_client import OpenAIResponsesClient
from tc_ai_bridge.tc_project import TranslationCoreProject

from tests.support.projects import call, fixture_project  # noqa: F401
from tests.support.waits import job_timeout


def _finding(**overrides):
    base = {
        "id": "f1", "engine": "wildebeest", "check_type": "wildebeest.script.mixed",
        "category": "unicode", "severity": "high", "original_text": "ஆதி",
        "explanation": "Latin character mixed into Tamil text.",
        "evidence": [{"label": "script", "value": "Latin + Tamil"}], "status": "open",
    }
    base.update(overrides)
    return base


def _plant(root, findings):
    # Give the fixture its registered id first, as project.open would, so the
    # snapshot is keyed to the id the opened project reads.
    marker = root / ".bridge" / "project.json"
    if not marker.is_file():
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"schemaVersion": 1, "projectId": str(uuid.uuid4())}), encoding="utf-8")
    TranslationCoreProject(root).save_check_findings_snapshot("1", {"1": findings})


def _engine_with(root, client, monkeypatch):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(root)})
    monkeypatch.setattr(engine, "_ai_client", lambda: client)
    return engine


def _run(engine):
    started = call(engine, "triage.run")
    assert started["success"] is True, started
    job_id = started["result"]["jobId"]
    deadline = time.monotonic() + job_timeout(5.0)
    while time.monotonic() < deadline:
        snapshot = call(engine, "triage.status", {"jobId": job_id})["result"]
        if snapshot["state"] in {"succeeded", "failed", "cancelled"}:
            return snapshot
        time.sleep(0.01)
    raise AssertionError(f"triage job {job_id} did not finish")


def test_an_unreachable_endpoint_stores_no_verdict_and_the_job_reports_the_error(fixture_project, monkeypatch):
    _plant(fixture_project, [_finding(id="f1"), _finding(id="f2", check_type="usfm.marker",
                                                         explanation="Unclosed marker.")])
    refused = ConnectionRefusedError(10061, "No connection could be made because the target machine actively refused it")
    attempts = []

    def no_network(req, timeout):
        attempts.append(req.full_url)
        raise urllib.error.URLError(refused)

    monkeypatch.setattr(ai_http, "urlopen", no_network)
    client = OpenAIResponsesClient("sk-test", model="gpt-5.6", base_url="http://127.0.0.1:9/v1")
    engine = _engine_with(fixture_project, client, monkeypatch)

    snapshot = _run(engine)

    assert attempts and all(url == "http://127.0.0.1:9/v1/responses" for url in attempts)
    assert snapshot["state"] == "failed"
    assert snapshot["batches"] == 2
    assert snapshot["failedBatches"] == snapshot["unreachedBatches"] == 2
    assert snapshot["triaged"] == 0
    assert "could not reach the model" in snapshot["error"]
    assert "left untriaged" in snapshot["error"]
    assert "The model could not be reached: Network error contacting OpenAI" in snapshot["error"]
    assert "left uncertain" not in snapshot["error"]

    results = call(engine, "triage.results")["result"]
    assert results["total"] == 0
    assert results["entries"] == {}
    # The engine is still alive and answering.
    assert call(engine, "ping")["success"] is True


def test_a_model_that_answers_without_a_usable_verdict_still_stores_uncertain(fixture_project, monkeypatch):
    _plant(fixture_project, [_finding()])

    def unusable_answer(url, headers, body, timeout):
        return 200, json.dumps({
            "output": [{"content": [{"text": "Sorry, I can't help with that."}]}],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }).encode("utf-8")

    client = OpenAIResponsesClient("sk-test", model="gpt-5.6", transport=unusable_answer)
    engine = _engine_with(fixture_project, client, monkeypatch)

    snapshot = _run(engine)

    assert snapshot["state"] == "failed"
    assert (snapshot["failedBatches"], snapshot["unreachedBatches"]) == (1, 0)
    assert "1 batch produced no usable result; those findings were left uncertain." in snapshot["error"]
    results = call(engine, "triage.results")["result"]
    assert results["total"] == 1
    [record] = results["entries"].values()
    assert (record["verdict"], record["confidence"]) == ("uncertain", 0)
    assert "could not be parsed" in record["reason"]
