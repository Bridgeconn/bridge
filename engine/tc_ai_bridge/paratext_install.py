"""Install Bridge's Paratext connector on the translator's own PC (#282).

The connector is the Paratext 9 plugin in `paratext_plugin/` (C#, protocol 1
over the local named pipe `\\\\.\\pipe\\translationCoreAIBridge`). Paratext 9
loads a plugin only from `<Paratext 9>\\plugins\\<name>\\<name>.ptxplg`, under
Program Files, so installing it needs administrator rights and Paratext must be
closed. Until now that meant `paratext_plugin/build.ps1 -Deploy` from an
Administrator shell.

Here it is compiled on the user's PC, as build.ps1 does, with the .NET
Framework `csc.exe` that ships with Windows, against that PC's own Paratext
interface DLLs (Benz, 2026-10-14). So it always matches the installed
Paratext, no binary is kept in git, and CI needs no Paratext. The compiled
plugin is then copied in by one elevated step (one Windows admin prompt).

Nothing here touches Scripture, a Paratext project or Paratext's settings: the
only write is the plugin folder.

Used from two places: the Settings › Connections button (the
`paratext.connectorStatus` / `paratext.installConnector` RPCs) and Bridge's
installer (`bridge-engine --install-paratext-connector`, run by the NSIS
post-install hook).
"""
from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

PLUGIN_NAME = "translationCoreAIBridge"
SOURCES = ("AiBridgeConnectorPlugin.cs", "NamedPipeBridgeServer.cs", "BridgeProtocol.cs")
INTERFACE_DLLS = ("PluginInterfaces.dll", "CorePluginInterfaces.dll")
VERSION_FILE = "connector-version.txt"
PARATEXT_REGISTRY_KEYS = (r"SOFTWARE\WOW6432Node\Paratext\8", r"SOFTWARE\Paratext\8")
DEFAULT_PARATEXT_DIR = Path(r"C:\Program Files\Paratext 9")
_VERSION = re.compile(r'PluginVersion\s*=\s*"(\d+(?:\.\d+){1,3})"')
_NO_WINDOW = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))

# CLI exit codes, read by src-tauri/windows/hooks.nsh.
EXIT_INSTALLED, EXIT_FAILED, EXIT_PARATEXT_RUNNING, EXIT_CANCELLED, EXIT_NOT_NEEDED, EXIT_NO_PARATEXT = 0, 1, 2, 3, 4, 5


class ConnectorInstallError(RuntimeError):
    """The connector could not be installed; the message is for the user."""


def source_dir() -> Path:
    """The connector's C# source: beside the frozen engine (bridge-engine.spec
    ships it as data), else the repository's `paratext_plugin/`."""
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        return Path(frozen) / "paratext_plugin"
    return Path(__file__).resolve().parents[2] / "paratext_plugin"


def bundled_version(src: Path | None = None) -> str:
    text = (Path(src or source_dir()) / SOURCES[0]).read_text(encoding="utf-8-sig")
    match = _VERSION.search(text)
    return match.group(1) if match else ""


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split(".") if part.isdigit())


def _registry_values() -> dict[str, str]:
    """Paratext 9's own registration, {} when there is none or off Windows."""
    if os.name != "nt":
        return {}
    import winreg

    for key in PARATEXT_REGISTRY_KEYS:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
                values: dict[str, str] = {}
                index = 0
                while True:
                    try:
                        name, value, _kind = winreg.EnumValue(handle, index)
                    except OSError:
                        break
                    values[str(name)] = str(value)
                    index += 1
                if values:
                    return values
        except OSError:
            continue
    return {}


def find_paratext9(registry: Callable[[], dict[str, str]] = _registry_values) -> tuple[Path | None, str]:
    """(Paratext 9 folder, its version) or (None, ""). The folder must hold
    the interface DLLs the connector compiles against."""
    values = registry()
    candidates = [values.get("Paratext9_Full_Release_AppPath", ""), str(DEFAULT_PARATEXT_DIR)]
    for candidate in candidates:
        if candidate and all((Path(candidate) / dll).is_file() for dll in INTERFACE_DLLS):
            return Path(candidate), values.get("ParatextVersion", "")
    return None, ""


