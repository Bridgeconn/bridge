/** Click-to-paint timing for the Tier A and B actions (#232, requirement 1).
 *
 *  An action is bracketed by `perfBegin(action)` at the click and
 *  `perfEnd(action)` once its last store update is in; `perfResponded(action)`
 *  marks the point at which the first visible change was pushed (a label, a
 *  spinner, the new chapter number). Both "responded" and "complete" are
 *  measured at the paint after that point (two animation frames), which is
 *  what the requirement means by "visible response within 100 ms" and
 *  "complete within 300 ms / 2 s". One action of each name is in flight at a
 *  time; a new `perfBegin` of the same name replaces a stale one.
 *
 *  Every finished sample goes to `perfSamples` (a bounded store, for the
 *  diagnostics panel's table and the in-app runner) and to the sink App.svelte
 *  installs, which writes one `perf action=... responded=... complete=...`
 *  line into the diagnostics log through the Rust shell, so
 *  `scripts/perf_table.py` can print the p95 table from
 *  `engine-events.log` after a measurement session on the field machine.
 *
 *  `performance.mark`/`measure` are also written, for the DevTools timeline
 *  on a dev build. Nothing here touches the engine.
 */
import { writable, type Writable } from "svelte/store";

export type PerfTier = "A" | "B";

/** The actions requirement 1 names, with the tier each belongs to. "word.select"
 *  is marked in VerseList.svelte: begun at the mousedown in a verse's text,
 *  ended at the mouseup that leaves a word under the pointer or a selection
 *  inside the verse, or at the verse menu that names a word (#260). */
export const PERF_ACTIONS: Record<string, { tier: PerfTier; label: string }> = {
  "verse.navigate": { tier: "A", label: "Navigate to a verse" },
  "word.select": { tier: "A", label: "Select a word" },
  "menu.open": { tier: "A", label: "Open a menu" },
  "panel.toggle": { tier: "A", label: "Toggle a side panel" },
  "decision.record": { tier: "A", label: "Record a decision" },
  "project.open": { tier: "B", label: "Open a project" },
  "chapter.open": { tier: "B", label: "Open a chapter" },
  "book.report": { tier: "B", label: "Generate a book report" },
  "book.switch": { tier: "B", label: "Switch books" },
};

/** Requirement 1's budgets, in milliseconds, at p95. */
export const TIER_BUDGETS: Record<PerfTier, { respondedMs: number; completeMs: number }> = {
  A: { respondedMs: 100, completeMs: 300 },
  B: { respondedMs: 100, completeMs: 2000 },
};

export interface PerfSample {
  action: string;
  tier: PerfTier;
  /** Click to the paint after the first visible change; equals `completeMs`
   *  when the action had no separate response step. */
  respondedMs: number;
  /** Click to the paint after the action's last store update. */
  completeMs: number;
  /** `Date.now()` when the sample was recorded. */
  at: number;
  detail: string;
}

interface Pending {
  action: string;
  detail: string;
  id: number;
  start: number;
  responded: number | null;
  respondedRequested: boolean;
}

export const PERF_SAMPLE_CAP = 2000;

export const perfSamples: Writable<PerfSample[]> = writable([]);

let sequence = 0;
const pending = new Map<string, Pending>();
let sink: ((sample: PerfSample) => void) | null = null;

/** Where finished samples go besides the store: App.svelte sends them to the
 *  diagnostics log. */
export function setPerfSink(fn: ((sample: PerfSample) => void) | null): void {
  sink = fn;
}

function now(): number {
  return typeof performance !== "undefined" && typeof performance.now === "function" ? performance.now() : Date.now();
}

function mark(name: string): void {
  try { performance.mark(name); } catch { /* not every runtime has the timeline */ }
}

function measure(name: string, startMark: string): void {
  try { performance.measure(name, startMark); } catch { /* as above */ }
}

/** Resolves with the time after the next paint: two animation frames, the
 *  first of which may still be the one the click landed in. Falls back to a
 *  macrotask where there is no frame scheduler (tests, a hidden window). */
export function afterPaint(): Promise<number> {
  const raf: (cb: () => void) => void =
    typeof requestAnimationFrame === "function" ? (cb) => requestAnimationFrame(() => cb()) : (cb) => { setTimeout(cb, 0); };
  return new Promise((resolve) => raf(() => raf(() => resolve(now()))));
}

export function perfInFlight(action: string): boolean {
  return pending.has(action);
}

export function perfBegin(action: string, detail = ""): void {
  if (!(action in PERF_ACTIONS)) return;
  const id = ++sequence;
  pending.set(action, { action, detail, id, start: now(), responded: null, respondedRequested: false });
  mark(`bridge.${action}.start#${id}`);
}

/** The first visible change for `action` was just pushed: measure the paint
 *  after it. Safe to call more than once; only the first counts. */
