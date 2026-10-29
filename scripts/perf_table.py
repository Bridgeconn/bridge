"""The p95 responsiveness table from Bridge's diagnostics log (#232).

The frontend records every Tier A and B action (src/lib/perf.ts) as one
line in the Rust shell's engine-events.log:

    <ts_ms> [info] perf action=chapter.open tier=B responded=12.4 complete=180.2 detail=12

This script reads that log, keeps the lines after --since (an ISO time or a
millisecond epoch; default: everything), and prints the table the release
notes carry: action, tier, sample count, responded and complete p95, the
tier's budget and the result. The percentile is the same nearest-rank one
as benchmark_language_qa.py and perf.ts, so the in-app table and this one
agree to the sample.

The frontend also writes one line per task over 250 ms (NFR-PERF-005's
"any frame over 250 ms", #260):

    <ts_ms> [info] perf longtask=312.5

Those are summarised under the table (count, longest, total) and carried
as "longTasks" in --json; they never enter the action rows.

    python scripts/perf_table.py                       # the installed app's log
    python scripts/perf_table.py --log path/to/engine-events.log --since 2026-10-15T09:00
    python scripts/perf_table.py --hardware "Field laptop, i3-1115G4 (2 cores), 8 GB, 1366x768" --json

Exit status is 0 unless --gate is given, in which case it is 1 when any
action with at least --min-samples samples misses its budget.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

APP_IDENTIFIER = "org.translationcore.aibridge"

# Mirrors PERF_ACTIONS / TIER_BUDGETS in src/lib/perf.ts. A test pins the two
# against each other.
ACTIONS: dict[str, tuple[str, str]] = {
    "verse.navigate": ("A", "Navigate to a verse"),
    "word.select": ("A", "Select a word"),
    "menu.open": ("A", "Open a menu"),
    "panel.toggle": ("A", "Toggle a side panel"),
    "decision.record": ("A", "Record a decision"),
    "alignment.drop": ("A", "Drop a word onto a source column"),
    "project.open": ("B", "Open a project"),
    "chapter.open": ("B", "Open a chapter"),
    "book.report": ("B", "Generate a book report"),
    "book.switch": ("B", "Switch books"),
}
BUDGETS = {"A": (100.0, 300.0), "B": (100.0, 2000.0)}

LINE = re.compile(
    r"^(?P<ts>\d+) \[(?P<level>\w+)\] perf action=(?P<action>\S+) tier=(?P<tier>[AB]) "
    r"responded=(?P<responded>[\d.]+) complete=(?P<complete>[\d.]+)(?: detail=(?P<detail>\S+))?\s*$"
)
# Mirrors formatLongTaskLine in src/lib/perf.ts.
LONG_TASK_LINE = re.compile(r"^(?P<ts>\d+) \[(?P<level>\w+)\] perf longtask=(?P<ms>[\d.]+)\s*$")
LONG_TASK_MS = 250.0


def default_log_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_IDENTIFIER / "logs" / "engine-events.log"


def parse_since(value: str | None) -> int:
    if not value:
        return 0
    if value.isdigit():
        return int(value)
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        stamp = stamp.astimezone()
    return int(stamp.astimezone(timezone.utc).timestamp() * 1000)


def parse_lines(lines, since_ms: int = 0) -> dict[str, list[tuple[float, float]]]:
    """action -> [(respondedMs, completeMs), ...] for every perf line at or after since_ms."""
    samples: dict[str, list[tuple[float, float]]] = {action: [] for action in ACTIONS}
    for line in lines:
        match = LINE.match(line.strip())
        if not match or int(match["ts"]) < since_ms:
            continue
        action = match["action"]
        if action not in samples:
            samples[action] = []
        samples[action].append((float(match["responded"]), float(match["complete"])))
    return samples


def parse_long_tasks(lines, since_ms: int = 0) -> list[float]:
    """Every `perf longtask=<ms>` duration at or after since_ms, in log order."""
    durations: list[float] = []
    for line in lines:
        match = LONG_TASK_LINE.match(line.strip())
        if match and int(match["ts"]) >= since_ms:
            durations.append(float(match["ms"]))
    return durations


def summarize_long_tasks(durations: list[float]) -> dict:
    return {
        "thresholdMs": LONG_TASK_MS,
        "count": len(durations),
        "longestMs": max(durations) if durations else None,
        "totalMs": round(sum(durations), 1) if durations else 0.0,
    }


def long_tasks_markdown(summary: dict) -> str:
    if not summary["count"]:
        return f"Long tasks over {int(summary['thresholdMs'])} ms: none recorded"
    return (
        f"Long tasks over {int(summary['thresholdMs'])} ms: {summary['count']} "
        f"(longest {_fmt(summary['longestMs'])} ms, {_fmt(summary['totalMs'])} ms in all)"
    )


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))]


def summarize(samples: dict[str, list[tuple[float, float]]], min_samples: int = 20) -> list[dict]:
    rows = []
    for action, (tier, label) in ACTIONS.items():
        own = samples.get(action, [])
        responded = [r for r, _ in own]
        complete = [c for _, c in own]
        budget_r, budget_c = BUDGETS[tier]
        row = {
            "action": action, "tier": tier, "label": label, "samples": len(own),
            "respondedP50": percentile(responded, .5) if own else None,
            "respondedP95": percentile(responded, .95) if own else None,
            "completeP50": percentile(complete, .5) if own else None,
            "completeP95": percentile(complete, .95) if own else None,
            "completeMax": max(complete) if own else None,
            "budgetRespondedMs": budget_r, "budgetCompleteMs": budget_c,
        }
        if not own:
            row["result"] = "not measured"
        elif len(own) < min_samples:
            row["result"] = f"only {len(own)} samples"
        else:
            row["result"] = "pass" if (row["respondedP95"] <= budget_r and row["completeP95"] <= budget_c) else "FAIL"
        rows.append(row)
    return rows


def markdown(rows: list[dict], hardware: str = "") -> str:
    out = []
    if hardware:
        out.append(f"Hardware: {hardware}")
        out.append("")
    out.append("| Action | Tier | n | Responded p95 (ms) | Complete p95 (ms) | Budget (ms) | Result |")
    out.append("|---|---|---:|---:|---:|---|---|")
    for row in rows:
        r95 = "-" if row["respondedP95"] is None else _fmt(row["respondedP95"])
        c95 = "-" if row["completeP95"] is None else _fmt(row["completeP95"])
        out.append(
            f"| {row['label']} (`{row['action']}`) | {row['tier']} | {row['samples']} | {r95} | {c95} | "
            f"{int(row['budgetRespondedMs'])} / {int(row['budgetCompleteMs'])} | {row['result']} |"
        )
    return "\n".join(out)


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log", type=Path, default=default_log_path(), help="engine-events.log to read")
    parser.add_argument("--since", help="ISO time or millisecond epoch; earlier lines are ignored")
    parser.add_argument("--hardware", default="", help="the machine, printed above the table")
    parser.add_argument("--min-samples", type=int, default=20)
    parser.add_argument("--json", action="store_true", help="print the rows as JSON instead of markdown")
    parser.add_argument("--gate", action="store_true", help="exit 1 when a fully sampled action misses its budget")
    args = parser.parse_args(argv)
    if not args.log.is_file():
        print(f"No log at {args.log}", file=sys.stderr)
        return 2
    since_ms = parse_since(args.since)
    with args.log.open(encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    samples = parse_lines(lines, since_ms)
    long_tasks = summarize_long_tasks(parse_long_tasks(lines, since_ms))
    rows = summarize(samples, args.min_samples)
    if args.json:
        print(json.dumps({"log": str(args.log), "hardware": args.hardware, "rows": rows, "longTasks": long_tasks}, indent=2))
    else:
        print(markdown(rows, args.hardware))
        print()
        print(long_tasks_markdown(long_tasks))
    if args.gate and any(row["result"] == "FAIL" for row in rows):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
