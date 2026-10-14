"""check_timing: the accumulator the check jobs and Language QA passes report
their per-engine wall clock through (2026-10-08). Pure; no dispatcher."""
from __future__ import annotations

import threading

from tc_ai_bridge import check_timing


def test_step_accumulates_ms_and_calls_slowest_first():
    timings = check_timing.Timings()
    timings.add("fast", 0.001)
    timings.add("slow", 0.020)
    timings.add("fast", 0.002)
    result = timings.as_dict()
    assert list(result) == ["slow", "fast"]
    assert result["fast"] == {"ms": 3.0, "calls": 2}
    assert result["slow"]["calls"] == 1
    with timings.step("stepped"):
        pass
    assert timings.as_dict()["stepped"]["calls"] == 1
    assert timings.summary().startswith("total=")


def test_current_is_the_activated_timings_on_this_thread_only():
    assert check_timing.current() is check_timing.NULL
    mine = check_timing.Timings()
    seen_on_other_thread: list[object] = []

    def other() -> None:
        seen_on_other_thread.append(check_timing.current())

    with check_timing.activate(mine):
        assert check_timing.current() is mine
        with check_timing.current().step("inner"):
            pass
        thread = threading.Thread(target=other)
        thread.start()
        thread.join()
    assert check_timing.current() is check_timing.NULL
    assert seen_on_other_thread == [check_timing.NULL]
    assert mine.as_dict()["inner"]["calls"] == 1


def test_null_timings_records_nothing():
    with check_timing.NULL.step("ignored"):
        pass
    check_timing.NULL.cached("ignored")
    assert check_timing.NULL.as_dict() == {}


def test_a_reused_step_reports_cached_beside_its_runs():
    """#271: a step served from a cache shows `cached`, with no time and no call;
    a step never reused carries no `cached` key at all."""
    timings = check_timing.Timings()
    timings.add("ran", 0.004)
    timings.cached("reused")
    timings.add("both", 0.002)
    timings.cached("both", 3)
    result = timings.as_dict()
    assert result["ran"] == {"ms": 4.0, "calls": 1}
    assert result["reused"] == {"ms": 0.0, "calls": 0, "cached": 1}
    assert result["both"] == {"ms": 2.0, "calls": 1, "cached": 3}
    merged = check_timing.Timings()
    merged.cached("both")
    merged.merge(timings)
    assert merged.as_dict()["both"] == {"ms": 2.0, "calls": 1, "cached": 4}
