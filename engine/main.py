"""
Entrypoint for the Bridge sidecar process.

Bundled via PyInstaller into a standalone executable (no Python runtime
required on the translator's machine). Tauri spawns this once at app
startup and keeps it alive for the whole session (doc §4).

    pyinstaller --onefile --name bridge-engine main.py
"""
import os
import sys

from greek_room_engine.transport.stdio_transport import run_stdio_loop, send_stage


def _apply_cli_overrides() -> None:
    """Tauri's sidecar spawner (src-tauri/src/sidecar.rs) passes
    --resources-dir pointing at the bundled tN/tW/tA/UHB/UGNT resources
    Tauri installs via bundle.resources. tc_ai_bridge's bundled_resources_
    source()/bundled_resources_root() functions check this env var before
    falling back to sys._MEIPASS or the source-tree layout — see their own
    docstrings for why this ~45MB payload moved out of bridge-engine.spec's
    onefile archive. Reading argv directly rather than pulling in argparse
    for one optional flag."""
    args = sys.argv[1:]
    # --language-packs-dir: the Language QA packs (engine/language_packs),
    # shipped the same way and for the same reason (docs/LANGUAGE_QA_PACKS.md).
    for flag, variable in (("--resources-dir", "BRIDGE_BUNDLED_RESOURCES_DIR"),
                           ("--language-packs-dir", "BRIDGE_LANGUAGE_PACKS_DIR")):
        if flag in args:
            index = args.index(flag)
            if index + 1 < len(args):
                os.environ[variable] = args[index + 1]


def _serve_args(argv: list[str]) -> dict[str, object] | None:
    """`--serve [--data-dir <dir>] [--host <h>] [--port <n>]` (#79): the team
    hub. None when --serve is absent, which is every desktop launch."""
    if "--serve" not in argv:
        return None

    def value(flag: str, default: str) -> str:
        if flag in argv:
            index = argv.index(flag)
            if index + 1 < len(argv):
                return argv[index + 1]
        return default

    return {
        "data_dir": value("--data-dir", ""),
        "host": value("--host", "127.0.0.1"),
        "port": int(value("--port", "8765")),
    }


def _install_paratext_connector() -> int:
    """`bridge-engine --install-paratext-connector` (#282): Bridge's installer
    runs this from its post-install hook (src-tauri/windows/hooks.nsh) after the
    user agrees. It compiles and installs the Paratext connector, then exits;
    it never starts the engine."""
    from tc_ai_bridge.paratext_install import cli

    return cli()


def _start() -> None:
    """Boot in named stages so the shell's loading screen can say what is
    slow (#233). Each stage line goes out *before* the work it names:
    importing bridge_service pulls in tc_ai_bridge and the Greek Room
    adapters (the bulk of a cold start after the onefile unpack),
    BridgeEngine() opens the workspace, and run_stdio_loop sends the ready
    line. That is why the import sits here rather than at the top of the
    module: at the top it would run before anything could be reported, and
    `import main` from a test would pay for it and print to stdout."""
    _apply_cli_overrides()
    serve = _serve_args(sys.argv[1:])
    if serve is not None:
        # The hub: an optional [server] extra, imported only here, so the
        # stdio sidecar never carries it (DECISIONS 2026-09-11, 2026-10-15).
        from bridge_server import serve as run_server

        run_server(**serve)  # type: ignore[arg-type]
        return
    send_stage("modules", "Loading engine modules")
    from bridge_service import BridgeEngine

    send_stage("engine", "Starting the engine")
    engine = BridgeEngine()
    run_stdio_loop(engine, on_ready=engine.start_background_warmup)


if __name__ == "__main__":
    if "--install-paratext-connector" in sys.argv[1:]:
        raise SystemExit(_install_paratext_connector())
    _start()
