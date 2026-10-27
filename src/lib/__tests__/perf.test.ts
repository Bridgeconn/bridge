import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

import {
  LONG_TASK_MS, PERF_ACTIONS, TIER_BUDGETS, formatLongTaskLine, formatPerfLine, longTasks, observeLongTasks,
  percentile, perfAbort, perfBegin, perfEnd, perfInFlight, perfResponded, perfSamples, perfSummary,
  perfTableMarkdown, registerPerfRunner, runPerfSample, setPerfSink, type PerfSample,
} from "../perf";

function sample(action: string, respondedMs: number, completeMs: number): PerfSample {
  return { action, tier: PERF_ACTIONS[action].tier, respondedMs, completeMs, at: 0, detail: "" };
}

beforeEach(() => {
  perfSamples.set([]);
  setPerfSink(null);
  registerPerfRunner(null);
});

describe("perf samples (#232)", () => {
  it("records a sample at the paint after the end, with responded defaulting to complete", async () => {
    const logged: PerfSample[] = [];
    setPerfSink((s) => logged.push(s));

    perfBegin("verse.navigate", "1:3");
    expect(perfInFlight("verse.navigate")).toBe(true);
    const recorded = await perfEnd("verse.navigate");

    expect(recorded).not.toBeNull();
    expect(recorded?.action).toBe("verse.navigate");
    expect(recorded?.tier).toBe("A");
    expect(recorded?.detail).toBe("1:3");
    expect(recorded?.completeMs).toBeGreaterThanOrEqual(0);
    expect(recorded?.respondedMs).toBe(recorded?.completeMs);
    expect(get(perfSamples)).toEqual([recorded]);
    expect(logged).toEqual([recorded]);
    expect(perfInFlight("verse.navigate")).toBe(false);
  });

  it("measures responded separately when the first visible change came before the end", async () => {
    perfBegin("chapter.open", "2");
    perfResponded("chapter.open");
    await new Promise((resolve) => setTimeout(resolve, 30));
    const recorded = await perfEnd("chapter.open");

    expect(recorded?.respondedMs).toBeLessThanOrEqual(recorded!.completeMs);
    expect(recorded?.completeMs).toBeGreaterThanOrEqual(25);
  });

  it("ignores unknown actions, ends nothing twice, and drops an aborted action", async () => {
    perfBegin("not.an.action");
    expect(perfInFlight("not.an.action")).toBe(false);
    expect(await perfEnd("not.an.action")).toBeNull();

    perfBegin("book.switch");
    perfAbort("book.switch");
    expect(await perfEnd("book.switch")).toBeNull();
    expect(get(perfSamples)).toEqual([]);
  });

  it("a sink that throws never loses the sample", async () => {
    setPerfSink(() => { throw new Error("log down"); });
    perfBegin("panel.toggle");
    await perfEnd("panel.toggle");
    expect(get(perfSamples)).toHaveLength(1);
  });

  it("formats the diagnostics line the table script parses", () => {
    expect(formatPerfLine({ ...sample("menu.open", 12.3, 12.3), detail: "finding menu" }))
      .toBe("perf action=menu.open tier=A responded=12.3 complete=12.3 detail=finding_menu");
    expect(formatPerfLine(sample("book.report", 8, 1500))).toBe("perf action=book.report tier=B responded=8 complete=1500");
  });
});

describe("perf summary and table", () => {
  it("uses the same nearest-rank percentile as the Python scripts", () => {
    // 20 samples 1..20: Python's round(0.95 * 19) = round(18.05) = 18 -> 19.
    const twenty = Array.from({ length: 20 }, (_, i) => i + 1);
    expect(percentile(twenty, 0.95)).toBe(19);
    expect(percentile(twenty, 0.5)).toBe(11); // round(9.5) is 10 (half to even) -> 11
    expect(percentile([7], 0.95)).toBe(7);
    expect(percentile([], 0.95)).toBe(0);
  });

  it("judges each action's p95 against its tier's budget and lists unmeasured ones", () => {
    const samples = [
      ...Array.from({ length: 20 }, (_, i) => sample("verse.navigate", 10 + i, 20 + i)),
      ...Array.from({ length: 20 }, (_, i) => sample("book.report", 50, 1900 + i * 20)),
    ];
    const rows = perfSummary(samples);
    const navigate = rows.find((r) => r.action === "verse.navigate")!;
    expect(navigate.samples).toBe(20);
    expect(navigate.respondedP95).toBe(28);
    expect(navigate.completeP95).toBe(38);
    expect(navigate.pass).toBe(true);
    const report = rows.find((r) => r.action === "book.report")!;
    expect(report.completeP95).toBe(2260);
    expect(report.pass).toBe(false);
    expect(rows.find((r) => r.action === "word.select")!.pass).toBeNull();
    expect(rows).toHaveLength(Object.keys(PERF_ACTIONS).length);
  });

  it("prints the release-notes table with hardware, budgets and results", () => {
    const rows = perfSummary([
      ...Array.from({ length: 20 }, () => sample("verse.navigate", 10, 20)),
      ...Array.from({ length: 5 }, () => sample("chapter.open", 40, 400)),
    ]);
    const table = perfTableMarkdown(rows, "Field laptop, i3-1115G4, 8 GB, SATA SSD, 1366x768");
    expect(table).toContain("Hardware: Field laptop");
    expect(table).toContain("| Navigate to a verse (`verse.navigate`) | A | 20 | 10 | 20 | 100 / 300 | pass |");
    expect(table).toContain("| Open a chapter (`chapter.open`) | B | 5 | 40 | 400 | 100 / 2000 | only 5 samples |");
    expect(table).toContain("| Select a word (`word.select`) | A | 0 | - | - | 100 / 300 | not measured |");
    expect(TIER_BUDGETS.B.completeMs).toBe(2000);
  });
});

