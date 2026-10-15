import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { tick } from "svelte";

const { getAlignmentRange, getAlignment } = vi.hoisted(() => ({
  getAlignmentRange: vi.fn(),
  getAlignment: vi.fn(),
}));
vi.mock("../../api/bridgeClient", () => ({ bridge: { getAlignmentRange, getAlignment } }));

import SourceTextPanel from "../SourceTextPanel.svelte";
import { clearSourceCache, sourceVerseOf } from "../../sourceText";
import {
  alignmentRevisionByVerse, alignmentStatusByVerse, chapterVerseNums, currentChapter, noteAlignmentChanged, project,
  selectedVerse,
} from "../../stores";
import type { AlignmentContext } from "../../types/finding";

// PSA 23:1 in the UHB, as alignment.getRange returns it: three source words,
// the first two aligned, the third not yet.
function context(verse: string, aligned: boolean, direction: "rtl" | "ltr" = "rtl"): AlignmentContext {
  return {
    chapter: "23", verse, sourceAvailable: true, sourceMessage: "", sourceDirection: direction, targetDirection: "ltr",
    topTokens: [
      { id: "H001", word: "מִזְמ֥וֹר", lemma: "מִזְמוֹר", strong: "H4210", occurrence: 1, occurrences: 1 },
      { id: "H002", word: "לְ⁠דָוִ֑ד", lemma: "דָּוִד", strong: "l:H1732", occurrence: 1, occurrences: 1 },
      { id: "H003", word: "יְהוָ֥ה", lemma: "יְהֹוָה", strong: "H3068", occurrence: 1, occurrences: 1 },
    ],
    bottomTokens: [
      { id: "T001", word: "தாவீதின்", occurrence: 1, occurrences: 1 },
      { id: "T002", word: "சங்கீதம்", occurrence: 1, occurrences: 1 },
      { id: "T003", word: "யெகோவா", occurrence: 1, occurrences: 1 },
    ],
    groups: aligned
      ? [{ id: "g1", topIds: ["H001"], bottomIds: ["T002"] }, { id: "g2", topIds: ["H002"], bottomIds: ["T001"] },
         { id: "g3", topIds: ["H003"], bottomIds: ["T003"] }]
      : [{ id: "g1", topIds: ["H001"], bottomIds: ["T002"] }, { id: "g2", topIds: ["H002"], bottomIds: ["T001"] }],
  } as unknown as AlignmentContext;
}

describe("sourceVerseOf", () => {
  it("keeps the source words and the target words each is aligned to", () => {
    const verse = sourceVerseOf(context("1", false));
    expect(verse.direction).toBe("rtl");
    expect(verse.words.map((w) => [w.word, w.targets])).toEqual([
      ["מִזְמ֥וֹר", ["சங்கீதம்"]], ["לְ⁠דָוִ֑ד", ["தாவீதின்"]], ["יְהוָ֥ה", []],
    ]);
  });
});

