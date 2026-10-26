import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { get } from "svelte/store";

const { paratextNotesForChapter } = vi.hoisted(() => ({ paratextNotesForChapter: vi.fn() }));
vi.mock("../api/bridgeClient", () => ({ bridge: { paratextNotesForChapter } }));

import { loadParatextNoteCounts, noteCountFor, verseAnchors } from "../paratextNotes";
import { currentChapter, paratextNoteCountsByVerse, project, verseKey } from "../stores";

const PROJECT = { path: "C:/p/jos", bookId: "jos", bookName: "Joshua", targetLanguage: "Tamil", tcVersion: "",
                  chapters: ["3"], checkTypes: {} };

function answer(state: string, counts: Record<string, { open: number; resolved: number }> = {}) {
  return { state, book: "JOS", chapter: "3", verses: {}, counts };
}

describe("paratextNotes (#357)", () => {
  beforeEach(() => {
    paratextNotesForChapter.mockReset();
    paratextNoteCountsByVerse.set({});
    project.set(PROJECT);
    currentChapter.set("3");
  });
  afterEach(() => {
    vi.useRealTimers();
    project.set(null);
  });

  it("covers every verse of a bridge", () => {
    expect(verseAnchors("4")).toEqual(["4"]);
    expect(verseAnchors("3-5")).toEqual(["3", "4", "5"]);
    expect(verseAnchors("4a")).toEqual(["4"]);
    expect(verseAnchors("")).toEqual([]);
    const counts = { [verseKey("3", "3")]: { open: 1, resolved: 0 }, [verseKey("3", "4")]: { open: 2, resolved: 1 } };
    expect(noteCountFor(counts, "3", "3-4")).toEqual({ open: 3, resolved: 1 });
    expect(noteCountFor(counts, "4", "4")).toEqual({ open: 0, resolved: 0 });
  });

  it("stores a chapter's counts under verseKey and replaces that chapter only", async () => {
    paratextNoteCountsByVerse.set({ [verseKey("3", "9")]: { open: 5, resolved: 0 }, [verseKey("2", "1")]: { open: 1, resolved: 0 } });
    paratextNotesForChapter.mockResolvedValue(answer("ready", { "4": { open: 3, resolved: 0 } }));
    await loadParatextNoteCounts("3");
    expect(get(paratextNoteCountsByVerse)).toEqual({
      [verseKey("2", "1")]: { open: 1, resolved: 0 }, [verseKey("3", "4")]: { open: 3, resolved: 0 },
    });
  });

  it("asks again while the index is building", async () => {
    vi.useFakeTimers();
    paratextNotesForChapter
      .mockResolvedValueOnce(answer("building"))
      .mockResolvedValueOnce(answer("ready", { "4": { open: 1, resolved: 0 } }));
    const done = loadParatextNoteCounts("3");
    await vi.advanceTimersByTimeAsync(2100);
    await done;
    expect(paratextNotesForChapter).toHaveBeenCalledTimes(2);
    expect(get(paratextNoteCountsByVerse)).toEqual({ [verseKey("3", "4")]: { open: 1, resolved: 0 } });
  });

  it("drops a late answer for a chapter the reviewer has left, and never throws", async () => {
    let resolve: (value: unknown) => void = () => {};
    paratextNotesForChapter.mockReturnValueOnce(new Promise((r) => (resolve = r)));
    const late = loadParatextNoteCounts("3");
    currentChapter.set("4");
    resolve(answer("ready", { "4": { open: 1, resolved: 0 } }));
    await late;
    expect(get(paratextNoteCountsByVerse)).toEqual({});

    paratextNotesForChapter.mockRejectedValueOnce(new Error("not linked"));
    await expect(loadParatextNoteCounts("4")).resolves.toBeUndefined();
    paratextNotesForChapter.mockResolvedValueOnce(answer("unavailable"));
    await loadParatextNoteCounts("4");
    expect(get(paratextNoteCountsByVerse)).toEqual({});
  });
});
