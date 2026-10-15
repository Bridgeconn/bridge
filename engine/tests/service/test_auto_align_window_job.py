"""#242: the page's one-window "Align automatically" as a job.

Before this, alignment.window.autoAlign ran its two provider calls on the
dispatcher thread and nothing else was answered until both returned (275 s
on the installed build, seven languageQa.status timeouts, #241). The window
is now scope "window" of the chapter job: the calls run on the worker, status
carries the pass in flight, and a cancel ends the window at its next
checkpoint before anything is written. Fake transport only.
"""
import json
import threading
import time

from bridge_service import BridgeEngine
from tests.support.alignment_books import unaligned_verse, write_alignment_book
from tests.support.projects import call
from tests.support.waits import job_timeout

TERMINAL = {"succeeded", "failed", "cancelled"}


def _reply():
    return {"links": [], "nulls": [], "unplaced": [], "review_notes": []}


class GatedTransport:
    """Each call waits on its own gate so a test can hold a provider call open."""

    def __init__(self):
        self.calls: list[dict] = []
        self.gates: list[threading.Event] = []
        self.lock = threading.Lock()

    def hold(self) -> threading.Event:
        gate = threading.Event()
        self.gates.append(gate)
        return gate

    def __call__(self, url, headers, request_body, timeout):
        with self.lock:
            index = len(self.calls)
            self.calls.append(json.loads(request_body))
        if index < len(self.gates):
            assert self.gates[index].wait(job_timeout(10.0)), "the test never released the provider"
        return 200, json.dumps({
            "output_text": json.dumps(_reply()),
            "usage": {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
        }).encode("utf-8")

    def wait_for_calls(self, count: int) -> None:
        deadline = time.monotonic() + job_timeout(5.0)
        while len(self.calls) < count and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(self.calls) >= count, f"expected {count} provider call(s), saw {len(self.calls)}"


def _book(tmp_path):
    root = tmp_path / "php"
    verses = {str(v): unaligned_verse(f"w{v}", [(f"λ{v}", f"G{1000 + v}0")]) for v in range(1, 5)}
    write_alignment_book(root, "php", {"1": verses})
    return root


def _engine(root, transport):
    engine = BridgeEngine(ai_transport=transport)
    engine.settings.set_api_key("test-key", persist=False)
    assert call(engine, "project.open", {"path": str(root)})["success"] is True
    return engine


def _status(engine, job_id):
    return call(engine, "alignment.autoAlign.status", {"jobId": job_id})["result"]


def _wait(engine, job_id, *, until=lambda s: s["state"] in TERMINAL, timeout=10.0):
    deadline = time.monotonic() + job_timeout(timeout)
    while time.monotonic() < deadline:
        snapshot = _status(engine, job_id)
        if until(snapshot):
            return snapshot
        time.sleep(0.02)
    raise AssertionError("auto-align window job did not reach the expected state")


def _alignment_file(root):
    return (root / ".apps" / "translationCore" / "alignmentData" / "php" / "1.json").read_bytes()


def test_window_job_keeps_the_dispatcher_free_and_reports_the_pass_in_flight(tmp_path):
    root = _book(tmp_path)
    transport = GatedTransport()
    first = transport.hold()
    second = transport.hold()
    engine = _engine(root, transport)

    started = call(engine, "alignment.autoAlign.start", {
        "scope": "window", "chapters": ["1"], "verses": ["1", "2", "3"],
    })
    assert started["success"] is True, started
    job_id = started["result"]["jobId"]
    assert started["result"]["scope"] == "window"
    assert started["result"]["windowsTotal"] == 1

    transport.wait_for_calls(1)
    # Pass 1 is in flight and the dispatcher answers meanwhile.
    snapshot = _status(engine, job_id)
    assert snapshot["state"] == "running"
    assert snapshot["currentPass"]["number"] == 1 and snapshot["currentPass"]["of"] == 2
    assert snapshot["stage"] == "Asking about 1:1-3 (pass 1 of 2)"
    assert call(engine, "ping")["success"] is True
    assert call(engine, "verse.get", {"chapter": "1", "verse": "1"})["success"] is True

    first.set()
    transport.wait_for_calls(2)
    snapshot = _wait(engine, job_id, until=lambda s: (s["currentPass"] or {}).get("number") == 2)
    assert snapshot["stage"] == "Asking about 1:1-3 (pass 2 of 2)"
    assert snapshot["windowResult"] is None

    second.set()
    finished = _wait(engine, job_id)
    assert finished["state"] == "succeeded", finished
    assert finished["currentPass"] is None
    result = finished["windowResult"]
    assert result["chapter"] == "1" and result["verses"] == ["1", "2", "3"]
    assert [item["verse"] for item in result["results"]] == ["1", "2", "3"]
    assert result["usage"]["calls"] == 2 and result["runId"].startswith("aa-")
    assert all("context" in item and "suggestions" in item for item in result["results"])
    assert finished["verdicts"] == {f"1:{v}": item["verdict"] for v, item in zip("123", result["results"])}


def test_cancel_during_a_provider_call_writes_nothing(tmp_path):
    root = _book(tmp_path)
    before = _alignment_file(root)
    transport = GatedTransport()
    first = transport.hold()
    engine = _engine(root, transport)

    job_id = call(engine, "alignment.autoAlign.start", {
        "scope": "window", "chapters": ["1"], "verses": ["1", "2"],
    })["result"]["jobId"]
    transport.wait_for_calls(1)

    cancelled = call(engine, "alignment.autoAlign.cancel", {"jobId": job_id})["result"]
    assert cancelled["state"] == "cancelling"
    first.set()
    finished = _wait(engine, job_id)
    assert finished["state"] == "cancelled", finished
    # The second pass was never asked for, and nothing reached the project.
    assert len(transport.calls) == 1
    assert finished["windowResult"] is None and finished["windowsDone"] == 0
    assert _alignment_file(root) == before
    for verse in ("1", "2"):
        verdict = call(engine, "alignment.autoAlign.verdict", {"chapter": "1", "verse": verse})["result"]
        assert verdict["verdict"] is None


def test_a_window_job_validates_its_window_like_the_sync_call(tmp_path):
    root = _book(tmp_path)
    engine = _engine(root, GatedTransport())
    two_chapters = call(engine, "alignment.autoAlign.start", {"scope": "window", "chapters": ["1", "2"], "verses": ["1"]})
    assert two_chapters["success"] is False and "exactly one chapter" in two_chapters["error"]["message"]
    no_verses = call(engine, "alignment.autoAlign.start", {"scope": "window", "chapters": ["1"]})
    assert no_verses["success"] is False and "list of verses" in no_verses["error"]["message"]
    unknown = call(engine, "alignment.autoAlign.start", {"scope": "window", "chapters": ["1"], "verses": ["9"]})
    assert unknown["success"] is False and "does not exist" in unknown["error"]["message"]
    estimate = call(engine, "alignment.autoAlign.estimate", {"scope": "window", "chapters": ["1"], "verses": ["1", "2"]})
    assert estimate["success"] is True and estimate["result"]["windows"] == 1 and estimate["result"]["calls"] == 2
