/**
 * One run of "Align with AI": the chapters a reviewer chose in the dialog,
 * aligned by the engine's automatic-alignment job (alignment.autoAlign.*).
 *
 * The run lives here and not in a component. It used to live in the strip
 * above the text, and leaving the editor screen unmounted the strip: the
 * engine went on, and the app never found the job again. That was survivable
 * for one chapter; a whole book runs for a long time, and the reviewer is
 * meant to keep working meanwhile. The dialog, the strip and the Alignment
 * menu all read this one store.
 *
 * Nothing here decides what is written. The job asks about three verses at a
 * time, twice, and writes what both answers agree on; this starts, watches,
 * cancels and resumes it.
 */
import { get, writable } from "svelte/store";
import { bridge } from "./api/bridgeClient";
import { noteAlignmentChanged, project } from "./stores";
import type { AutoAlignJobStatus, AutoAlignVerdictKind } from "./types/finding";

type WindowResult = NonNullable<AutoAlignJobStatus["results"]>[string];

export interface AutoAlignRun {
  /** idle: nothing to show. running: a job is under way. finished: its result
   *  is on screen until it is dismissed. */
  phase: "idle" | "running" | "finished";
  job: AutoAlignJobStatus | null;
  /** The chapters of the whole run, in the order they run, and how many
   *  windows each has. Fixed when the run starts: a resumed job reports only
   *  what it still has to run, and the run is still the same chapters. */
  chapters: string[];
  chapterWindows: Record<string, number>;
  /** Across this job and the jobs it resumed. */
  verdicts: Record<string, AutoAlignVerdictKind>;
  results: Record<string, WindowResult>;
  error: string;
  /** The status could not be read several times in a row: the last figures
   *  stand, and nothing more is known. */
  lost: boolean;
  /** The project the run was started in. */
  projectPath: string;
}

const IDLE: AutoAlignRun = {
  phase: "idle", job: null, chapters: [], chapterWindows: {}, verdicts: {}, results: {},
  error: "", lost: false, projectPath: "",
};

export const autoAlignRun = writable<AutoAlignRun>({ ...IDLE });

/** Set once a job ends: the editor reloads the open chapter when the run
 *  wrote to it. `seq` makes two runs over the same chapters two signals. */
export const autoAlignFinished = writable<{ seq: number; chapters: string[]; projectPath: string } | null>(null);

/** An AI request could be sent now (an API key, or a ChatGPT sign-in).
 *  Undefined until it has been read. */
export const autoAlignReady = writable<boolean | undefined>(undefined);

export async function refreshAutoAlignReady(): Promise<void> {
  try {
    // #506: an engine from before the ChatGPT sign-in reports only hasApiKey.
    const settings = await bridge.getSettings();
    autoAlignReady.set(Boolean(settings?.aiReady ?? settings?.hasApiKey));
  } catch {
    autoAlignReady.set(false);
  }
}

const POLL_MS = 1000;
/** A failed status read says nothing about the job, which keeps running in
 *  the engine. Polling goes on through this many failures in a row. */
const MAX_POLL_FAILURES = 5;
const ACTIVE = new Set<AutoAlignJobStatus["state"]>(["queued", "running", "cancelling"]);

let timer: ReturnType<typeof setInterval> | null = null;
let pollFailures = 0;
let polling = false;
let finishedSeq = 0;
/** What the jobs this one resumed had already decided. */
let carriedVerdicts: Record<string, AutoAlignVerdictKind> = {};
let carriedResults: Record<string, WindowResult> = {};
/** Verdicts already announced to the alignment views. */
let announced = new Set<string>();

const message = (value: unknown): string => (value instanceof Error ? value.message : String(value));

function stopPolling(): void {
  if (timer) clearInterval(timer);
  timer = null;
}

function startPolling(): void {
  stopPolling();
  pollFailures = 0;
  timer = setInterval(() => { void poll(); }, POLL_MS);
}

function inThisProject(run: AutoAlignRun): boolean {
  return run.projectPath === (get(project)?.path ?? "");
}

/** Put a job snapshot into the store, merged with what earlier jobs of the
 *  same run decided, and tell the alignment views about each new verdict. */
function absorb(job: AutoAlignJobStatus, patch: Partial<AutoAlignRun> = {}): AutoAlignRun {
  const current = get(autoAlignRun);
  const next: AutoAlignRun = {
    ...current, ...patch, job,
    verdicts: { ...carriedVerdicts, ...(job.verdicts ?? {}) },
    results: { ...carriedResults, ...(job.results ?? {}) },
  };
  autoAlignRun.set(next);
  // A verse with a verdict was written. Said as it happens, not only at the
  // end: during a long run the reviewer may be looking at that verse.
  if (inThisProject(next)) {
    for (const key of Object.keys(job.verdicts ?? {})) {
      const mark = `${job.jobId}|${key}`;
      if (announced.has(mark)) continue;
      announced.add(mark);
      noteAlignmentChanged(key);
    }
  }
  return next;
}