export function perfResponded(action: string): void {
  const entry = pending.get(action);
  if (!entry || entry.respondedRequested) return;
  entry.respondedRequested = true;
  void afterPaint().then((t) => {
    if (entry.responded === null) {
      entry.responded = t - entry.start;
      measure(`bridge.${action}.responded#${entry.id}`, `bridge.${action}.start#${entry.id}`);
    }
  });
}

/** Drop the in-flight `action` without a sample (it failed or was superseded). */
export function perfAbort(action: string): void {
  pending.delete(action);
}

/** The action's last store update is in: measure the paint after it and
 *  record the sample. Resolves with the sample, or null when nothing was in
 *  flight. */
export function perfEnd(action: string): Promise<PerfSample | null> {
  const entry = pending.get(action);
  if (!entry) return Promise.resolve(null);
  pending.delete(action);
  return afterPaint().then((t) => {
    const completeMs = t - entry.start;
    measure(`bridge.${action}.complete#${entry.id}`, `bridge.${action}.start#${entry.id}`);
    const sample: PerfSample = {
      action, tier: PERF_ACTIONS[action].tier,
      respondedMs: round1(entry.responded ?? completeMs), completeMs: round1(completeMs),
      at: Date.now(), detail: entry.detail,
    };
    perfSamples.update((list) => {
      const next = list.length >= PERF_SAMPLE_CAP ? list.slice(list.length - PERF_SAMPLE_CAP + 1) : list.slice();
      next.push(sample);
      return next;
    });
    try { sink?.(sample); } catch { /* a logging failure never breaks an action */ }
    return sample;
  });
}

function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

// -- long tasks ------------------------------------------------------------

/** NFR-PERF-005's "any frame over 250 ms". */
export const LONG_TASK_MS = 250;

export interface LongTaskTally {
  /** The WebView exposes the `longtask` entry type and the observer is running. */
  supported: boolean;
  /** Tasks of LONG_TASK_MS or more since the observer started. */
  count: number;
  longestMs: number;
  totalMs: number;
}

export const longTasks: Writable<LongTaskTally> = writable({ supported: false, count: 0, longestMs: 0, totalMs: 0 });

/** The diagnostics-log line for one long task; `scripts/perf_table.py` counts
 *  them and reports the longest. */
export function formatLongTaskLine(durationMs: number): string {
  return `perf longtask=${round1(durationMs)}`;
}

/** Count every task of LONG_TASK_MS or more for the rest of the session and
 *  write each one to `log`, so the 30-minute recording on the field laptop
 *  needs no DevTools (#260). Feature-detected: where the WebView does not
 *  expose `PerformanceObserver` or its `longtask` entry type this registers
 *  nothing, `longTasks.supported` stays false and the returned stop is a
 *  no-op. Registered once, by App.svelte. */
export function observeLongTasks(log: (line: string) => void): () => void {
  const Observer = (globalThis as { PerformanceObserver?: typeof PerformanceObserver }).PerformanceObserver;
  const supported = typeof Observer === "function"
    && Array.isArray(Observer.supportedEntryTypes) && Observer.supportedEntryTypes.includes("longtask");
  if (!supported) return () => {};
  let observer: PerformanceObserver;
  try {
    observer = new Observer((list) => {
      for (const entry of list.getEntries()) {
        if (entry.duration < LONG_TASK_MS) continue;
        longTasks.update((tally) => ({
          supported: true,
          count: tally.count + 1,
          longestMs: Math.max(tally.longestMs, round1(entry.duration)),
          totalMs: round1(tally.totalMs + entry.duration),
        }));
        try { log(formatLongTaskLine(entry.duration)); } catch { /* the log is nobody's problem but the log's */ }
      }
    });
    observer.observe({ type: "longtask", buffered: true });
  } catch {
    return () => {};
  }
  longTasks.update((tally) => ({ ...tally, supported: true }));
  return () => {
    observer.disconnect();
    longTasks.update((tally) => ({ ...tally, supported: false }));
  };
}

/** The diagnostics-log line for one sample; `scripts/perf_table.py` parses it. */
export function formatPerfLine(sample: PerfSample): string {
  const detail = sample.detail ? ` detail=${sample.detail.replace(/\s+/g, "_")}` : "";
  return `perf action=${sample.action} tier=${sample.tier} responded=${sample.respondedMs} complete=${sample.completeMs}${detail}`;
}

// -- summary ---------------------------------------------------------------

/** The same nearest-rank percentile as scripts/benchmark_language_qa.py and
 *  scripts/perf_table.py, so a table built in the app and one built from the
 *  log agree to the sample. */
export function percentile(values: number[], fraction: number): number {
  if (values.length === 0) return 0;
  const ordered = [...values].sort((a, b) => a - b);
  const index = Math.min(ordered.length - 1, roundHalfEven(fraction * (ordered.length - 1)));
  return ordered[index];
}

