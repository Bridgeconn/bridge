"""scripts/perf_table.py (#232): the p95 table from the diagnostics log.

Pins the line format the frontend writes (src/lib/perf.ts formatPerfLine),
the action and budget tables against the TypeScript ones, and the
nearest-rank percentile shared with benchmark_language_qa.py.
"""
from __future__ import annotations

import re

import perf_table
from tests.support.paths import REPO_ROOT

LINES = [
    "1760400000000 [info] Engine ready",
    *[f"17604000{i:05d} [info] perf action=verse.navigate tier=A responded={10 + i} complete={20 + i} detail=1:{i}" for i in range(20)],
    *[f"17604001{i:05d} [info] perf action=book.report tier=B responded=50 complete={1900 + i * 20}" for i in range(20)],
    "1760400200000 [info] perf action=chapter.open tier=B responded=40 complete=400 detail=3",
    "1760400200001 [warn] perf action=garbage",
]


def test_parses_only_perf_lines_and_respects_since():
    samples = perf_table.parse_lines(LINES)
    assert len(samples["verse.navigate"]) == 20
    assert samples["verse.navigate"][0] == (10.0, 20.0)
    assert len(samples["book.report"]) == 20
    assert samples["chapter.open"] == [(40.0, 400.0)]
    assert samples["word.select"] == []
    later = perf_table.parse_lines(LINES, since_ms=1760400100000)
    assert later["verse.navigate"] == [] and len(later["book.report"]) == 20


def test_summary_judges_p95_against_the_tier_budget_and_marks_short_rows():
    rows = {row["action"]: row for row in perf_table.summarize(perf_table.parse_lines(LINES))}
    assert rows["verse.navigate"]["respondedP95"] == 28 and rows["verse.navigate"]["completeP95"] == 38
    assert rows["verse.navigate"]["result"] == "pass"
    assert rows["book.report"]["completeP95"] == 2260 and rows["book.report"]["result"] == "FAIL"
    assert rows["chapter.open"]["result"] == "only 1 samples"
    assert rows["word.select"]["result"] == "not measured" and rows["word.select"]["respondedP95"] is None


def test_markdown_table_carries_hardware_budget_and_result():
    table = perf_table.markdown(perf_table.summarize(perf_table.parse_lines(LINES)), "Field laptop, 1366x768")
    assert table.splitlines()[0] == "Hardware: Field laptop, 1366x768"
    assert "| Navigate to a verse (`verse.navigate`) | A | 20 | 28 | 38 | 100 / 300 | pass |" in table
    assert "| Generate a book report (`book.report`) | B | 20 | 50 | 2260 | 100 / 2000 | FAIL |" in table
    assert "| Select a word (`word.select`) | A | 0 | - | - | 100 / 300 | not measured |" in table


def test_gate_and_json(tmp_path, capsys):
    log = tmp_path / "engine-events.log"
    log.write_text("\n".join(LINES), encoding="utf-8")
    assert perf_table.main(["--log", str(log), "--json"]) == 0
    assert '"action": "verse.navigate"' in capsys.readouterr().out
    assert perf_table.main(["--log", str(log), "--gate"]) == 1
    assert perf_table.main(["--log", str(tmp_path / "missing.log")]) == 2


def test_actions_and_budgets_match_the_frontend():
    source = (REPO_ROOT / "src" / "lib" / "perf.ts").read_text(encoding="utf-8")
    ts_actions = dict(re.findall(r'"([a-z]+\.[a-z]+)": \{ tier: "([AB])"', source))
    assert ts_actions == {action: tier for action, (tier, _) in perf_table.ACTIONS.items()}
    assert 'A: { respondedMs: 100, completeMs: 300 }' in source
    assert 'B: { respondedMs: 100, completeMs: 2000 }' in source
    assert perf_table.BUDGETS == {"A": (100.0, 300.0), "B": (100.0, 2000.0)}
    # The line the script parses is the one the frontend writes.
    assert 'perf action=${sample.action} tier=${sample.tier} responded=${sample.respondedMs} complete=${sample.completeMs}' in source
