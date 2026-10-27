import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

const { collectionQaStatus, collectionRunChecks, collectionCancelChecks } = vi.hoisted(() => ({
  collectionQaStatus: vi.fn(),
  collectionRunChecks: vi.fn(),
  collectionCancelChecks: vi.fn(),
}));

vi.mock("../api/bridgeClient", () => ({
  bridge: { collectionQaStatus, collectionRunChecks, collectionCancelChecks, collectionPauseChecks: vi.fn() },
}));

import { collectionQa, collectionQaRunning, startCollectionQa, stopCollectionQa } from "../collectionQa";
import {
  bindCollectionStrip, cancelStripJob, collectionFinishedLabel, collectionStripProgress,
} from "../collectionStrip";
import { checkingProgress } from "../stores";
import type { CollectionQaSnapshot } from "../types/collectionQa";

function snapshot(overrides: Partial<CollectionQaSnapshot> = {}): CollectionQaSnapshot {
  return { jobId: "cq-1", state: "running", paused: false, collectionPath: "/p/gen", checks: ["languageQa"],
    totalBooks: 66, completedBooks: 3, percent: 4.6, currentBook: "lev", books: [], finalStage: null,
    elapsedSeconds: 180, estimatedRemainingSeconds: 2400, error: null, createdAt: null, finishedAt: null,
    ...overrides };
}

function idleStrip() {
  checkingProgress.set({ running: false, percent: 40, label: "", jobId: "", state: "idle", error: "", scope: "chapter" });
}

describe("the Collection QA strip (#399)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stopCollectionQa();
    idleStrip();
  });

  it("words the run's own progress: books done, the job's percent, time left, paused, cancelling", () => {
    expect(collectionStripProgress(snapshot())).toEqual({
      running: true, percent: 5, label: "Collection QA \u00b7 3/66 books \u00b7 about 40 min 0 s left", state: "running",
    });
    expect(collectionStripProgress(snapshot({ paused: true })).label).toBe("Collection QA \u00b7 3/66 books \u00b7 paused");
    expect(collectionStripProgress(snapshot({ estimatedRemainingSeconds: null })).label).toBe("Collection QA \u00b7 3/66 books");
    expect(collectionStripProgress(snapshot({ state: "cancelling", percent: 100.4 })))
      .toEqual({ running: true, percent: 100, label: "Collection QA \u00b7 3/66 books \u00b7 cancelling", state: "cancelling" });
    expect(collectionFinishedLabel(snapshot({ state: "succeeded" }))).toBe("Collection QA finished");
    expect(collectionFinishedLabel(snapshot({ state: "cancelled" }))).toBe("Collection QA cancelled");
    expect(collectionFinishedLabel(snapshot({ state: "failed", error: "disk full" }))).toBe("Collection QA failed: disk full");
  });

  it("feeds the strip from each poll of the run and releases it with the outcome, never a frozen percent", async () => {
    const unbind = bindCollectionStrip();
    try {
      // Before the run the strip keeps whatever the last check job left (40%).
      expect(get(checkingProgress)).toMatchObject({ running: false, percent: 40 });

      collectionRunChecks.mockResolvedValue(snapshot({ completedBooks: 0, percent: 0, estimatedRemainingSeconds: null }));
      await startCollectionQa(false, ["languageQa"]);
      expect(get(collectionQaRunning)).toBe(true);
      expect(get(checkingProgress)).toMatchObject({ running: true, percent: 0, label: "Collection QA \u00b7 0/66 books", state: "running" });

      // The next poll moves the bar and the label; nothing else needs to happen.
      collectionQa.set(snapshot());
      expect(get(checkingProgress)).toMatchObject({ running: true, percent: 5, label: "Collection QA \u00b7 3/66 books \u00b7 about 40 min 0 s left" });

      collectionQa.set(snapshot({ state: "cancelling" }));
      expect(get(checkingProgress)).toMatchObject({ state: "cancelling", label: "Collection QA \u00b7 3/66 books \u00b7 cancelling" });

      collectionQa.set(snapshot({ state: "cancelled", finishedAt: "2026-10-28T10:00:00Z" }));
      collectionQaRunning.set(false);
      expect(get(checkingProgress)).toMatchObject({ running: false, label: "Collection QA cancelled", state: "succeeded" });
    } finally {
      unbind();
    }
  });

  it("routes the strip's Cancel to the collection job while one runs, else to the check job", async () => {
    const cancelCheckJob = vi.fn().mockResolvedValue(undefined);
    collectionCancelChecks.mockResolvedValue(snapshot({ state: "cancelling" }));

    expect(await cancelStripJob("", cancelCheckJob)).toBe("none");
    expect(cancelCheckJob).not.toHaveBeenCalled();

    expect(await cancelStripJob("job-7", cancelCheckJob)).toBe("checks");
    expect(cancelCheckJob).toHaveBeenCalledWith("job-7");
    expect(collectionCancelChecks).not.toHaveBeenCalled();

    collectionRunChecks.mockResolvedValue(snapshot());
    await startCollectionQa(false, ["languageQa"]);
    cancelCheckJob.mockClear();
    expect(await cancelStripJob("", cancelCheckJob)).toBe("collection");
    expect(collectionCancelChecks).toHaveBeenCalledOnce();
    expect(cancelCheckJob).not.toHaveBeenCalled();
    expect(get(collectionQa)?.state).toBe("cancelling");
  });
});