/** Python's round(): half to even. */
function roundHalfEven(value: number): number {
  const floor = Math.floor(value);
  const diff = value - floor;
  if (diff > 0.5) return floor + 1;
  if (diff < 0.5) return floor;
  return floor % 2 === 0 ? floor : floor + 1;
}

export interface PerfActionSummary {
  action: string;
  tier: PerfTier;
  label: string;
  samples: number;
  respondedP50: number;
  respondedP95: number;
  completeP50: number;
  completeP95: number;
  completeMax: number;
  /** p95 within both budgets of the tier; null when there are no samples. */
  pass: boolean | null;
}

export function perfSummary(samples: PerfSample[]): PerfActionSummary[] {
  return Object.entries(PERF_ACTIONS).map(([action, { tier, label }]) => {
    const own = samples.filter((s) => s.action === action);
    const responded = own.map((s) => s.respondedMs);
    const complete = own.map((s) => s.completeMs);
    const budget = TIER_BUDGETS[tier];
    const respondedP95 = percentile(responded, 0.95);
    const completeP95 = percentile(complete, 0.95);
    return {
      action, tier, label, samples: own.length,
      respondedP50: percentile(responded, 0.5), respondedP95,
      completeP50: percentile(complete, 0.5), completeP95,
      completeMax: complete.length ? Math.max(...complete) : 0,
      pass: own.length ? respondedP95 <= budget.respondedMs && completeP95 <= budget.completeMs : null,
    };
  });
}

/** The release-notes table: action, tier, samples, p95s, budget, result. */
export function perfTableMarkdown(rows: PerfActionSummary[], hardware = "", minSamples = 20): string {
  const lines = [
    hardware ? `Hardware: ${hardware}` : "",
    "",
    "| Action | Tier | n | Responded p95 (ms) | Complete p95 (ms) | Budget (ms) | Result |",
    "|---|---|---:|---:|---:|---|---|",
  ].filter((line, index) => index !== 0 || line);
  for (const row of rows) {
    const budget = TIER_BUDGETS[row.tier];
    const result = row.samples === 0 ? "not measured"
      : row.samples < minSamples ? `only ${row.samples} samples`
      : row.pass ? "pass" : "FAIL";
    lines.push(
      `| ${row.label} (\`${row.action}\`) | ${row.tier} | ${row.samples} | ${row.samples ? row.respondedP95 : "-"} | `
      + `${row.samples ? row.completeP95 : "-"} | ${budget.respondedMs} / ${budget.completeMs} | ${result} |`,
    );
  }
  return lines.join("\n");
}

// -- the in-app runner -----------------------------------------------------

/** What App.svelte can drive without a hand on the mouse. Each performs one
 *  instrumented action and resolves when it has ended; the runner repeats
 *  each one `repetitions` times. The actions whose click lives in a
 *  component (a menu, a word) are measured when a reviewer does them. */
export interface PerfRunnerActions {
  navigateVerse: () => Promise<void>;
  openChapter: () => Promise<void>;
  togglePanel: () => Promise<void>;
  switchBook: (() => Promise<void>) | null;
  openReport: (() => Promise<void>) | null;
}

let runner: PerfRunnerActions | null = null;
let running = false;

export function registerPerfRunner(actions: PerfRunnerActions | null): void {
  runner = actions;
}

export function perfRunnerAvailable(): boolean {
  return runner !== null && !running;
}

export interface PerfRunProgress {
  step: string;
  done: number;
  total: number;
}

/** Repeat every registered action `repetitions` times, pausing briefly between
 *  repetitions so each paint is its own. Resolves with the summary. */
export async function runPerfSample(
  repetitions = 20,
  onProgress?: (progress: PerfRunProgress) => void,
  pauseMs = 60,
): Promise<PerfActionSummary[]> {
  if (!runner || running) throw new Error("The responsiveness runner needs an open project and no run in progress.");
  running = true;
  try {
    const steps: Array<[string, () => Promise<void>]> = [
      ["verse.navigate", runner.navigateVerse],
      ["panel.toggle", runner.togglePanel],
      ["chapter.open", runner.openChapter],
    ];
    if (runner.switchBook) steps.push(["book.switch", runner.switchBook]);
    if (runner.openReport) steps.push(["book.report", runner.openReport]);
    const total = steps.length * repetitions;
    let done = 0;
    for (const [step, act] of steps) {
      for (let i = 0; i < repetitions; i += 1) {
        onProgress?.({ step, done, total });
        await act();
        done += 1;
        await new Promise<void>((resolve) => setTimeout(resolve, pauseMs));
      }
    }
    onProgress?.({ step: "", done: total, total });
    let latest: PerfSample[] = [];
    const stop = perfSamples.subscribe((list) => { latest = list; });
    stop();
    return perfSummary(latest);
  } finally {
    running = false;
  }
}
