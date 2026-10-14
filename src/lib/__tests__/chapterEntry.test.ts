import { describe, expect, it } from "vitest";
import { planChapterEntry, shouldReadStored } from "../chapterEntry";
import { DEFAULT_EDITOR_CHECKS, groupsOf, type CheckBoxId } from "../checkSelection";
import type { StoredChapterFindings } from "../types/finding";

// #272: entering a chapter reads the stored findings back instead of
// re-running the chapter job when they still describe it.
const idle = { loaded: false, jobActive: false, collectionRunning: false };
const selection = [...DEFAULT_EDITOR_CHECKS] as CheckBoxId[];
const stored = (current: boolean, checks: readonly string[]): StoredChapterFindings => ({
  chapter: "1", current, checkGroups: groupsOf(checks), verses: { "1": [] },
});

describe("chapter entry", () => {
  it("a current snapshot covering the selection starts no job", () => {
    expect(planChapterEntry(idle, stored(true, selection), selection)).toEqual({ kind: "stored", run: [] });
  });

  it("a current snapshot runs only the selected checks it lacks", () => {
    const plan = planChapterEntry(idle, stored(true, ["tN", "tW", "alignment"]), selection);
    expect(plan).toEqual({ kind: "stored", run: ["text", "languageQa"] });
  });

  it("a stale snapshot, none, or a failed read runs the chapter job with the selection", () => {
    expect(planChapterEntry(idle, stored(false, selection), selection)).toEqual({ kind: "job", run: selection });
    expect(planChapterEntry(idle, null, selection)).toEqual({ kind: "job", run: selection });
  });

  it("nothing happens while a job or Collection QA runs, or once the chapter is loaded", () => {
    for (const state of [{ ...idle, jobActive: true }, { ...idle, collectionRunning: true }, { ...idle, loaded: true }]) {
      expect(shouldReadStored(state)).toBe(false);
      expect(planChapterEntry(state, stored(false, selection), selection)).toEqual({ kind: "nothing" });
    }
  });
});