def find_compiler() -> Path | None:
    windir = Path(os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows")
    for framework in ("Framework64", "Framework"):
        csc = windir / "Microsoft.NET" / framework / "v4.0.30319" / "csc.exe"
        if csc.is_file():
            return csc
    return None


def paratext_running() -> bool:
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Paratext.exe", "/NH"], capture_output=True,
                             text=True, timeout=15, creationflags=_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "paratext.exe" in out.lower()


def plugin_folder(paratext_dir: Path) -> Path:
    return Path(paratext_dir) / "plugins" / PLUGIN_NAME


def installed_version(paratext_dir: Path) -> tuple[bool, str]:
    """(installed, version). The version file is written by this module; a
    connector deployed by hand with build.ps1 has none, so its compiled
    `PluginVersion` string (UTF-16 in the assembly's string heap) is read
    instead. "" when installed but unreadable."""
    folder = plugin_folder(paratext_dir)
    plugin = folder / f"{PLUGIN_NAME}.ptxplg"
    if not plugin.is_file():
        return False, ""
    try:
        stamped = (folder / VERSION_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        stamped = ""
    if stamped:
        return True, stamped
    try:
        data = plugin.read_bytes()
    except OSError:
        return True, ""
    # Not preceded by another UTF-16 digit: an ASCII "...319\0" just before the
    # string would otherwise read as a leading "9".
    found = re.findall(rb"(?<![0-9]\x00)((?:[0-9]\x00)+(?:\.\x00(?:[0-9]\x00)+){2,3})", data)
    versions = [raw.decode("utf-16-le") for raw in found]
    return True, max(versions, key=_version_key) if versions else ""


def status(*, registry: Callable[[], dict[str, str]] = _registry_values,
           running: Callable[[], bool] = paratext_running, src: Path | None = None) -> dict[str, Any]:
    """What Settings › Connections shows, and what the installer decides on.

    `action` is "install" (Paratext 9 found, no connector), "update" (an older
    connector), "none" (current) or "unavailable" (not Windows, no Paratext 9,
    no compiler, or no connector source in this build)."""
    bundled = ""
    try:
        bundled = bundled_version(src)
    except OSError:
        pass
    result: dict[str, Any] = {
        "paratextFound": False, "paratextDir": "", "paratextVersion": "", "running": False,
        "installed": False, "installedVersion": "", "bundledVersion": bundled,
        "compilerFound": False, "action": "unavailable", "message": "",
    }
    if os.name != "nt":
        result["message"] = "The Paratext connector is installed on Windows only."
        return result
    paratext_dir, paratext_version = find_paratext9(registry)
    if paratext_dir is None:
        result["message"] = "Paratext 9 was not found on this computer."
        return result
    installed, version = installed_version(paratext_dir)
    result.update(paratextFound=True, paratextDir=str(paratext_dir), paratextVersion=paratext_version,
                  running=bool(running()), installed=installed, installedVersion=version,
                  compilerFound=find_compiler() is not None)
    if not bundled:
        result["message"] = "This Bridge build does not carry the Paratext connector."
    elif not result["compilerFound"]:
        result["message"] = "The .NET Framework 4 C# compiler that Paratext 9 needs was not found."
    elif not installed:
        result.update(action="install", message="Paratext 9 is installed, but Bridge's connector is not.")
    elif not version or _version_key(version) < _version_key(bundled):
        result.update(action="update", message=f"An older Paratext connector is installed "
                                               f"({version or 'version unknown'}); this Bridge carries {bundled}.")
    else:
        result.update(action="none", message=f"The Paratext connector {version} is installed.")
    return result


def compile_connector(paratext_dir: Path, out_dir: Path, *, src: Path | None = None,
                      run: Callable[..., Any] = subprocess.run) -> Path:
    """Compile the connector as build.ps1 does. Returns the DLL."""
    csc = find_compiler()
    if csc is None:
        raise ConnectorInstallError("The .NET Framework 4 C# compiler was not found, so the connector cannot be built.")
    source = Path(src or source_dir())
    framework = csc.parent
    references = [str(Path(paratext_dir) / dll) for dll in INTERFACE_DLLS]
    references += ["System.Web.Extensions.dll", str(framework / "netstandard.dll")]
    out_dir.mkdir(parents=True, exist_ok=True)
    dll = out_dir / f"{PLUGIN_NAME}.dll"
    command = [str(csc), "/nologo", "/target:library", "/platform:anycpu", f"/out:{dll}",
               f"/reference:{','.join(references)}", *(str(source / name) for name in SOURCES)]
    completed = run(command, capture_output=True, text=True, timeout=180, creationflags=_NO_WINDOW)
    if completed.returncode != 0 or not dll.is_file():
        detail = (completed.stdout or completed.stderr or "").strip().splitlines()[-3:]
        raise ConnectorInstallError("The connector could not be built: " + (" ".join(detail) or "csc.exe failed."))
    return dll


def _install_script(dll: Path, folder: Path, version: str) -> str:
    def quote(value: Path | str) -> str:
        return "'" + str(value).replace("'", "''") + "'"
    target = folder / f"{PLUGIN_NAME}.ptxplg"
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        f"New-Item -ItemType Directory -Force -Path {quote(folder)} | Out-Null",
        f"Copy-Item -LiteralPath {quote(dll)} -Destination {quote(target)} -Force",
        f"Set-Content -LiteralPath {quote(folder / VERSION_FILE)} -Value {quote(version)} -Encoding ASCII",
        "",
    ])


