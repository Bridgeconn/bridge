/**
 * The run behind "Align with AI" (2026-11-24): one store that starts, watches,
 * cancels and resumes the engine's automatic-alignment job, and outlives the
 * dialog and the editor screen. It used to live in a component, and leaving the
 * editor lost the job.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

const { getSettings, autoAlignStart, autoAlignStatus, autoAlignCancel, autoAlignRetry } = vi.hoisted(() => ({
  getSettings: vi.fn(), autoAlignStart: vi.fn(), autoAlignStatus: vi.fn(), autoAlignCancel: vi.fn(), autoAlignRetry: vi.fn(),
}));

vi.mock("../api/bridgeClient", () => ({
  bridge: { getSettings, autoAlignStart, autoAlignStatus, autoAlignCancel, autoAlignRetry },
}));

import {
  attachRun, autoAlignFinished, autoAlignReady, autoAlignRun, cancelRun, chapterSummaries, dismissRun,
  firstToReview, refreshAutoAlignReady, resetAutoAlignRunForTests, resumeRun, runTotals, startRun,
} from "../autoAlignRun";
import { alignmentRevisionByVerse, project } from "../stores";
import type { AutoAlignJobStatus } from "../types/finding";

function snapshot(overrides: Partial<AutoAlignJobStatus> = {}): AutoAlignJobStatus {
  return {
    jobId: "aaj-1", scope: "chapter", apply: true, state: "running", stage: "",
    chapters: ["1", "2"], chapterWindows: { "1": 2, "2": 1 },
    windowsTotal: 3, windowsDone: 0, windowsFailed: 0, percent: 0,
    currentWindow: null, currentPass: null, windowResult: null,
    verdictCounts: {}, verdicts: {}, results: {},
    usage: { calls: 0, totalTokens: 0, estimatedCostUSD: 0 },
    error: null, unavailable: null, resumeOf: "", createdAt: "", finishedAt: null,
    ...overrides,
  };
}

const done = (chapter: string, verses: string[], status: "succeeded" | "failed" = "succeeded") => ({
  chapter, verses, status, error: status === "failed" ? "The provider refused." : null,
});

async function tick(ms = 1100): Promise<void> {
  await vi.advanceTimersByTimeAsync(ms);
}

describe("autoAlignRun", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    resetAutoAlignRunForTests();
    project.set({ path: "/p", bookId: "php", chapters: ["1", "2", "3"] } as never);
    alignmentRevisionByVerse.set({});
  });

  afterEach(() => {
    resetAutoAlignRunForTests();
    vi.useRealTimers();
  });

  it("starts a run over the chosen chapters and follows it to the end", async () => {
    autoAlignStart.mockResolvedValue(snapshot());
    autoAlignStatus
      .mockResolvedValueOnce(snapshot({
        currentWindow: { chapter: "1", verses: ["3", "4"] }, windowsDone: 1,
        verdicts: { "1:1": "ALIGNED_CLEAN", "1:2": "NEEDS_REVIEW" }, results: { "1:1-3": done("1", ["1", "2", "3"]) },
      }))
      .mockResolvedValue(snapshot({
        state: "succeeded", windowsDone: 3,
        verdicts: { "1:1": "ALIGNED_CLEAN", "1:2": "NEEDS_REVIEW", "1:4": "ALIGNED_CLEAN", "2:1": "ALIGNED_CLEAN" },
        results: { "1:1-3": done("1", ["1", "2", "3"]), "1:3-4": done("1", ["3", "4"]), "2:1-2": done("2", ["1", "2"]) },
      }));

    expect(await startRun(["1", "2"])).toBe(true);
    expect(autoAlignStart).toHaveBeenCalledWith("chapter", ["1", "2"]);
    expect(get(autoAlignRun)).toMatchObject({ phase: "running", chapters: ["1", "2"], chapterWindows: { "1": 2, "2": 1 }, projectPath: "/p" });

    await tick();
    // A verse with a verdict was written: said as it happens, during the run.
    expect(get(alignmentRevisionByVerse)).toEqual({ "1:1": 1, "1:2": 1 });
    expect(get(autoAlignFinished)).toBeNull();
    expect(chapterSummaries(get(autoAlignRun)).map((item) => item.state)).toEqual(["running", "waiting"]);

    await tick();
    const run = get(autoAlignRun);
    expect(run.phase).toBe("finished");
    // Each verse once, however many polls carried its verdict.
    expect(get(alignmentRevisionByVerse)).toEqual({ "1:1": 1, "1:2": 1, "1:4": 1, "2:1": 1 });
    expect(get(autoAlignFinished)).toMatchObject({ chapters: ["1", "2"], projectPath: "/p" });
    expect(chapterSummaries(run).map((item) => [item.chapter, item.state, item.clean, item.review]))
      .toEqual([["1", "review", 2, 1], ["2", "clean", 1, 0]]);
    expect(runTotals(run)).toEqual({ clean: 3, review: 1, windowsDone: 3, windowsTotal: 3, windowsFailed: 0 });
    expect(firstToReview(run)).toEqual({ chapter: "1", verses: ["2"] });
    // No more polling once it has ended.
    const calls = autoAlignStatus.mock.calls.length;
    await tick(3000);
    expect(autoAlignStatus).toHaveBeenCalledTimes(calls);
  });

  it("does not start with no provider, and says why", async () => {
    autoAlignStart.mockResolvedValue({ ...snapshot({ state: "failed" }), unavailable: { reason: "no-api-key", message: "No OpenAI-compatible API key is configured." } });
    expect(await startRun(["1"])).toBe(false);
    expect(get(autoAlignRun)).toMatchObject({ phase: "idle", error: "No OpenAI-compatible API key is configured." });
    expect(autoAlignStatus).not.toHaveBeenCalled();
  });

  it("shows a refused start (another job is running) as an error and stays idle", async () => {
    autoAlignStart.mockRejectedValue(new Error("Automatic alignment job aaj-9 is already running."));
    expect(await startRun(["1"])).toBe(false);
    expect(get(autoAlignRun)).toMatchObject({ phase: "idle", error: "Automatic alignment job aaj-9 is already running." });
  });

  it("refuses a second run while one is under way, and an empty one", async () => {
    autoAlignStart.mockResolvedValue(snapshot());
    autoAlignStatus.mockResolvedValue(snapshot());
    expect(await startRun([])).toBe(false);
    expect(await startRun(["1", "2"])).toBe(true);
    expect(await startRun(["3"])).toBe(false);
    expect(autoAlignStart).toHaveBeenCalledTimes(1);
  });

  it("cancels, then resumes with what is left and keeps what was done", async () => {
    autoAlignStart.mockResolvedValue(snapshot());
    const afterOne = {
      windowsDone: 1, verdicts: { "1:1": "ALIGNED_CLEAN" as const }, results: { "1:1-3": done("1", ["1", "2", "3"]) },
    };
    autoAlignCancel.mockResolvedValue(snapshot({ state: "cancelling", ...afterOne }));
    autoAlignStatus.mockResolvedValue(snapshot({ state: "cancelled", ...afterOne }));
    await startRun(["1", "2"]);
    await cancelRun();
    expect(autoAlignCancel).toHaveBeenCalledWith("aaj-1");
    expect(get(autoAlignRun).job?.state).toBe("cancelling");
    await tick();
    expect(get(autoAlignRun).phase).toBe("finished");
    expect(chapterSummaries(get(autoAlignRun)).map((item) => item.state)).toEqual(["partial", "waiting"]);
    // Dismiss is for a finished run; a running one is not thrown away.

    // The resumed job reports only what it still has to run.
    autoAlignRetry.mockResolvedValue(snapshot({ jobId: "aaj-2", resumeOf: "aaj-1", chapterWindows: { "1": 1, "2": 1 }, windowsTotal: 2 }));
    autoAlignStatus.mockResolvedValue(snapshot({
      jobId: "aaj-2", resumeOf: "aaj-1", state: "succeeded", chapterWindows: { "1": 1, "2": 1 }, windowsTotal: 2, windowsDone: 2,
      verdicts: { "1:4": "ALIGNED_CLEAN", "2:1": "NEEDS_REVIEW" },
      results: { "1:3-4": done("1", ["3", "4"]), "2:1-2": done("2", ["1", "2"]) },
    }));
    expect(await resumeRun()).toBe(true);
    expect(autoAlignRetry).toHaveBeenCalledWith("aaj-1");
    expect(get(autoAlignRun)).toMatchObject({ phase: "running", chapterWindows: { "1": 2, "2": 1 } });
    await tick();
    const run = get(autoAlignRun);
    expect(run.phase).toBe("finished");
    // The whole run: the first job's verse and window, and the second's.
    expect(Object.keys(run.verdicts).sort()).toEqual(["1:1", "1:4", "2:1"]);
    expect(runTotals(run)).toEqual({ clean: 2, review: 1, windowsDone: 3, windowsTotal: 3, windowsFailed: 0 });
    expect(chapterSummaries(run).map((item) => item.state)).toEqual(["clean", "review"]);
  });

  it("asks a failed window again on resume: its failure is no longer the last word", async () => {
    autoAlignStart.mockResolvedValue(snapshot({ chapters: ["1"], chapterWindows: { "1": 2 }, windowsTotal: 2 }));
    autoAlignStatus.mockResolvedValue(snapshot({
      chapters: ["1"], chapterWindows: { "1": 2 }, windowsTotal: 2, windowsDone: 2, windowsFailed: 1,
      state: "failed", error: "1 window(s) failed.",
      results: { "1:1-3": done("1", ["1", "2", "3"]), "1:3-4": done("1", ["3", "4"], "failed") },
    }));
    await startRun(["1"]);
    await tick();
    expect(get(autoAlignRun)).toMatchObject({ phase: "finished", error: "1 window(s) failed." });
    expect(chapterSummaries(get(autoAlignRun))[0]).toMatchObject({ state: "failed", failed: 1 });

    autoAlignRetry.mockResolvedValue(snapshot({ jobId: "aaj-2", chapters: ["1"], chapterWindows: { "1": 1 }, windowsTotal: 1 }));
    autoAlignStatus.mockResolvedValue(snapshot({ jobId: "aaj-2", chapters: ["1"], chapterWindows: { "1": 1 }, windowsTotal: 1 }));
    await resumeRun();
    const run = get(autoAlignRun);
    expect(run.error).toBe("");
    expect(Object.keys(run.results)).toEqual(["1:1-3"]);
    expect(chapterSummaries(run)[0]).toMatchObject({ state: "partial", failed: 0, windowsDone: 1 });
  });

  it("does not resume a run that succeeded, and dismisses only a finished run", async () => {
    autoAlignStart.mockResolvedValue(snapshot());
    autoAlignStatus.mockResolvedValue(snapshot());
    await startRun(["1", "2"]);
    dismissRun();
    expect(get(autoAlignRun).phase).toBe("running");
    expect(await resumeRun()).toBe(false);

    autoAlignStatus.mockResolvedValue(snapshot({ state: "succeeded" }));
    await tick();
    expect(await resumeRun()).toBe(false);
    dismissRun();
    expect(get(autoAlignRun)).toMatchObject({ phase: "idle", job: null, chapters: [] });
  });

  it("keeps following through a few failed status reads, then says it lost the run", async () => {
    autoAlignStart.mockResolvedValue(snapshot());
    autoAlignStatus
      .mockRejectedValueOnce(new Error("timeout"))
      .mockRejectedValueOnce(new Error("timeout"))
      .mockResolvedValueOnce(snapshot({ windowsDone: 1, results: { "1:1-3": done("1", ["1", "2", "3"]) } }))
      .mockRejectedValue(new Error("Unknown automatic alignment job 'aaj-1'."));
    await startRun(["1", "2"]);
    await tick(3300);
    // Two failures, then an answer: still running, nothing shown as wrong.
    expect(get(autoAlignRun)).toMatchObject({ phase: "running", error: "", lost: false });
    expect(runTotals(get(autoAlignRun)).windowsDone).toBe(1);
    await tick(5500);
    const run = get(autoAlignRun);
    expect(run).toMatchObject({ phase: "finished", lost: true });
    expect(run.error).toContain("Unknown automatic alignment job");
    // The last figures stand.
    expect(runTotals(run).windowsDone).toBe(1);
  });

  describe("a job the engine is still running when the page has none", () => {
    it("is picked up and followed", async () => {
      autoAlignStatus.mockResolvedValue(snapshot({ currentWindow: { chapter: "2", verses: ["1", "2"] }, windowsDone: 2 }));
      await attachRun();
      expect(autoAlignStatus).toHaveBeenCalledWith("");
      expect(get(autoAlignRun)).toMatchObject({ phase: "running", chapters: ["1", "2"], projectPath: "/p" });
      autoAlignStatus.mockResolvedValue(snapshot({ state: "succeeded", windowsDone: 3 }));
      await tick();
      expect(get(autoAlignRun).phase).toBe("finished");
    });

    it("is left alone when it is the Cross-verse page's window, has ended, or does not exist", async () => {
      autoAlignStatus.mockResolvedValueOnce(snapshot({ scope: "window" }));
      await attachRun();
      expect(get(autoAlignRun).phase).toBe("idle");
      autoAlignStatus.mockResolvedValueOnce(snapshot({ state: "succeeded" }));
      await attachRun();
      expect(get(autoAlignRun).phase).toBe("idle");
      autoAlignStatus.mockRejectedValueOnce(new Error("Unknown automatic alignment job ''."));
      await attachRun();
      expect(get(autoAlignRun)).toMatchObject({ phase: "idle", error: "" });
    });
  });

  it("says nothing to the alignment views for a run that belongs to another book", async () => {
    autoAlignStart.mockResolvedValue(snapshot());
    autoAlignStatus.mockResolvedValue(snapshot({ state: "succeeded", verdicts: { "1:1": "ALIGNED_CLEAN" } }));
    await startRun(["1", "2"]);
    project.set({ path: "/other", bookId: "tit", chapters: ["1"] } as never);
    await tick();
    expect(get(autoAlignRun).phase).toBe("finished");
    expect(get(alignmentRevisionByVerse)).toEqual({});
    // The editor compares this path with the open project before it reloads.
    expect(get(autoAlignFinished)?.projectPath).toBe("/p");
  });

  it("reads a chapter's state by position when the engine gives no per-chapter count", () => {
    const base = get(autoAlignRun);
    const run = {
      ...base, phase: "running" as const, chapters: ["1", "2", "3"], chapterWindows: {},
      job: snapshot({ chapters: ["1", "2", "3"], chapterWindows: undefined, currentWindow: { chapter: "2", verses: ["1", "2"] } }),
      results: { "1:1-3": done("1", ["1", "2", "3"]) }, verdicts: { "1:1": "NEEDS_REVIEW" as const },
    };
    expect(chapterSummaries(run).map((item) => [item.state, item.windowsTotal]))
      .toEqual([["review", null], ["running", null], ["waiting", null]]);
    expect(runTotals(run).windowsTotal).toBe(3);
  });

  it("reads whether an AI request could be sent", async () => {
    getSettings.mockResolvedValueOnce({ aiReady: true, hasApiKey: false });
    await refreshAutoAlignReady();
    expect(get(autoAlignReady)).toBe(true);
    // An engine from before the ChatGPT sign-in reports only hasApiKey.
    getSettings.mockResolvedValueOnce({ hasApiKey: false });
    await refreshAutoAlignReady();
    expect(get(autoAlignReady)).toBe(false);
    getSettings.mockRejectedValueOnce(new Error("no engine"));
    await refreshAutoAlignReady();
    expect(get(autoAlignReady)).toBe(false);
  });
});
