"""End-to-end coverage for the newline-delimited sidecar process boundary."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path


from tests.support.paths import ENGINE_ROOT
from tests.support.waits import job_timeout


class Sidecar:
    def __init__(self, entrypoint: Path | None = None) -> None:
        self.process = subprocess.Popen(
            [sys.executable, str(entrypoint or ENGINE_ROOT / "main.py")],
            cwd=ENGINE_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        # The stage lines (#233) come first, each before the work it names;
        # the ready line ends the boot. Anything else on stdout before ready
        # is a protocol corruption, not a response, so it fails here.
        self.stages: list[str] = []
        while True:
            frame = self._read()
            if frame["id"] == "__ready__":
                break
            assert frame["id"] == "__stage__", frame
            self.stages.append(frame["result"]["stage"])
        self.sequence = 0

    def _read(self) -> dict:
        assert self.process.stdout is not None
        line = self.process.stdout.readline()
        assert line, "sidecar exited before returning a response"
        return json.loads(line)

    def request(self, method: str, params: dict) -> dict:
        self.sequence += 1
        request_id = f"e2e-{self.sequence}"
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps({
            "id": request_id,
            "method": method,
            "params": params,
        }, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        response = self._read()
        assert response["id"] == request_id
        assert response["success"] is True, response
        return response

    def close(self) -> None:
        self.process.terminate()
        try:
            self.process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.communicate(timeout=5)


def _wait_for_job(sidecar: Sidecar, job_id: str) -> dict:
    deadline = time.monotonic() + job_timeout(20)
    while time.monotonic() < deadline:
        snapshot = sidecar.request("checks.status", {"jobId": job_id})["result"]
        if snapshot["state"] in {"succeeded", "failed", "cancelled"}:
            return snapshot
        time.sleep(0.02)
    raise AssertionError("background sidecar job did not finish")


def test_import_check_decide_restart_edit_and_export_over_stdio(tmp_path):
    source = tmp_path / "TIT.usfm"
    source.write_text(
        "\\id TIT\n\\h தீத்து\n\\c 1\n\\p\n\\v 1 தேவன்aஆதி\n",
        encoding="utf-8",
    )
    projects = tmp_path / "projects"
    aligned = tmp_path / "aligned.json"
    non_aligned = tmp_path / "non-aligned.usfm"

    sidecar = Sidecar()
    try:
        imported = sidecar.request("project.import", {
            "path": str(source),
            "destinationRoot": str(projects),
            "metadata": {
                "languageId": "tam",
                "languageName": "Tamil",
                "projectName": "Tamil Titus",
                "bibleName": "Tamil Bible",
            },
        })["result"]
        project_path = imported["path"]

        started = sidecar.request("checks.start", {
            "scope": "chapter",
            "chapters": ["1"],
            "checks": ["greekroom"],
        })["result"]
        snapshot = _wait_for_job(sidecar, started["jobId"])
        assert snapshot["state"] == "succeeded"
        findings = snapshot["results"]["1:1"]["findings"]
        finding = next(item for item in findings if item["engine"] == "wildebeest")

        sidecar.request("verse.decide", {
            "chapter": "1",
            "verse": "1",
            "findingId": finding["id"],
            "status": "accepted",
            "comment": "stdio review",
        })
    finally:
        sidecar.close()

    # A fresh process proves that review state is on disk, not only cached
    # inside the original BridgeEngine instance.
    restarted = Sidecar()
    try:
        restarted.request("project.open", {"path": project_path})
        checked = restarted.request("verse.runChecks", {
            "chapter": "1", "verse": "1", "checks": ["greekroom"],
        })["findings"]
        persisted = next(item for item in checked if item["id"] == finding["id"])
        assert persisted["status"] == "accepted"
        assert persisted["human_comment"] == "stdio review"

        restarted.request("verse.edit", {
            "chapter": "1", "verse": "1", "newText": "தேவன் ஆதி",
        })
        verse = restarted.request("verse.get", {"chapter": "1", "verse": "1"})["result"]
        assert verse["text"] == "தேவன் ஆதி"

        restarted.request("export.aligned", {"outputPath": str(aligned)})
        restarted.request("export.nonAligned", {"outputPath": str(non_aligned)})
    finally:
        restarted.close()

    aligned_data = json.loads(aligned.read_text(encoding="utf-8"))
    assert aligned_data["chapters"]["1"]["1"]["text"] == "தேவன் ஆதி"
    exported_usfm = non_aligned.read_text(encoding="utf-8")
    assert "\\v 1 தேவன் ஆதி" in exported_usfm
    assert (Path(project_path) / ".apps" / "translationCoreAI" / "transactions").is_dir()



def test_uroman_loads_after_ready_and_engine_info_does_not_wait_for_it(tmp_path):
    """main.py starts the uroman preload after the ready line (#242):
    engine.info answers at once with names available, and names reports
    loaded once the background load finishes."""
    entered, release = tmp_path / "loading", tmp_path / "release"
    bootstrap = tmp_path / "gated_main.py"
    bootstrap.write_text(
        "import runpy, sys, time\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(ENGINE_ROOT)!r})\n"
        "from greek_room_engine.adapters import names_adapter\n"
        "original = names_adapter._ensure_uroman\n"
        "def gated_load():\n"
        f"    Path({str(entered)!r}).touch()\n"
        f"    while not Path({str(release)!r}).exists():\n"
        "        time.sleep(.01)\n"
        "    return original()\n"
        "names_adapter._ensure_uroman = gated_load\n"
        f"runpy.run_path({str(ENGINE_ROOT / 'main.py')!r}, run_name='__main__')\n",
        encoding="utf-8",
    )
    sidecar = Sidecar(bootstrap)
    returned = threading.Event()
    responses = []
    caller = None
    try:
        deadline = time.monotonic() + job_timeout(30)
        while not entered.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert entered.exists(), "background preload did not start after ready"

        def request_info():
            responses.append(sidecar.request("engine.info", {}))
            returned.set()

        caller = threading.Thread(target=request_info, daemon=True)
        caller.start()
        # The loader cannot finish until we release it: a response now proves
        # engine.info is independent of its completion, under any CPU load.
        assert returned.wait(10), "engine.info waited for the held preload"
        info = responses[0]
        names = info["result"]["greekRoom"]["adapters"]["names"]
        assert names["available"] is True
        assert names["state"] == "loading"
        release.touch()
        deadline = time.monotonic() + job_timeout(30)
        while names.get("state") != "loaded" and time.monotonic() < deadline:
            time.sleep(0.25)
            names = sidecar.request("engine.info", {})["result"]["greekRoom"]["adapters"]["names"]
        assert names["state"] == "loaded", names
    finally:
        release.touch()
        if caller is not None:
            caller.join(10)
        sidecar.close()


def test_startup_stage_lines_precede_the_ready_line():
    """main.py reports "modules" before importing bridge_service and
    "engine" before constructing BridgeEngine (#233); the shell turns them
    into the loading screen's status line. Order matters: a stage after
    the work it names would describe the past."""
    sidecar = Sidecar()
    try:
        assert sidecar.stages == ["modules", "engine"]
        assert sidecar.request("ping", {})["result"]["pong"] is True
    finally:
        sidecar.close()