describe("SourceTextPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearSourceCache();
    project.set({ path: "/p", bookId: "psa" } as never);
    chapterVerseNums.set({ "23": ["1", "2"] });
    currentChapter.set("23");
    selectedVerse.set("1");
    alignmentStatusByVerse.set({});
    alignmentRevisionByVerse.set({});
    getAlignmentRange.mockResolvedValue({ chapter: "23", verses: [context("1", false), context("2", true)] });
  });

  afterEach(() => selectedVerse.set(null));

  it("shows the chapter right to left, marks the unaligned word, and selects a verse on click", async () => {
    const onSelectVerse = vi.fn();
    render(SourceTextPanel, { props: { onSelectVerse } });
    expect(await screen.findByText("Source · Hebrew / Aramaic")).toBeTruthy();
    expect(getAlignmentRange).toHaveBeenCalledWith("23", ["1", "2"]);
    const text = document.querySelector('[data-source-verse="1"] .text') as HTMLElement;
    expect(text.getAttribute("dir")).toBe("rtl");
    expect(text.classList.contains("rtl")).toBe(true);
    const words = [...text.querySelectorAll(".w")];
    expect(words.map((w) => w.textContent)).toEqual(["מִזְמ֥וֹר", "לְ⁠דָוִ֑ד", "יְהוָ֥ה"]);
    expect(words.map((w) => w.classList.contains("unaligned"))).toEqual([false, false, true]);
    expect(words[0].getAttribute("title")).toContain("Aligned to: சங்கீதம்");
    expect(screen.getByText("2 of 3 source words aligned")).toBeTruthy();
    expect(document.querySelector('[data-source-verse="1"]')?.classList.contains("current")).toBe(true);
    await fireEvent.click(screen.getByRole("button", { name: /Verse 2 in the source/ }));
    expect(onSelectVerse).toHaveBeenCalledWith("2");
  });

  it("draws a chapter it has read before at once, without asking the engine again (Tier A)", async () => {
    const first = render(SourceTextPanel);
    await screen.findByText("Source · Hebrew / Aramaic");
    first.unmount();
    render(SourceTextPanel);
    // Present on the first render, before any promise settles.
    expect(document.querySelector('[data-source-verse="1"] .text')).toBeTruthy();
    expect(getAlignmentRange).toHaveBeenCalledTimes(1);
  });

  // #291: the panel re-reads a verse when its alignment is written, not when
  // its status moves. Most edits leave the status as it was.
  it("reads one verse again when its alignment is written and the status stays the same", async () => {
    alignmentStatusByVerse.set({ "23:1": "partial", "23:2": "complete" });
    render(SourceTextPanel);
    await screen.findByText("Source · Hebrew / Aramaic");
    expect(screen.getByText("2 of 3 source words aligned")).toBeTruthy();
    // One more word aligned in 23:1; the verse is still partial.
    getAlignment.mockResolvedValue(context("1", true));
    noteAlignmentChanged("23:1");
    await waitFor(() => expect(getAlignment).toHaveBeenCalledWith("23", "1"));
    await waitFor(() => expect(screen.getByText("3 of 3 source words aligned")).toBeTruthy());
    expect(getAlignment).toHaveBeenCalledTimes(1);
    expect(getAlignmentRange).toHaveBeenCalledTimes(1);
  });

  it("does not read a verse again when only its status arrives or moves", async () => {
    render(SourceTextPanel);
    await screen.findByText("Source · Hebrew / Aramaic");
    alignmentStatusByVerse.set({ "23:1": "partial", "23:2": "complete" });
    await tick();
    alignmentStatusByVerse.set({ "23:1": "complete", "23:2": "complete" });
    await tick();
    await tick();
    expect(getAlignment).not.toHaveBeenCalled();
  });

  it("re-reads a verse written while the column was closed, and keeps the rest of the chapter", async () => {
    const first = render(SourceTextPanel);
    await screen.findByText("Source · Hebrew / Aramaic");
    first.unmount();
    getAlignment.mockResolvedValue(context("1", true));
    noteAlignmentChanged("23:1");
    render(SourceTextPanel);
    await waitFor(() => expect(getAlignment).toHaveBeenCalledWith("23", "1"));
    await waitFor(() => expect(screen.getByText("3 of 3 source words aligned")).toBeTruthy());
    expect(getAlignment).toHaveBeenCalledTimes(1);
    expect(getAlignmentRange).toHaveBeenCalledTimes(1);
  });

  it("reads a verse once per write, even when the write is noted twice before the read lands", async () => {
    render(SourceTextPanel);
    await screen.findByText("Source · Hebrew / Aramaic");
    let release: (value: AlignmentContext) => void = () => {};
    getAlignment.mockReturnValueOnce(new Promise<AlignmentContext>((resolve) => { release = resolve; }));
    getAlignment.mockResolvedValue(context("1", true));
    noteAlignmentChanged("23:1");
    await waitFor(() => expect(getAlignment).toHaveBeenCalledTimes(1));
    // A second write while the first read is in flight: the verse is read
    // again for the newer revision, not a third time.
    noteAlignmentChanged("23:1");
    release(context("1", false));
    await waitFor(() => expect(screen.getByText("3 of 3 source words aligned")).toBeTruthy());
    await tick();
    expect(getAlignment).toHaveBeenCalledTimes(2);
  });

  it("uses the Greek face left to right for a New Testament chapter", async () => {
    getAlignmentRange.mockResolvedValue({ chapter: "23", verses: [context("1", true, "ltr")] });
    chapterVerseNums.set({ "23": ["1"] });
    render(SourceTextPanel);
    expect(await screen.findByText("Source · Greek")).toBeTruthy();
    const text = document.querySelector('[data-source-verse="1"] .text') as HTMLElement;
    expect(text.getAttribute("dir")).toBe("ltr");
    expect(text.classList.contains("rtl")).toBe(false);
  });

  it("says so when the chapter has no source text", async () => {
    getAlignmentRange.mockResolvedValue({ chapter: "23", verses: [
      { ...context("1", false), sourceAvailable: false, sourceMessage: "No UHB text for this verse.", topTokens: [] }] });
    chapterVerseNums.set({ "23": ["1"] });
    render(SourceTextPanel);
    expect(await screen.findByText("No UHB text for this verse.")).toBeTruthy();
  });
});
