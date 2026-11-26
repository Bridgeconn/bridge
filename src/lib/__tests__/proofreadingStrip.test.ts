import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

const api = vi.hoisted(() => ({
  proofreadingStatus: vi.fn(), proofreadingStart: vi.fn(), proofreadingCancel: vi.fn(), proofreadingPause: vi.fn(),
  collectionQaStatus: vi.fn(), collectionCancelChecks: vi.fn(),
}));

vi.mock("../api/bridgeClient", () => ({ bridge: api }));

import {
  bindCollectionStrip, cancelStripJob, proofreadingFinishedLabel, proofreadingStripProgress,
} from "../collectionStrip";
import {
  cancelProofreading, compactCount, pauseProofreading, proofreading, proofreadingRunning, startProofreading,
  stopProofreading,
} from "../proofreading";
import { checkingProgress } from "../stores";
import type { ProofreadingSnapshot } from "../types/proofreading";

function snapshot(overrides: Partial<ProofreadingSnapshot> = {}): ProofreadingSnapshot {
  return { jobId: "prj-1", state: "running", paused: false, stage: "Reading chapters 4 to 6", halted: false,
    collectionPath: "/p/gen", reference: "esv", totalBooks: 66, completedBooks: 3, percent: 4.6,
    currentBook: "lev", books: [], findings: 40, usage: {}, elapsedSeconds: 180, estimatedRemainingSeconds: 2400,
    error: null, createdAt: null, finishedAt: null, ...overrides };
}

// #505: a proofreading run holds the app as Collection QA does, through the
// same strip, and the strip's Cancel reaches it.
describe("the top strip during a proofreading run", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stopProofreading();
    checkingProgress.set({ running: false, percent: 40, label: "", jobId: "", state: "idle", error: "", scope: "chapter" });
  });

  it("says what the run is doing, or that it is paused or cancelling", () => {
    expect(proofreadingStripProgress(snapshot())).toEqual({
      running: true, percent: 5, label: "Proofreading · 3/66 books · Reading chapters 4 to 6", state: "running" });
    expect(proofreadingStripProgress(snapshot({ paused: true })).label).toBe("Proofreading · 3/66 books · paused");
    expect(proofreadingStripProgress(snapshot({ state: "cancelling" }))).toMatchObject({
      label: "Proofreading · 3/66 books · cancelling", state: "cancelling" });
  });

  it("says how a run stopped", () => {
    expect(proofreadingFinishedLabel(snapshot({ state: "succeeded" }))).toBe("Proofreading finished");
    expect(proofreadingFinishedLabel(snapshot({ state: "cancelled" }))).toBe("Proofreading cancelled");
    expect(proofreadingFinishedLabel(snapshot({ state: "failed", error: "Your ChatGPT plan limit has been reached." })))
      .toBe("Proofreading stopped: Your ChatGPT plan limit has been reached.");
  });

  it("holds the app while a run is active and lets go when it stops", async () => {
    api.proofreadingStart.mockResolvedValue(snapshot());
    const unbind = bindCollectionStrip();
    try {
      await startProofreading(null);
      expect(get(proofreadingRunning)).toBe(true);
      expect(get(checkingProgress)).toMatchObject({
        running: true, label: "Proofreading · 3/66 books · Reading chapters 4 to 6" });
      // A new snapshot moves the strip.
      proofreading.set(snapshot({ completedBooks: 4, stage: "Verifying every finding against the text" }));
      expect(get(checkingProgress).label).toBe("Proofreading · 4/66 books · Verifying every finding against the text");
      // The run ends: the hold is released with a line saying how.
      proofreading.set(snapshot({ state: "succeeded" }));
      proofreadingRunning.set(false);
      expect(get(checkingProgress)).toMatchObject({ running: false, label: "Proofreading finished" });
    } finally {
      unbind();
    }
  });

  it("sends the strip's Cancel to the proofreading run", async () => {
    api.proofreadingStart.mockResolvedValue(snapshot());
    api.proofreadingCancel.mockResolvedValue(snapshot({ state: "cancelling" }));
    await startProofreading(["gen"], true);
    expect(api.proofreadingStart).toHaveBeenCalledWith(["gen"], true);
    const cancelCheckJob = vi.fn();
    expect(await cancelStripJob("job-9", cancelCheckJob)).toBe("proofreading");
    expect(api.proofreadingCancel).toHaveBeenCalled();
    expect(cancelCheckJob).not.toHaveBeenCalled();
    stopProofreading();
    expect(await cancelStripJob("job-9", cancelCheckJob)).toBe("checks");
  });

  it("drops a Pause or Cancel answer that arrives after the project was closed", async () => {
    // Published late it would mark a run active with nothing polling it, and
    // the app would stay read-only.
    api.proofreadingStart.mockResolvedValue(snapshot());
    for (const [request, send] of [
      [api.proofreadingPause, () => pauseProofreading(true)],
      [api.proofreadingCancel, () => cancelProofreading()],
    ] as const) {
      await startProofreading(null);
      let answer: (value: ProofreadingSnapshot) => void = () => {};
      request.mockReturnValue(new Promise<ProofreadingSnapshot>((resolve) => { answer = resolve; }));
      const sent = send();
      stopProofreading();  // the project closes while the request is in flight
      answer(snapshot({ paused: true }));
      await sent;
      expect(get(proofreadingRunning)).toBe(false);
      expect(get(proofreading)).toBeNull();
    }
    // While the run is still held, the answer is published as before.
    await startProofreading(null);
    api.proofreadingPause.mockResolvedValue(snapshot({ paused: true }));
    await pauseProofreading(true);
    expect(get(proofreading)?.paused).toBe(true);
    stopProofreading();
  });

  it("shortens a token count for a status line", () => {
    expect([compactCount(950), compactCount(1200), compactCount(44000), compactCount(2_500_000), compactCount(undefined)])
      .toEqual(["950", "1.2k", "44k", "2.5M", "0"]);
  });
});
