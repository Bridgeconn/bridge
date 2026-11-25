"""Runs one tool of the bundled proofreading toolkit (#505).

`bridge-engine --proofread-tool <tool> [args...]` from the frozen exe, or
`python proofread_tool_main.py <tool> [args...]` from source. The toolkit
(`engine/proofreading_toolkit/`, Benz's `bible-qa-universal`) is a set of
command-line scripts that work at module level on `sys.argv` and leave with
`sys.exit`, so each call is its own short-lived process: the long-lived engine
owns the JSON-lines pipe, and a tool's prints, its crash or its `sys.exit` must
never reach it. Same boundary, for the same reason, as `usfm_checker_main.py`.

What this adds to the scripts as written, and nothing else:

- stdout and stderr are UTF-8. The tools print verse text, and on Windows the
  default console encoding cannot hold it (CLAUDE.md gotcha 5): `sweep.py` on a
  Malayalam book died on its first hit, seen 2026-11-25.
- only a tool named in `TOOLS` runs, from the bundled folder. The argument is
  never used as a path.

The tools read USFM with their own parser. That is the exception to gotcha 14
recorded in docs/DECISIONS.md (2026-11-25): they only ever see staged copies
that `tc_ai_bridge.proofreading` writes, never Bridge's stored text.
"""
from __future__ import annotations

import runpy
import sys
import traceback
from pathlib import Path

TOOLKIT_VERSION = "bible-qa-universal-2026-11"

# Every script in the toolkit's tools/ folder except the two shared modules
# (`project`, `corpus`), which are imported by the others and are not commands.
TOOLS: tuple[str, ...] = (
    "approve_candidates", "build", "cost", "deliver", "detect_language", "dump", "make_profile",
    "merge_notes", "nearby", "numchk", "q", "queue", "report", "sweep", "terms",
)


def toolkit_root() -> Path:
    """The toolkit folder in source and PyInstaller modes."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "proofreading_toolkit"
    return Path(__file__).resolve().parent / "proofreading_toolkit"


def _utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    _utf8_streams()
    # `build.py` loads a book's findings file through the import machinery,
    # which would leave a compiled copy beside it and trust that copy while
    # the file's size and modification second are unchanged. A findings file
    # rewritten within the same second to the same length was then ignored and
    # the old findings were verified instead (seen 2026-11-25). No tool run
    # writes bytecode; `write_rows_file` also clears any that is already there.
    sys.dont_write_bytecode = True
    if args == ["--version"]:
        print(f"bridge-proofread-tool {TOOLKIT_VERSION}")
        return 0
    if not args or args[0] not in TOOLS:
        print(f"Unknown proofreading tool. Expected one of: {', '.join(TOOLS)}", file=sys.stderr)
        return 2
    tools_dir = toolkit_root() / "tools"
    script = tools_dir / f"{args[0]}.py"
    if not script.is_file():
        print(f"Proofreading toolkit payload is missing: {script}", file=sys.stderr)
        return 2

    # The tools import each other by bare name (`import project as P`), so
    # their folder must be first.
    sys.path.insert(0, str(tools_dir))
    old_argv = sys.argv
    try:
        sys.argv = [str(script), *args[1:]]
        runpy.run_path(str(script), run_name="__main__")
        return 0
    except SystemExit as exc:
        if exc.code is None:
            return 0
        if isinstance(exc.code, int):
            return exc.code
        # `sys.exit("message")`: the tools' way of saying why they stopped.
        print(str(exc.code), file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - a worker must return a useful exit code
        traceback.print_exc(file=sys.stderr)
        return 2
    finally:
        sys.argv = old_argv
        sys.stdout.flush()
        sys.stderr.flush()


if __name__ == "__main__":
    raise SystemExit(main())