def run_elevated(script: Path) -> int:
    """Run a PowerShell script with administrator rights (one UAC prompt) and
    wait for it. Returns its exit code; raises ConnectorInstallError when the
    user declines the prompt."""
    if os.name != "nt":
        raise ConnectorInstallError("Installing the Paratext connector needs Windows.")

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("fMask", ctypes.c_ulong), ("hwnd", ctypes.c_void_p),
                    ("lpVerb", ctypes.c_wchar_p), ("lpFile", ctypes.c_wchar_p), ("lpParameters", ctypes.c_wchar_p),
                    ("lpDirectory", ctypes.c_wchar_p), ("nShow", ctypes.c_int), ("hInstApp", ctypes.c_void_p),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", ctypes.c_wchar_p), ("hkeyClass", ctypes.c_void_p),
                    ("dwHotKey", ctypes.c_ulong), ("hIconOrMonitor", ctypes.c_void_p), ("hProcess", ctypes.c_void_p)]

    see_mask_nocloseprocess, sw_hide, error_cancelled = 0x40, 0, 1223
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = see_mask_nocloseprocess
    info.lpVerb = "runas"
    info.lpFile = "powershell.exe"
    info.lpParameters = f'-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{script}"'
    info.nShow = sw_hide
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        if ctypes.GetLastError() == error_cancelled:
            raise ConnectorInstallError("The Windows administrator prompt was declined, so nothing was installed.")
        raise ConnectorInstallError(f"Windows could not start the installer step (error {ctypes.GetLastError()}).")
    kernel32 = ctypes.windll.kernel32
    kernel32.WaitForSingleObject(ctypes.c_void_p(info.hProcess), 0xFFFFFFFF)
    code = ctypes.c_ulong(0)
    kernel32.GetExitCodeProcess(ctypes.c_void_p(info.hProcess), ctypes.byref(code))
    kernel32.CloseHandle(ctypes.c_void_p(info.hProcess))
    return int(code.value)


