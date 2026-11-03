import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

const { chapterVerseData } = vi.hoisted(() => ({ chapterVerseData: vi.fn() }));
vi.mock("../api/bridgeClient", () => ({ bridge: { chapterVerseData } }));
import { refreshParatextReviewEditor } from "../paratextReviewRefresh";
import { alignmentRevisionByVerse, alignmentStatusByVerse, headingsByVerse, historyCountByVerse,
  languageQaFindingsByVerse, project, resetBookState, verseDisplay, verseKey, verseTexts } from "../stores";
import type { ParatextReviewDecision } from "../types/paratext";

const decision = (extra: Partial<ParatextReviewDecision> = {}) => ({
  book: "TIT", chapter: "1", verse: "3-4", region: "body", decision: "applied", ...extra,
} as ParatextReviewDecision);
const key = verseKey("1", "3-4");
const display = { plain: "Saved body.", removed: [], notes: [], styles: [], warnings: [] };
const saved = { chapter: "1", headings: { "3-4": [{ tag: "s2", text: "Saved heading" }] },
  editCounts: { "3-4": 7 }, verses: { "3-4": { text: "Saved body.", display, alignmentStatus: "partial" } } };

describe("Paratext review editor refresh (#445)", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    resetBookState();
    project.set({ path: "/p/tit", bookId: "tit" } as never);
    verseTexts.set({ [key]: "Old body.", [verseKey("2", "3-4")]: "Other chapter." });
    verseDisplay.set({ [key]: { ...display, plain: "Old body." } });
    languageQaFindingsByVerse.set({ [key]: [{}] as never });
    chapterVerseData.mockResolvedValue(saved);
  });

  it("reads saved raw/display data, clears stale marks and refreshes edit/alignment readers for exact verse bridges", async () => {
    await refreshParatextReviewEditor("/p/tit", decision({ region: "footnote" }));
    expect(chapterVerseData).toHaveBeenCalledWith("1");
    expect(get(verseTexts)[key]).toBe("Saved body.");
    expect(get(verseTexts)[verseKey("2", "3-4")]).toBe("Other chapter.");
    expect(get(verseDisplay)[key]).toEqual(display);
    expect(get(languageQaFindingsByVerse)[key]).toBeUndefined();
    expect(get(historyCountByVerse)[key]).toBe(7);
    expect(get(alignmentStatusByVerse)[key]).toBe("partial");
    expect(get(alignmentRevisionByVerse)[key]).toBe(1);
  });

  it("refreshes heading-only writes without changing body text or its alignment", async () => {
    alignmentStatusByVerse.set({ [key]: "complete" });
    await refreshParatextReviewEditor("/p/tit", decision({ region: "structure", bridgeCopy: "heading" }));
    expect(get(headingsByVerse)[key]).toEqual(saved.headings["3-4"]);
    expect(get(verseTexts)[key]).toBe("Old body.");
    expect(get(alignmentStatusByVerse)[key]).toBe("complete");
    expect(get(alignmentRevisionByVerse)[key]).toBeUndefined();
  });

  it("discards a response after another project with the same book becomes active", async () => {
    let finish!: (value: typeof saved) => void;
    chapterVerseData.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const refreshing = refreshParatextReviewEditor("/p/tit", decision());
    project.set({ path: "/other/tit", bookId: "tit" } as never);
    verseTexts.set({ [key]: "Other project's text." });
    finish(saved);
    await refreshing;
    expect(get(verseTexts)[key]).toBe("Other project's text.");
    expect(get(headingsByVerse)[key]).toBeUndefined();
  });

  it("does not read another book or an introduction Bridge does not keep", async () => {
    await refreshParatextReviewEditor("/p/tit", decision({ book: "PHM" }));
    await refreshParatextReviewEditor("/p/tit", decision({ region: "introduction", bridgeCopy: "none" }));
    expect(chapterVerseData).not.toHaveBeenCalled();
  });
});