function finish(run: AutoAlignRun): void {
  stopPolling();
  const job = run.job;
  autoAlignRun.set({
    ...run, phase: "finished",
    error: job?.state === "failed" && job.error ? job.error : run.error,
  });
  finishedSeq += 1;
  autoAlignFinished.set({ seq: finishedSeq, chapters: [...run.chapters], projectPath: run.projectPath });
}

async function poll(): Promise<void> {
  const jobId = get(autoAlignRun).job?.jobId;
  if (!jobId || polling) return;
  polling = true;
  try {
    const job = await bridge.autoAlignStatus(jobId);
    // Dismissed or replaced while the answer was on its way.
    if (get(autoAlignRun).job?.jobId !== jobId) return;
    pollFailures = 0;
    const run = absorb(job, { lost: false });
    if (!ACTIVE.has(job.state)) finish(run);
  } catch (value) {
    if (get(autoAlignRun).job?.jobId !== jobId) return;
    pollFailures += 1;
    if (pollFailures >= MAX_POLL_FAILURES) {
      stopPolling();
      autoAlignRun.update((run) => ({
        ...run, phase: "finished", lost: true,
        error: `The run can no longer be followed: ${message(value)}`,
      }));
    }
  } finally {
    polling = false;
  }
}

/** Start a run over these chapters, in this order. False when it did not
 *  start; the reason is in the store's `error`. */
export async function startRun(chapters: string[]): Promise<boolean> {
  if (!chapters.length || get(autoAlignRun).phase === "running") return false;
  const projectPath = get(project)?.path ?? "";
  autoAlignRun.update((run) => ({ ...run, error: "" }));
  try {
    const job = await bridge.autoAlignStart("chapter", chapters);
    if (job.unavailable) {
      autoAlignRun.update((run) => ({ ...run, error: job.unavailable?.message ?? "No AI provider is set up." }));
      return false;
    }
    carriedVerdicts = {};
    carriedResults = {};
    announced = new Set();
    autoAlignRun.set({ ...IDLE, projectPath });
    absorb(job, {
      phase: "running", projectPath,
      chapters: job.chapters?.length ? [...job.chapters] : [...chapters],
      chapterWindows: { ...(job.chapterWindows ?? {}) },
    });
    startPolling();
    return true;
  } catch (value) {
    autoAlignRun.update((run) => ({ ...run, error: message(value) }));
    return false;
  }
}

/** Ask the running job to stop. It stops after the request in flight; what
 *  finished windows wrote stays. */
export async function cancelRun(): Promise<void> {
  const job = get(autoAlignRun).job;
  if (!job || !ACTIVE.has(job.state)) return;
  try {
    absorb(await bridge.autoAlignCancel(job.jobId));
  } catch (value) {
    autoAlignRun.update((run) => ({ ...run, error: message(value) }));
  }
}

/** Run what a cancelled or failed run left: the windows with no result, and
 *  the ones that failed. */
export async function resumeRun(): Promise<boolean> {
  const run = get(autoAlignRun);
  const job = run.job;
  if (run.phase !== "finished" || !job || !["failed", "cancelled"].includes(job.state)) return false;
  try {
    const next = await bridge.autoAlignRetry(job.jobId);
    // A failed window is asked again, so its failure is no longer the last word.
    carriedVerdicts = { ...run.verdicts };
    carriedResults = Object.fromEntries(
      Object.entries(run.results).filter(([, result]) => result.status === "succeeded"),
    );
    absorb(next, { phase: "running", error: "", lost: false });
    startPolling();
    return true;
  } catch (value) {
    autoAlignRun.update((current) => ({ ...current, error: message(value) }));
    return false;
  }
}

/** Clear a finished run from the screen. A running one is not dismissed. */
export function dismissRun(): void {
  if (get(autoAlignRun).phase === "running") return;
  stopPolling();
  autoAlignRun.set({ ...IDLE });
}

/** Drop an error that belongs to no run (a start that was refused). */
export function clearRunError(): void {
  autoAlignRun.update((run) => (run.phase === "idle" ? { ...run, error: "" } : run));
}

/** Pick up a job the engine is still running when the app has no run of its
 *  own (the page was reloaded). A window-scoped job is the Cross-verse page's
 *  "Align automatically", not a run of this dialog. */
