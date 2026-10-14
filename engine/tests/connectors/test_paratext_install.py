"""Installing Bridge's Paratext connector on the user's PC (#282): finding
Paratext 9, reading the installed version, deciding install/update, the
elevated copy script, the CLI the installer runs, and the worker-thread
installer. No Paratext is touched: every path is a temp folder, the compiler
and the elevation are fakes, except one real compile that runs only where
Paratext 9 is installed."""
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tc_ai_bridge import paratext_install as pi

windows_only = pytest.mark.skipif(os.name != "nt", reason="the connector is a Windows-only Paratext 9 plugin")


def paratext_at(root: Path, *, connector: bytes | None = None, version_file: str | None = None) -> Path:
    folder = root / "Paratext 9"
    folder.mkdir(parents=True)
    for dll in pi.INTERFACE_DLLS:
        (folder / dll).write_bytes(b"MZ")
    if connector is not None:
        plugins = pi.plugin_folder(folder)
        plugins.mkdir(parents=True)
        (plugins / f"{pi.PLUGIN_NAME}.ptxplg").write_bytes(connector)
        if version_file is not None:
            (plugins / pi.VERSION_FILE).write_text(version_file, encoding="utf-8")
    return folder


def registry_for(folder: Path):
    return lambda: {"Paratext9_Full_Release_AppPath": str(folder) + "\\", "ParatextVersion": "9.5.110.1"}


def utf16(text: str) -> bytes:
    return text.encode("utf-16-le")


def test_bundled_version_is_the_connector_sources_plugin_version():
    source = (pi.source_dir() / pi.SOURCES[0]).read_text(encoding="utf-8-sig")
    assert f'PluginVersion = "{pi.bundled_version()}"' in source
    assert all((pi.source_dir() / name).is_file() for name in pi.SOURCES)


def test_find_paratext9_needs_the_interface_dlls(tmp_path):
    folder = paratext_at(tmp_path)
    assert pi.find_paratext9(registry_for(folder)) == (folder, "9.5.110.1")
    (folder / pi.INTERFACE_DLLS[0]).unlink()
    found, _ = pi.find_paratext9(registry_for(folder))
    assert found != folder


def test_installed_version_reads_the_stamp_then_the_compiled_string(tmp_path):
    stamped = paratext_at(tmp_path / "a", connector=b"MZ", version_file="0.7.4\n")
    assert pi.installed_version(stamped) == (True, "0.7.4")
    # Deployed by hand with build.ps1: no stamp; the PluginVersion const is a
    # UTF-16 string in the assembly.
    # Laid out as a real assembly: the CLR's "v4.0.30319" is ASCII, NUL-padded,
    # in the metadata header; a user string sits in the #US heap behind its
    # length byte (11 = 5 UTF-16 chars + the trailing flag byte).
    by_hand = paratext_at(tmp_path / "b", connector=b"MZ\x00\x00v4.0.30319\x00\x00\x00\x00\x0b"
                          + utf16("0.7.4") + b"\x00")
    assert pi.installed_version(by_hand) == (True, "0.7.4")
    absent = paratext_at(tmp_path / "c")
    assert pi.installed_version(absent) == (False, "")


@windows_only
def test_status_decides_install_update_or_none(tmp_path):
    bundled = pi.bundled_version()
    never = lambda: False  # noqa: E731
    fresh = paratext_at(tmp_path / "fresh")
    assert pi.status(registry=registry_for(fresh), running=never)["action"] == "install"
    old = paratext_at(tmp_path / "old", connector=b"MZ", version_file="0.1.0")
    result = pi.status(registry=registry_for(old), running=never)
    assert (result["action"], result["installedVersion"], result["bundledVersion"]) == ("update", "0.1.0", bundled)
    current = paratext_at(tmp_path / "current", connector=b"MZ", version_file=bundled)
    assert pi.status(registry=registry_for(current), running=never)["action"] == "none"
    unknown = paratext_at(tmp_path / "unknown", connector=b"MZ")
    assert pi.status(registry=registry_for(unknown), running=never)["action"] == "update"


def test_status_without_paratext9_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(pi, "DEFAULT_PARATEXT_DIR", tmp_path / "nowhere")
    result = pi.status(registry=lambda: {}, running=lambda: False)
    assert result["action"] == "unavailable" and not result["paratextFound"]


@windows_only
def test_install_refuses_while_paratext_runs_and_never_compiles(tmp_path):
    folder = paratext_at(tmp_path)
    compiled = []
    with pytest.raises(pi.ConnectorInstallError, match="Close Paratext first"):
        pi.install(registry=registry_for(folder), running=lambda: True,
                   compile_step=lambda *a, **k: compiled.append(1), elevate=lambda s: 0)
    assert not compiled


