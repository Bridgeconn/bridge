import threading
import time

from tc_ai_bridge.navigation import NavigationSyncCoordinator
from tests.support.waits import job_timeout


class FakeOwnership:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.owned = False

    def acquire(self):
        self.owned = self.allowed
        return self.owned

    def release(self):
        self.owned = False


class FakeConnector:
    def __init__(self, reference="TIT 1:1", project_id="", project_name=""):
        self.reference = reference
        self.project_id = project_id
        self.project_name = project_name
        self.sent = []
        self.state_reads = 0

    def get_state(self):
        self.state_reads += 1
        return {"connected": True, "reference": self.reference,
                "project_id": self.project_id, "project_name": self.project_name}

    def set_reference(self, reference, origin_id=""):
        self.reference = reference
        self.sent.append((reference, origin_id))
        return {"connected": True, "reference": reference}


def wait_for(predicate, timeout=1.0):
    deadline = time.monotonic() + job_timeout(timeout)
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("navigation coordinator did not settle")


def make_coordinator(paratext, logos, ownership=None, expected=None):
    return NavigationSyncCoordinator(
        paratext_client=lambda: paratext,
        logos_client=lambda: logos,
        ownership=ownership or FakeOwnership(),
        poll_interval_seconds=0.01,
        paratext_expected=lambda: dict(expected or {}),
    )


# #347 (Revant's decision, 2026-10-24): the expected Paratext project is the
# open book's link Guid; a different active project holds navigation both ways.
IRVTAM = {"id": "c2d042a9-linked-guid", "name": "IRVTam"}


def test_a_different_active_paratext_project_holds_navigation_both_ways_and_names_both():
    paratext = FakeConnector("TIT 1:1", project_id="4ae31b0d-other-guid", project_name="DVT")
    sync = make_coordinator(paratext, FakeConnector(), expected=IRVTAM)
    sync.bridge_changed("TIT 1:2")
    sync.configure(paratext=True, logos=False)

    state = wait_for(lambda: (s := sync.snapshot(context="clean"))["paratext"].get("projectMismatch") and s)
    # Outbound: Bridge's verse was not pushed into DVT.
    assert paratext.sent == []
    assert state["paratext"]["expectedProjectId"] == IRVTAM["id"]
    assert state["paratext"]["expectedProjectName"] == "IRVTam"
    message = state["paratext"]["mismatchMessage"]
    assert "DVT (4ae31b0d…)" in message and "IRVTam (c2d042a9…)" in message
    assert "does not match" in message
    # Inbound: DVT moving is not navigation to follow.
    # Probes run only while something asks for a snapshot, as the UI's poll does.
    poll = lambda predicate: wait_for(lambda: (sync.snapshot(context="clean"), predicate())[1])  # noqa: E731
    paratext.reference = "TIT 2:3"
    reads = paratext.state_reads
    poll(lambda: paratext.state_reads >= reads + 3)
    assert sync.snapshot(context="clean")["candidate"] is None
    assert sync.snapshot(context="clean")["paratext"]["reference"] == "TIT 2:3"

    # The link matches again: the held destination goes out, and Paratext's
    # next move is offered as before.
    paratext.project_id = IRVTAM["id"]
    paratext.project_name = "IRVTam"
    poll(lambda: len(paratext.sent) == 1)
    assert paratext.sent[0][0] == "TIT 1:2"
    state = wait_for(lambda: (s := sync.snapshot(context="clean"))["paratext"].get("projectMismatch") is False and s)
    assert state["paratext"]["mismatchMessage"] == ""
    paratext.reference = "TIT 2:4"
    candidate = wait_for(lambda: sync.snapshot(context="clean")["candidate"])
    assert candidate == {"reference": "TIT 2:4", "origin": "paratext", "requestId": candidate["requestId"]}


def test_without_a_linked_book_or_a_reported_project_there_is_nothing_to_check():
    # No linked book open: any project is followed, as before #347.
    paratext = FakeConnector("TIT 1:1", project_id="4ae31b0d-other-guid", project_name="DVT")
    sync = make_coordinator(paratext, FakeConnector(), expected={})
    sync.bridge_changed("TIT 1:2")
    sync.configure(paratext=True, logos=False)
    wait_for(lambda: len(paratext.sent) == 1)
    state = sync.snapshot(context="clean")
    assert state["paratext"]["projectMismatch"] is False
    assert state["paratext"]["expectedProjectId"] == ""
    sync.close()

    # A connector that names no project (an older companion) cannot be checked.
    quiet = FakeConnector("TIT 1:1")
    sync = make_coordinator(quiet, FakeConnector(), expected=IRVTAM)
    sync.bridge_changed("TIT 1:2")
    sync.configure(paratext=True, logos=False)
    wait_for(lambda: len(quiet.sent) == 1)
    assert sync.snapshot(context="clean")["paratext"]["projectMismatch"] is False
    sync.close()