export async function attachRun(): Promise<void> {
  if (get(autoAlignRun).phase !== "idle") return;
  let job: AutoAlignJobStatus;
  try {
    job = await bridge.autoAlignStatus("");
  } catch {
    return; // no job has run in this engine
  }
  if (get(autoAlignRun).phase !== "idle") return;
  if (!job || job.scope === "window" || !ACTIVE.has(job.state)) return;
  carriedVerdicts = {};
  carriedResults = {};
  announced = new Set();
  absorb(job, {
    phase: "running", projectPath: get(project)?.path ?? "", error: "", lost: false,
    chapters: [...(job.chapters ?? [])],
    chapterWindows: { ...(job.chapterWindows ?? {}) },
  });
  startPolling();
}

// -- what the dialog and the strip show ---------------------------------------

export type ChapterRunState = "waiting" | "running" | "clean" | "review" | "failed" | "partial";

export interface ChapterRunSummary {
  chapter: string;
  state: ChapterRunState;
  windowsDone: number;
  /** Unknown from an engine that does not report it. */
  windowsTotal: number | null;
  clean: number;
  review: number;
  failed: number;
}

/** One summary per chapter of the run, in run order.
 *  - running: the job is asking about this chapter now;
 *  - clean / review / failed: every window of the chapter has a result;
 *  - partial: the run ended partway through the chapter;
 *  - waiting: nothing of it has been asked yet. */
export function chapterSummaries(run: AutoAlignRun): ChapterRunSummary[] {
  const job = run.job;
  const active = run.phase === "running";
  const currentChapter = active ? job?.currentWindow?.chapter ?? null : null;
  const currentIndex = currentChapter === null ? -1 : run.chapters.indexOf(currentChapter);
  return run.chapters.map((chapter, index) => {
    const prefix = `${chapter}:`;
    let windowsDone = 0;
    let failed = 0;
    for (const result of Object.values(run.results)) {
      if (result.chapter !== chapter) continue;
      windowsDone += 1;
      if (result.status === "failed") failed += 1;
    }
    let clean = 0;
    let review = 0;
    for (const [key, verdict] of Object.entries(run.verdicts)) {
      if (!key.startsWith(prefix)) continue;
      if (verdict === "ALIGNED_CLEAN") clean += 1;
      else if (verdict === "NEEDS_REVIEW") review += 1;
    }
    const total = chapter in run.chapterWindows ? run.chapterWindows[chapter] : null;
    const complete = total !== null
      ? windowsDone >= total
      // No per-chapter count: a chapter the job has moved past, or any chapter
      // with results once the whole job succeeded.
      : job?.state === "succeeded" || (currentIndex > -1 && index < currentIndex);
    let state: ChapterRunState;
    if (chapter === currentChapter) state = "running";
    else if (complete) state = failed > 0 ? "failed" : review > 0 ? "review" : "clean";
    else state = windowsDone > 0 ? "partial" : "waiting";
    return { chapter, state, windowsDone, windowsTotal: total, clean, review, failed };
  });
}

export interface RunTotals { clean: number; review: number; windowsDone: number; windowsTotal: number; windowsFailed: number }

export function runTotals(run: AutoAlignRun): RunTotals {
  let clean = 0;
  let review = 0;
  for (const verdict of Object.values(run.verdicts)) {
    if (verdict === "ALIGNED_CLEAN") clean += 1;
    else if (verdict === "NEEDS_REVIEW") review += 1;
  }
  const results = Object.values(run.results);
  const known = Object.values(run.chapterWindows);
  return {
    clean, review,
    windowsDone: results.length,
    windowsFailed: results.filter((result) => result.status === "failed").length,
    // The run's own total when the engine gave it per chapter; otherwise the job's.
    windowsTotal: known.length ? known.reduce((sum, count) => sum + count, 0) : run.job?.windowsTotal ?? 0,
  };
}

/** The first chapter with verses to review, and its first three. */
export function firstToReview(run: AutoAlignRun): { chapter: string; verses: string[] } | null {
  for (const chapter of run.chapters) {
    const prefix = `${chapter}:`;
    const verses = Object.entries(run.verdicts)
      .filter(([key, verdict]) => key.startsWith(prefix) && verdict === "NEEDS_REVIEW")
      .map(([key]) => key.slice(prefix.length));
    if (verses.length) return { chapter, verses: verses.slice(0, 3) };
  }
  return null;
}

/** What a run would cost, as the dialog and the strip say it. */
export function runCost(usd: number): string {
  return usd < 0.01 ? "under $0.01" : `about $${usd.toFixed(2)}`;
}

/** For tests: forget everything, as a fresh app start does. */
export function resetAutoAlignRunForTests(): void {
  stopPolling();
  carriedVerdicts = {};
  carriedResults = {};
  announced = new Set();
  pollFailures = 0;
  polling = false;
  autoAlignRun.set({ ...IDLE });
  autoAlignFinished.set(null);
  autoAlignReady.set(undefined);
}