describe("the in-app runner", () => {
  it("repeats each registered action and reports progress, then summarises", async () => {
    const calls = { navigate: 0, chapter: 0, panel: 0 };
    registerPerfRunner({
      navigateVerse: async () => { calls.navigate += 1; perfBegin("verse.navigate"); await perfEnd("verse.navigate"); },
      openChapter: async () => { calls.chapter += 1; perfBegin("chapter.open"); await perfEnd("chapter.open"); },
      togglePanel: async () => { calls.panel += 1; perfBegin("panel.toggle"); await perfEnd("panel.toggle"); },
      switchBook: null,
      openReport: null,
    });
    const progress: number[] = [];

    const rows = await runPerfSample(3, (p) => progress.push(p.done), 0);

    expect(calls).toEqual({ navigate: 3, chapter: 3, panel: 3 });
    expect(progress[0]).toBe(0);
    expect(progress[progress.length - 1]).toBe(9);
    expect(rows.find((r) => r.action === "verse.navigate")?.samples).toBe(3);
    expect(rows.find((r) => r.action === "book.switch")?.samples).toBe(0);
  });

  it("refuses to run without a registered runner", async () => {
    await expect(runPerfSample(1)).rejects.toThrow(/open project/);
  });
});

describe("long tasks (#260)", () => {
  const realObserver = (globalThis as { PerformanceObserver?: unknown }).PerformanceObserver;

  /** A PerformanceObserver double that exposes the longtask type and hands
   *  the test the callback, so entries can be fed by hand. */
  function fakeObserver(entryTypes: string[]) {
    let callback: ((list: { getEntries: () => Array<{ duration: number }> }) => void) | null = null;
    const observed: unknown[] = [];
    const disconnect = vi.fn();
    class Fake {
      static supportedEntryTypes = entryTypes;
      constructor(cb: typeof callback) { callback = cb; }
      observe(options: unknown) { observed.push(options); }
      disconnect() { disconnect(); }
    }
    (globalThis as { PerformanceObserver?: unknown }).PerformanceObserver = Fake;
    return {
      feed: (durations: number[]) => callback?.({ getEntries: () => durations.map((duration) => ({ duration })) }),
      observed, disconnect,
    };
  }

  beforeEach(() => {
    longTasks.set({ supported: false, count: 0, longestMs: 0, totalMs: 0 });
  });

  afterEach(() => {
    (globalThis as { PerformanceObserver?: unknown }).PerformanceObserver = realObserver;
  });

  it("counts every task over the threshold and writes one perf longtask= line each through the sink", () => {
    const fake = fakeObserver(["longtask", "mark"]);
    const lines: string[] = [];
    const stop = observeLongTasks((line) => lines.push(line));

    expect(get(longTasks).supported).toBe(true);
    expect(fake.observed).toEqual([{ type: "longtask", buffered: true }]);
    fake.feed([312.46, 100, LONG_TASK_MS, 249.9]);

    expect(lines).toEqual(["perf longtask=312.5", `perf longtask=${LONG_TASK_MS}`]);
    expect(get(longTasks)).toEqual({ supported: true, count: 2, longestMs: 312.5, totalMs: 562.5 });
    expect(formatLongTaskLine(1000)).toBe("perf longtask=1000");

    stop();
    expect(fake.disconnect).toHaveBeenCalledOnce();
    expect(get(longTasks).supported).toBe(false);
  });

  it("registers nothing where the WebView has no PerformanceObserver or no longtask type", () => {
    (globalThis as { PerformanceObserver?: unknown }).PerformanceObserver = undefined;
    const lines: string[] = [];
    expect(() => observeLongTasks((line) => lines.push(line))()).not.toThrow();
    expect(get(longTasks).supported).toBe(false);

    const fake = fakeObserver(["mark", "measure"]);
    observeLongTasks((line) => lines.push(line));
    expect(fake.observed).toEqual([]);
    expect(get(longTasks).supported).toBe(false);
    expect(lines).toEqual([]);
  });

  it("a throwing log never stops the count", () => {
    const fake = fakeObserver(["longtask"]);
    observeLongTasks(() => { throw new Error("log closed"); });
    expect(() => fake.feed([400])).not.toThrow();
    expect(get(longTasks).count).toBe(1);
  });
});
