import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * #242: `bridge.autoAlignWindow` is the window-scoped background job, not a
 * blocking call. These tests pin what it sends (scope "window", one chapter,
 * the verses) and how it reads the job: pass numbers go to `onProgress`, a
 * succeeded job yields its `windowResult`, no key yields `unavailable` without
 * polling, and a cancelled job rejects.
 */
const { tauriInvoke } = vi.hoisted(() => ({ tauriInvoke: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: tauriInvoke }));

import { bridge } from "../bridgeClient";
import type { AutoAlignJobStatus, AutoAlignWindowResult } from "../../types/finding";

function status(overrides: Partial<AutoAlignJobStatus> = {}): AutoAlignJobStatus {
  return {
    jobId: "aaj-1", scope: "window", apply: true, state: "running", stage: "Asking about 1:1-2 (pass 1 of 2)",
    chapters: ["1"], windowsTotal: 1, windowsDone: 0, windowsFailed: 0, percent: 0,
    currentWindow: { chapter: "1", verses: ["1", "2"] },
    currentPass: { number: 1, of: 2, direction: "source-first", stage: "" },
    windowResult: null, verdictCounts: {}, verdicts: {}, usage: { calls: 0, totalTokens: 0, estimatedCostUSD: 0 },
    error: null, unavailable: null, resumeOf: "", createdAt: "2026-10-14T09:00:00Z", finishedAt: null,
    ...overrides,
  };
}

const windowResult: AutoAlignWindowResult = {
  chapter: "1", verses: ["1", "2"], runId: "aa-1", calibrationVersion: "agreement-v1", results: [],
  usage: { calls: 2, totalTokens: 300, estimatedCostUSD: 0.01 },
};

function envelope(result: unknown) {
  return { id: "1", success: true, result };
}

beforeEach(() => {
  tauriInvoke.mockReset();
});

describe("bridge.autoAlignWindow as the window job (#242)", () => {
  it("starts a window-scoped job, reports each pass, and returns the window result", async () => {
    tauriInvoke
      .mockResolvedValueOnce(envelope(status()))
      .mockResolvedValueOnce(envelope(status({ currentPass: { number: 2, of: 2, direction: "target-first", stage: "" } })))
      .mockResolvedValueOnce(envelope(status({ state: "succeeded", currentPass: null, windowResult, windowsDone: 1, percent: 100 })));
    const passes: Array<number | null> = [];

    const result = await bridge.autoAlignWindow("1", ["1", "2"], true, (snapshot) => {
      passes.push(snapshot.currentPass?.number ?? null);
    });

    expect(tauriInvoke.mock.calls[0]).toEqual(["engine_call", {
      method: "alignment.autoAlign.start",
      params: { scope: "window", chapters: ["1"], verses: ["1", "2"], apply: true },
    }]);
    expect(tauriInvoke.mock.calls[1]).toEqual(["engine_call", { method: "alignment.autoAlign.status", params: { jobId: "aaj-1" } }]);
    expect(passes).toEqual([1, 2, null]);
    expect(result).toEqual(windowResult);
  });

  it("returns unavailable without polling when no provider is configured", async () => {
    tauriInvoke.mockResolvedValueOnce(envelope({
      state: "failed", unavailable: { reason: "no-api-key", message: "No API key is configured." },
    }));

    const result = await bridge.autoAlignWindow("1", ["1", "2"]);

    expect(result.unavailable).toEqual({ reason: "no-api-key", message: "No API key is configured." });
    expect(result.results).toEqual([]);
    expect(tauriInvoke).toHaveBeenCalledTimes(1);
  });

  it("rejects a cancelled job and says nothing was written", async () => {
    tauriInvoke
      .mockResolvedValueOnce(envelope(status()))
      .mockResolvedValueOnce(envelope(status({ state: "cancelled", currentPass: null })));

    await expect(bridge.autoAlignWindow("1", ["1", "2"])).rejects.toThrow(/cancelled.*Nothing was written/);
  });

  it("rejects a failed job with the engine's error", async () => {
    tauriInvoke
      .mockResolvedValueOnce(envelope(status()))
      .mockResolvedValueOnce(envelope(status({ state: "failed", currentPass: null, error: "1 window(s) failed." })));

    await expect(bridge.autoAlignWindow("1", ["1", "2"])).rejects.toThrow("1 window(s) failed.");
  });
});