def install(*, registry: Callable[[], dict[str, str]] = _registry_values, running: Callable[[], bool] = paratext_running,
            compile_step: Callable[..., Path] = compile_connector, elevate: Callable[[Path], int] = run_elevated,
            src: Path | None = None) -> dict[str, Any]:
    """Compile and install (or update) the connector. Returns the new status
    with `installedNow`; raises ConnectorInstallError with a message for the
    user. Refuses while Paratext is running: a loaded plugin is never
    overwritten in place (build.ps1's rule)."""
    before = status(registry=registry, running=running, src=src)
    if before["action"] == "unavailable":
        raise ConnectorInstallError(before["message"])
    if before["running"]:
        raise ConnectorInstallError("Close Paratext first: the connector cannot be installed while Paratext is running.")
    paratext_dir = Path(before["paratextDir"])
    work = Path(tempfile.mkdtemp(prefix="bridge-paratext-connector-"))
    try:
        dll = compile_step(paratext_dir, work / "build", src=src)
        script = work / "install-connector.ps1"
        script.write_text(_install_script(dll, plugin_folder(paratext_dir), before["bundledVersion"]),
                          encoding="utf-8-sig")
        code = elevate(script)
        if code != 0:
            raise ConnectorInstallError(f"Copying the connector into Paratext's plugins folder failed (exit code {code}).")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    after = status(registry=registry, running=running, src=src)
    if not after["installed"] or after["action"] != "none":
        raise ConnectorInstallError("The connector was copied, but Bridge cannot see it in Paratext's plugins folder.")
    return {**after, "installedNow": True,
            "message": f"The Paratext connector {after['installedVersion']} is installed. Start Paratext, then turn on "
                       "Paratext navigation in Settings › Connections."}


def cli(out: Callable[[str], Any] = print) -> int:
    """`bridge-engine --install-paratext-connector`, for the installer's hook.
    Exit codes: see EXIT_*."""
    try:
        current = status()
        if current["action"] == "unavailable":
            out(current["message"])
            return EXIT_NO_PARATEXT if not current["paratextFound"] else EXIT_FAILED
        if current["action"] == "none":
            out(current["message"])
            return EXIT_NOT_NEEDED
        if current["running"]:
            out("Close Paratext first: the connector cannot be installed while Paratext is running.")
            return EXIT_PARATEXT_RUNNING
        out(install()["message"])
        return EXIT_INSTALLED
    except ConnectorInstallError as exc:
        out(str(exc))
        return EXIT_CANCELLED if "declined" in str(exc) else EXIT_FAILED


class ConnectorInstaller:
    """One install at a time, on a worker thread, so the engine's dispatcher is
    never held while the user reads the Windows admin prompt (#241's lesson).
    `start()` returns at once; `snapshot()` is the status plus the install's
    own state: "idle", "running", "succeeded" or "failed", with its message."""

    def __init__(self, install_fn: Callable[[], dict[str, Any]] = install,
                 status_fn: Callable[[], dict[str, Any]] = status) -> None:
        import threading

        self._install_fn = install_fn
        self._status_fn = status_fn
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._job: dict[str, Any] = {"state": "idle", "message": ""}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            job = dict(self._job)
        return {**self._status_fn(), "install": job}

    def start(self) -> dict[str, Any]:
        import threading

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return {"install": dict(self._job)}
            self._job = {"state": "running", "message": "Building the connector and waiting for Windows' "
                                                        "administrator prompt."}
            self._thread = threading.Thread(target=self._run, name="paratext-connector-install", daemon=True)
            self._thread.start()
            return {"install": dict(self._job)}

    def _run(self) -> None:
        try:
            result = self._install_fn()
            job = {"state": "succeeded", "message": str(result.get("message") or "")}
        except ConnectorInstallError as exc:
            job = {"state": "failed", "message": str(exc)}
        except Exception as exc:  # noqa: BLE001 -- reported to the user, never raised into the engine
            job = {"state": "failed", "message": f"The connector could not be installed: {exc}"}
        with self._lock:
            self._job = job
