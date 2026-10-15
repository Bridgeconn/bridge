import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * #210: `bridge.openProject` follows a "preparing" answer. The engine prepares
 * a never-opened sibling on a worker and answers at once; the client polls the
 * import job, reports its chapters to `onProgress`, and opens again when it has
 * succeeded. A cancelled or failed preparation rejects with plain words.
 */
const { tauriInvoke } = vi.hoisted(() => ({ tauriInvoke: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: tauriInvoke }));

import { bridge } from "../bridgeClient";
import type { ImportJobSnapshot } from "../../types/finding";

function job(overrides: Partial<ImportJobSnapshot> = {}): ImportJobSnapshot {
  return {
    jobId: "job-7", sourcePath: "C:/projects/psa", state: "running", phase: "normalize", phaseLabel: "Preparing PSA",
    totalBooks: 1, completedBooks: 0, currentBook: "psa", chapter: 12, chapterCount: 150, percent: 16,
    result: null, error: null, createdAt: "2026-10-14T18:00:00Z", finishedAt: null, ...overrides,
  };
}

function envelope(result: unknown) {
  return { id: "1", success: true, result };
}

const preparing = { state: "preparing", path: "C:/projects/psa", jobId: "job-7", job: job() };
const info = { path: "C:/projects/psa", bookId: "psa", bookName: "Psalms", chapters: ["1"] };

beforeEach(() => {
  tauriInvoke.mockReset();
});

describe("bridge.openProject with a book being prepared (#210)", () => {
  it("polls the job, reports chapters, and opens again once it has succeeded", async () => {
    tauriInvoke
      .mockResolvedValueOnce(envelope(preparing))
      .mockResolvedValueOnce(envelope(job({ chapter: 80, percent: 50 })))
      .mockResolvedValueOnce(envelope(job({ state: "succeeded", chapter: null, percent: 100, result: null })))
      .mockResolvedValueOnce(envelope(info));
    const chapters: Array<number | null> = [];

    const opened = await bridge.openProject("C:/projects/psa", undefined, (s) => chapters.push(s.chapter));

    expect(opened).toEqual(info);
    expect(chapters).toEqual([12, 80, null]);
    expect(tauriInvoke.mock.calls.map(([, args]) => (args as { method: string }).method)).toEqual([
      "project.open", "project.import.status", "project.import.status", "project.open",
    ]);
    expect(tauriInvoke.mock.calls[0][1]).toEqual({
      method: "project.open", params: { path: "C:/projects/psa", projectId: undefined, prepareInBackground: true },
    });
  });

  it("returns an already-prepared book without polling", async () => {
    tauriInvoke.mockResolvedValueOnce(envelope(info));
    await expect(bridge.openProject("C:/projects/psa")).resolves.toEqual(info);
    expect(tauriInvoke).toHaveBeenCalledTimes(1);
  });

  it("rejects a cancelled preparation in plain words", async () => {
    tauriInvoke
      .mockResolvedValueOnce(envelope(preparing))
      .mockResolvedValueOnce(envelope(job({ state: "cancelled" })));
    await expect(bridge.openProject("C:/projects/psa")).rejects.toThrow("Preparing the book was cancelled. Nothing was changed.");
  });

  it("rejects a failed preparation with the engine's error", async () => {
    tauriInvoke
      .mockResolvedValueOnce(envelope(preparing))
      .mockResolvedValueOnce(envelope(job({ state: "failed", error: "Deferred Scripture source is missing" })));
    await expect(bridge.openProject("C:/projects/psa")).rejects.toThrow("Deferred Scripture source is missing");
  });
});