def test_bridge_reference_is_sent_to_each_enabled_connector_without_blocking():
    paratext = FakeConnector()
    logos = FakeConnector()
    sync = make_coordinator(paratext, logos)
    sync.bridge_changed("TIT 1:2")

    started = time.monotonic()
    state = sync.configure(paratext=True, logos=True)
    assert time.monotonic() - started < 0.1
    assert state["ownsNavigation"] is True

    wait_for(lambda: len(paratext.sent) == 1 and len(logos.sent) == 1)
    assert paratext.sent[0][0] == "TIT 1:2"
    assert logos.sent[0][0] == "TIT 1:2"


def test_external_navigation_is_committed_then_forwarded_only_to_other_connector():
    paratext = FakeConnector("TIT 1:1")
    logos = FakeConnector("TIT 1:1")
    sync = make_coordinator(paratext, logos)
    sync.bridge_changed("TIT 1:1")
    sync.configure(paratext=True, logos=True)
    wait_for(lambda: not sync._polling)
    paratext.sent.clear()
    logos.sent.clear()

    paratext.reference = "TIT 1:2"
    candidate = wait_for(lambda: sync.snapshot(context="clean")["candidate"])
    assert candidate["origin"] == "paratext"
    assert candidate["reference"] == "TIT 1:2"

    sync.resolve(candidate["requestId"], accepted=True, bridge_reference="TIT 1:2")
    wait_for(lambda: len(logos.sent) == 1)
    assert paratext.sent == []
    assert logos.sent[0][0] == "TIT 1:2"


def test_rejected_external_reference_is_reoffered_only_after_context_changes():
    paratext = FakeConnector("TIT 1:1")
    sync = make_coordinator(paratext, FakeConnector())
    sync.bridge_changed("TIT 1:1")
    sync.configure(paratext=True, logos=False)
    wait_for(lambda: not sync._polling)

    paratext.reference = "TIT 1:2"
    candidate = wait_for(lambda: sync.snapshot(context="editing")["candidate"])
    sync.resolve(
        candidate["requestId"], accepted=False, bridge_reference="TIT 1:1", context="editing",
    )

    wait_for(lambda: not sync._polling)
    time.sleep(0.11)
    sync.snapshot(context="editing")
    wait_for(lambda: not sync._polling)
    assert sync.snapshot(schedule_probe=False)["candidate"] is None

    retried = wait_for(lambda: sync.snapshot(context="clean")["candidate"])
    assert retried["reference"] == "TIT 1:2"


def test_owner_conflict_prevents_connector_calls():
    paratext = FakeConnector()
    sync = make_coordinator(paratext, FakeConnector(), FakeOwnership(allowed=False))
    state = sync.configure(paratext=True, logos=False)
    assert state["ownerConflict"] is True
    assert state["ownsNavigation"] is False
    time.sleep(0.03)
    assert paratext.sent == []


def test_slow_connector_probe_does_not_block_snapshot():
    release = threading.Event()
    returned = threading.Event()
    states = []

    class SlowConnector(FakeConnector):
        def get_state(self):
            release.wait()
            return super().get_state()

    sync = make_coordinator(SlowConnector(), FakeConnector())
    def configure():
        states.append(sync.configure(paratext=True, logos=False))
        returned.set()

    caller = threading.Thread(target=configure, daemon=True)
    caller.start()
    try:
        # Completion while get_state is still held proves non-blocking behavior
        # without treating scheduler latency as connector latency.
        assert returned.wait(10), "configure waited for the connector probe"
        assert states[0]["paratext"]["checking"] is True
    finally:
        release.set()
        caller.join(10)
        sync.close()


def test_latest_bridge_reference_retries_when_connector_starts_late():
    class StartingConnector(FakeConnector):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        def set_reference(self, reference, origin_id=""):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("connector is still starting")
            return super().set_reference(reference, origin_id)

    paratext = StartingConnector()
    sync = make_coordinator(paratext, FakeConnector())
    sync.bridge_changed("TIT 1:3")
    sync.configure(paratext=True, logos=False)

    wait_for(lambda: paratext.attempts >= 1 and not sync._polling)
    wait_for(lambda: (sync.snapshot()["paratext"]["connected"] and paratext.attempts >= 2))
    assert paratext.reference == "TIT 1:3"
