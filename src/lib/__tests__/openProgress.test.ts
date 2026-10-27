import { beforeEach, describe, expect, it } from "vitest";
import { get } from "svelte/store";

import { clearPrepare, prepareDetail, prepareProgress, trackPrepare } from "../openProgress";
import type { ImportJobSnapshot } from "../types/finding";

function snapshot(overrides: Partial<ImportJobSnapshot> = {}): ImportJobSnapshot {
  return {
    jobId: "prep-1", sourcePath: "", state: "running", phase: "normalize", phaseLabel: "Preparing PSA",
    totalBooks: 1, completedBooks: 0, currentBook: "psa", chapter: null, chapterCount: null, percent: 0,
    result: null, error: null, createdAt: "2026-10-28T09:00:00Z", finishedAt: null, ...overrides,
  };
}

describe("the prepare strip store (#400)", () => {
  beforeEach(() => clearPrepare());

  it("words a prepare snapshot the way the book switch does", () => {
    expect(prepareDetail(snapshot({ chapter: 3, chapterCount: 150 }))).toBe("preparing chapter 3 of 150");
    expect(prepareDetail(snapshot())).toBe("preparing");
    expect(prepareDetail(snapshot({ state: "succeeded", percent: 100 }))).toBe("");
  });

  it("puts the named book's prepare into the store and clears it", () => {
    const report = trackPrepare("Psalms");
    report(snapshot({ chapter: 12, chapterCount: 150, percent: 8 }));
    expect(get(prepareProgress)).toEqual({ name: "Psalms", detail: "preparing chapter 12 of 150" });
    report(snapshot({ state: "succeeded", percent: 100 }));
    expect(get(prepareProgress)).toEqual({ name: "Psalms", detail: "" });
    clearPrepare();
    expect(get(prepareProgress)).toBeNull();
  });
});