def fake_compile(paratext_dir, out_dir, *, src=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    dll = out_dir / f"{pi.PLUGIN_NAME}.dll"
    dll.write_bytes(b"MZ-fake-connector")
    return dll


def run_script_unelevated(script: Path) -> int:
    """The generated script, run for real: the target is a temp folder, so it
    needs no administrator rights here."""
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-File", str(script)], capture_output=True, timeout=120).returncode


@windows_only
@pytest.mark.skipif(shutil.which("powershell") is None, reason="needs Windows PowerShell")
def test_install_copies_the_plugin_as_ptxplg_and_stamps_its_version(tmp_path):
    folder = paratext_at(tmp_path / "it's here")  # a quote in the path: the script must escape it
    result = pi.install(registry=registry_for(folder), running=lambda: False,
                        compile_step=fake_compile, elevate=run_script_unelevated)
    plugin = pi.plugin_folder(folder) / f"{pi.PLUGIN_NAME}.ptxplg"
    assert plugin.read_bytes() == b"MZ-fake-connector"
    assert (pi.plugin_folder(folder) / pi.VERSION_FILE).read_text().strip() == pi.bundled_version()
    assert result["installedNow"] and result["action"] == "none"


@windows_only
def test_a_failed_or_declined_elevation_is_reported_and_installs_nothing(tmp_path):
    folder = paratext_at(tmp_path)
    with pytest.raises(pi.ConnectorInstallError, match="exit code 1"):
        pi.install(registry=registry_for(folder), running=lambda: False, compile_step=fake_compile,
                   elevate=lambda script: 1)

    def declined(script):
        raise pi.ConnectorInstallError("The Windows administrator prompt was declined, so nothing was installed.")

    with pytest.raises(pi.ConnectorInstallError, match="declined"):
        pi.install(registry=registry_for(folder), running=lambda: False, compile_step=fake_compile, elevate=declined)
    assert not pi.plugin_folder(folder).exists()


def test_a_compiler_failure_is_reported_with_its_last_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(pi, "find_compiler", lambda: tmp_path / "csc.exe")

    class Failed:
        returncode, stdout, stderr = 1, "line one\nerror CS0246: PluginInterfaces not found", ""

    with pytest.raises(pi.ConnectorInstallError, match="CS0246"):
        pi.compile_connector(tmp_path, tmp_path / "out", run=lambda *a, **k: Failed())


real_paratext, _ = pi.find_paratext9()


@windows_only
@pytest.mark.skipif(real_paratext is None or pi.find_compiler() is None,
                    reason="needs Paratext 9 and the .NET Framework compiler (not on CI)")
def test_the_connector_compiles_against_the_installed_paratext(tmp_path):
    dll = pi.compile_connector(real_paratext, tmp_path / "build")
    assert dll.is_file() and dll.read_bytes()[:2] == b"MZ"
    assert utf16(pi.bundled_version()) in dll.read_bytes()


def test_cli_exit_codes(monkeypatch):
    lines = []
    cases = [({"action": "unavailable", "paratextFound": False, "message": "no Paratext"}, pi.EXIT_NO_PARATEXT),
             ({"action": "none", "paratextFound": True, "message": "current"}, pi.EXIT_NOT_NEEDED),
             ({"action": "install", "paratextFound": True, "running": True, "message": ""}, pi.EXIT_PARATEXT_RUNNING)]
    for current, code in cases:
        monkeypatch.setattr(pi, "status", lambda current=current: current)
        assert pi.cli(lines.append) == code
    monkeypatch.setattr(pi, "status", lambda: {"action": "install", "paratextFound": True, "running": False})
    monkeypatch.setattr(pi, "install", lambda: {"message": "installed"})
    assert pi.cli(lines.append) == pi.EXIT_INSTALLED and lines[-1] == "installed"

    def declined():
        raise pi.ConnectorInstallError("The Windows administrator prompt was declined, so nothing was installed.")

    monkeypatch.setattr(pi, "install", declined)
    assert pi.cli(lines.append) == pi.EXIT_CANCELLED


def test_the_installer_runs_off_the_calling_thread_and_reports_its_result():
    gate = []

    def slow_install():
        while not gate:
            time.sleep(0.01)
        return {"message": "done"}

    installer = pi.ConnectorInstaller(install_fn=slow_install, status_fn=lambda: {"action": "install"})
    started = time.monotonic()
    assert installer.start()["install"]["state"] == "running"
    assert time.monotonic() - started < 1.0, "start() must not wait for the install"
    assert installer.start()["install"]["state"] == "running", "a second start joins the first"
    gate.append(1)
    deadline = time.monotonic() + 10
    while installer.snapshot()["install"]["state"] == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert installer.snapshot()["install"] == {"state": "succeeded", "message": "done"}

    def failing():
        raise pi.ConnectorInstallError("Close Paratext first: …")

    failed = pi.ConnectorInstaller(install_fn=failing, status_fn=lambda: {})
    failed.start()
    deadline = time.monotonic() + 10
    while failed.snapshot()["install"]["state"] == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert failed.snapshot()["install"]["state"] == "failed"
