import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";

import AlignmentModal from "../AlignmentModal.svelte";
// @ts-expect-error Vite's test-only raw loader is not part of the app tsconfig.
import alignmentModalSource from "../AlignmentModal.svelte?raw";
import { get } from "svelte/store";
import { alignmentRevisionByVerse, project, verseDisplay, verseKey } from "../../stores";
import type { AlignmentContext, AlignmentToken, ProjectInfo } from "../../types/finding";

const {
  getAlignment, realignWords, unalignWords, undoAlignment, restoreAlignment, runVerseChecks, getLexiconEntry, getVerse,
} = vi.hoisted(() => ({
  getAlignment: vi.fn(),
  getVerse: vi.fn(),
  realignWords: vi.fn(),
  unalignWords: vi.fn(),
  undoAlignment: vi.fn(),
  restoreAlignment: vi.fn(),
  runVerseChecks: vi.fn(),
  getLexiconEntry: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: {
    getAlignment, realignWords, unalignWords, undoAlignment, restoreAlignment, runVerseChecks, getLexiconEntry, getVerse,
  },
}));

function token(id: string, word: string, extra: Partial<AlignmentToken> = {}): AlignmentToken {
  return { id, word, occurrence: 1, occurrences: 1, ...extra };
}

/** Genesis 1:1-shaped: two source words, three target words, one pair aligned. */
function context(extra: Partial<AlignmentContext> = {}): AlignmentContext {
  const topTokens = [token("H001", "בְּרֵאשִׁית", { lemma: "רֵאשִׁית" }), token("H002", "בָּרָא")];
  const bottomTokens = [token("T001", "आदि"), token("T002", "में"), token("T003", "सृष्टि")];
  return {
    chapter: "1", verse: "1",
    alignment: {
      alignments: [
        { topWords: [topTokens[0]], bottomWords: [bottomTokens[0]] },
        { topWords: [topTokens[1]], bottomWords: [] },
      ],
      wordBank: [bottomTokens[1], bottomTokens[2]],
    },
    topTokens,
    bottomTokens,
    groups: [
      { id: "G001", topIds: ["H001"], bottomIds: ["T001"] },
      { id: "G002", topIds: ["H002"], bottomIds: [] },
    ],
    status: "partial",
    completionState: "pending",
    sourceAvailable: true, sourceMessage: "",
    sourceDirection: "rtl", targetDirection: "ltr",
    issues: [], canComplete: false, history: [],
    // 0 + 3 + 28 = 31, Genesis 1's verse count -- the tally is per verse.
    chapterStatus: { complete: 0, complete_cross_verse: 0, partial: 3, untouched: 28, invalid: 0 },
    gaps: { sourceUnmatched: 1, targetUnmatched: 2 },
    crossVerseLinks: [],
    crossVerseGroups: [],
    crossVerseAccountedIds: [],
    crossVerseRealizedIds: [],
    crossVerseAccounted: 0,
    crossVerseRealized: 0,
    fullyAccounted: false,
    nullDecisions: { source: [], target: [] },
    accountedBy: { tc: 0, crossVerse: 0, null: 0 },
    accounted: false,
    ...extra,
  };
}

function projectInfo(extra: Partial<ProjectInfo> = {}): ProjectInfo {
  return {
    path: "C:/projects/gen", bookId: "gen", bookName: "Genesis", chapters: ["1"], ...extra,
  } as ProjectInfo;
}

/** Renders and waits out the async load in onMount. */
async function open(ctx: AlignmentContext = context()) {
  getAlignment.mockResolvedValue(ctx);
  const result = render(AlignmentModal, { props: { chapter: "1", verse: "1", onClose: vi.fn() } });
  await screen.findByText(/align source and target words/);
  return result;
}

describe("AlignmentModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    project.set(projectInfo());
    verseDisplay.set({});
    getLexiconEntry.mockResolvedValue({ segments: [] });
    runVerseChecks.mockResolvedValue([]);
    getVerse.mockResolvedValue({ chapter: "1", verse: "1", text: "", display: { plain: "", notes: [], removed: [], styles: [], warnings: [] } });
  });

  // #409: the reading area shows the verse's display text, continuous and
  // with its punctuation, and a drop does not change it.
  it("reads the full target verse with its punctuation from the display text", async () => {
    verseDisplay.set({ [verseKey("1", "1")]: { plain: "ஆதியிலே தேவன் வானத்தையும் பூமியையும் சிருஷ்டித்தார்.", notes: [], removed: [], styles: [], warnings: [] } });
    await open();
    const reading = screen.getByRole("region", { name: "Read Genesis (GEN) 1:1" });
    expect(reading).toHaveTextContent("ஆதியிலே தேவன் வானத்தையும் பூமியையும் சிருஷ்டித்தார்.");
    expect(getVerse).not.toHaveBeenCalled();
    realignWords.mockResolvedValue(context());
    await fireEvent.click(screen.getByRole("button", { name: "Pick up आदि from בְּרֵאשִׁית" }));
    expect(reading).toHaveTextContent("ஆதியிலே தேவன் வானத்தையும் பூமியையும் சிருஷ்டித்தார்.");
  });

  it("reads the verse once from the engine when the chapter has not been loaded", async () => {
    getVerse.mockResolvedValue({ chapter: "1", verse: "1", text: "In the beginning, God created.", display: { plain: "In the beginning, God created.", notes: [], removed: [], styles: [], warnings: [] } });
    await open();
    await waitFor(() => expect(screen.getByRole("region", { name: "Read Genesis (GEN) 1:1" })).toHaveTextContent("In the beginning, God created."));
    expect(getVerse).toHaveBeenCalledWith("1", "1");
  });

  it("names the book and its code in the title", async () => {
    await open();
    expect(screen.getByRole("heading", { name: /^Genesis \(GEN\) 1:1 — align source and target words$/ }))
      .toBeInTheDocument();
  });

  it("does not repeat the book id as its own name", async () => {
    // bookName falls back to the raw book id when the tC manifest has no
    // project.name, and "gen (GEN)" would be nonsense.
    project.set(projectInfo({ bookName: "gen" }));
    await open();
    expect(screen.getByRole("heading", { name: /^GEN 1:1 — align source and target words$/ })).toBeInTheDocument();
  });

  it("says the tally counts this chapter's verses", async () => {
    await open();
    const tally = screen.getByText(/31 verses/);
    expect(tally).toHaveTextContent("Chapter 1 — 31 verses:");
    expect(tally).toHaveTextContent("0 complete");
    expect(tally).toHaveTextContent("3 partial");
    expect(tally).toHaveTextContent("28 untouched");
  });

  it("shows the unaligned count as a chip, not a banner", async () => {
    await open();
    expect(screen.getByText("2 remaining")).toBeInTheDocument();
    expect(screen.queryByText(/Not fully aligned/)).not.toBeInTheDocument();
  });

  it("shows cross-verse linked words as their own chip", async () => {
    await open(context({ crossVerseAccounted: 2, crossVerseRealized: 0, crossVerseAccountedIds: ["T002", "T003"] }));
    const chip = screen.getByText(/2 linked across verses/);
    expect(chip).toHaveAttribute("title", expect.stringContaining("completion stays with translationCore"));
  });

  it("headings name both word banks", async () => {
    await open();
    expect(screen.getByText("Source words")).toBeInTheDocument();
    expect(screen.getByText("Target words")).toBeInTheDocument();
  });

  it("keeps structural issues behind a button until asked for", async () => {
    const issue = "2 alignment group(s) contain non-adjacent target words; aligned USFM requires each target span to be contiguous.";
    await open(context({ issues: [issue] }));

    const button = screen.getByRole("button", { name: "⚠ 1 issue" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(`⚠ ${issue}`)).not.toBeInTheDocument();

    await fireEvent.click(button);
    expect(screen.getByText(`⚠ ${issue}`)).toBeInTheDocument();
    expect(button).toHaveAttribute("aria-expanded", "true");

    await fireEvent.click(button);
    expect(screen.queryByText(`⚠ ${issue}`)).not.toBeInTheDocument();
  });

  it("reveals the issues on hover too", async () => {
    const issue = "1 target token(s) occur more than once in alignment data.";
    await open(context({ issues: [issue] }));
    const wrap = screen.getByRole("button", { name: "⚠ 1 issue" }).parentElement!;

    await fireEvent.mouseEnter(wrap);
    expect(screen.getByText(`⚠ ${issue}`)).toBeInTheDocument();
    await fireEvent.mouseLeave(wrap);
    expect(screen.queryByText(`⚠ ${issue}`)).not.toBeInTheDocument();
  });

  it("calls the invalid flag what it is", async () => {
    // #149: this is the translationCore marker, not the issues list.
    await open(context({ status: "invalid" }));
    expect(screen.getByText("⚑ Marked invalid in translationCore.")).toBeInTheDocument();
  });

  it("still aligns a word bank item into a column by click", async () => {
    const ctx = context();
    realignWords.mockResolvedValue(ctx);
    await open(ctx);

    await fireEvent.click(screen.getByRole("button", { name: "में" }));
    await fireEvent.click(screen.getByLabelText("Align picked-up word to בָּרָא"));

    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "1", ["H002"], ["T002"], ctx.alignment));
    // The save is announced as a write (#291), although the status is still "partial".
    await waitFor(() => expect(get(alignmentRevisionByVerse)["1:1"]).toBe(1));
  });
});

/** The text of one CSS rule block, by selector, from a component's source. */
function rule(source: string, selector: string): string {
  const match = source.match(new RegExp(`\\${selector}\\s*{([^}]*)}`));
  return match?.[1] ?? "";
}

describe("AlignmentModal layout", () => {
  // jsdom neither lays out nor paints, so this asserts on the rules themselves
  // (the pattern QaFindingDetail.test.ts uses). It guards #72: the interlinear
  // wraps instead of scrolling sideways, and that was not bought by letting the
  // columns squash.
  it("wraps the interlinear instead of scrolling it sideways", () => {
    const interlinear = rule(alignmentModalSource, ".interlinear");
    expect(interlinear).toMatch(/flex-wrap:\s*wrap/);
    expect(interlinear).toMatch(/overflow-x:\s*hidden/);
    expect(interlinear).not.toMatch(/overflow-x:\s*(auto|scroll)/);
  });

  it("caps the wrapped block so the word bank stays on screen", () => {
    const interlinear = rule(alignmentModalSource, ".interlinear");
    expect(interlinear).toMatch(/max-height:/);
    expect(interlinear).toMatch(/overflow-y:\s*auto/);
  });

  it("keeps the columns unsqueezable", () => {
    expect(rule(alignmentModalSource, ".column")).toMatch(/flex-shrink:\s*0/);
  });
});

describe("AlignmentModal joined columns (#207) and Undo (#122)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    project.set(projectInfo());
    getLexiconEntry.mockResolvedValue({ segments: [] });
    runVerseChecks.mockResolvedValue([]);
  });

  /** Both source words in one group with the joined target word. */
  function joined(extra: Partial<AlignmentContext> = {}): AlignmentContext {
    const base = context();
    return context({
      alignment: {
        alignments: [{ topWords: base.topTokens, bottomWords: [base.bottomTokens[0]] }],
        wordBank: [base.bottomTokens[1], base.bottomTokens[2]],
      },
      groups: [{ id: "G001", topIds: ["H001", "H002"], bottomIds: ["T001"] }],
      ...extra,
    });
  }

  it("draws a group with two source words as one column, not two columns with the same targets", async () => {
    await open(joined());
    expect(screen.getAllByLabelText(/^Target words aligned to/)).toHaveLength(1);
    expect(screen.getByLabelText("Target words aligned to בְּרֵאשִׁית בָּרָא")).toBeInTheDocument();
    expect(document.querySelectorAll(".aligned-card")).toHaveLength(1);
  });

  it("a drop on a joined column keeps every source word in the group", async () => {
    const ctx = joined();
    realignWords.mockResolvedValue(ctx);
    await open(ctx);
    await fireEvent.click(screen.getByRole("button", { name: "में" }));
    await fireEvent.click(screen.getByLabelText("Align picked-up word to בְּרֵאשִׁית בָּרָא"));
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "1", ["H001", "H002"], ["T001", "T002"], ctx.alignment));
  });

  it("Join folds a source word into the previous column, with the targets of both", async () => {
    const ctx = context();
    realignWords.mockResolvedValue(ctx);
    await open(ctx);
    await fireEvent.click(screen.getByRole("button", { name: "Join בָּרָא with the previous source word" }));
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "1", ["H001", "H002"], ["T001"], ctx.alignment));
  });

  it("Join is disabled while neither column has a target word, because the engine needs one", async () => {
    const ctx = context({
      alignment: { alignments: [], wordBank: context().bottomTokens },
      groups: [],
    });
    await open(ctx);
    expect(screen.getByRole("button", { name: "Join בָּרָא with the previous source word" })).toBeDisabled();
    expect(realignWords).not.toHaveBeenCalled();
  });

  it("Split takes the last source word out of a joined column", async () => {
    const ctx = joined();
    realignWords.mockResolvedValue(ctx);
    await open(ctx);
    await fireEvent.click(screen.getByRole("button", { name: "Split בָּרָא out of this column" }));
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "1", ["H001"], ["T001"], ctx.alignment));
  });

  it("Undo walks back through the edits instead of toggling the newest backup", async () => {
    const history = [
      { id: "h3-restore", operation: "restore", timestamp: "t3" },
      { id: "h2-realign", operation: "realign", timestamp: "t2" },
      { id: "h1-realign", operation: "realign", timestamp: "t1" },
    ];
    const ctx = context({ history });
    restoreAlignment.mockResolvedValue(ctx);
    await open(ctx);
    // One undo already happened (the restore row): the next press restores the older edit's backup.
    await fireEvent.click(screen.getByRole("button", { name: "Undo last change" }));
    await waitFor(() => expect(restoreAlignment).toHaveBeenCalledWith("1", "1", "h1-realign", ctx.alignment));
    expect(undoAlignment).not.toHaveBeenCalled();
  });

  it("Undo restores the newest edit when nothing has been undone yet, and is disabled when everything has", async () => {
    const fresh = context({ history: [
      { id: "h2-realign", operation: "realign", timestamp: "t2" },
      { id: "h1-realign", operation: "realign", timestamp: "t1" },
    ] });
    restoreAlignment.mockResolvedValue(fresh);
    const first = await open(fresh);
    await fireEvent.click(screen.getByRole("button", { name: "Undo last change" }));
    await waitFor(() => expect(restoreAlignment).toHaveBeenCalledWith("1", "1", "h2-realign", fresh.alignment));
    first.unmount();
    await open(context({ history: [
      { id: "h4-restore", operation: "restore", timestamp: "t4" },
      { id: "h3-restore", operation: "restore", timestamp: "t3" },
      { id: "h2-realign", operation: "realign", timestamp: "t2" },
      { id: "h1-realign", operation: "realign", timestamp: "t1" },
    ] }));
    expect(screen.getByRole("button", { name: "Undo last change" })).toBeDisabled();
  });
});

describe("AlignmentModal several target words at once (#285)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    project.set(projectInfo());
    getLexiconEntry.mockResolvedValue({ segments: [] });
    runVerseChecks.mockResolvedValue([]);
  });

  /** Nothing aligned yet: three bank words, two empty source columns. */
  function untouched(): AlignmentContext {
    return context({
      alignment: { alignments: [], wordBank: context().bottomTokens },
      groups: [],
      status: "untouched",
    });
  }

  type HitTest = { elementFromPoint: (x: number, y: number) => Element | null };

  /** jsdom has no PointerEvent; a MouseEvent under the pointer name carries
   *  the button and coordinates alignmentDrag reads. */
  function pointer(type: string, target: Element | Window, init: MouseEventInit = {}) {
    target.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, ...init }));
  }

  it("Ctrl-click picks several bank words; one click on a column places them in one save, in verse order", async () => {
    const ctx = untouched();
    realignWords.mockResolvedValue(ctx);
    await open(ctx);
    await fireEvent.click(screen.getByRole("button", { name: "सृष्टि" }));
    await fireEvent.click(screen.getByRole("button", { name: "आदि" }), { ctrlKey: true });
    expect(screen.getByRole("button", { name: "सृष्टि" }).classList.contains("picked")).toBe(true);
    expect(screen.getByRole("button", { name: "आदि" }).classList.contains("picked")).toBe(true);
    expect(screen.getByRole("status")).toHaveTextContent("2 picked");
    await fireEvent.click(screen.getByLabelText("Align 2 picked-up words to בָּרָא"));
    await waitFor(() => expect(realignWords).toHaveBeenCalledTimes(1));
    expect(realignWords).toHaveBeenCalledWith("1", "1", ["H002"], ["T001", "T003"], ctx.alignment);
    await waitFor(() => expect(runVerseChecks).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/2 words placed together/)).toBeInTheDocument();
    expect(document.querySelectorAll(".picked")).toHaveLength(0);
  });

  it("Shift-click takes the run of words from the last picked one", async () => {
    const ctx = untouched();
    realignWords.mockResolvedValue(ctx);
    await open(ctx);
    await fireEvent.click(screen.getByRole("button", { name: "आदि" }));
    await fireEvent.click(screen.getByRole("button", { name: "सृष्टि" }), { shiftKey: true });
    expect(document.querySelectorAll(".bank-tokens .picked")).toHaveLength(3);
    await fireEvent.click(screen.getByLabelText("Align 3 picked-up words to בְּרֵאשִׁית"));
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "1", ["H001"], ["T001", "T002", "T003"], ctx.alignment));
  });

  it("Ctrl-click on a picked word puts that one down; a plain click keeps the one-word path", async () => {
    const ctx = untouched();
    await open(ctx);
    await fireEvent.click(screen.getByRole("button", { name: "आदि" }));
    await fireEvent.click(screen.getByRole("button", { name: "में" }), { ctrlKey: true });
    await fireEvent.click(screen.getByRole("button", { name: "आदि" }), { ctrlKey: true });
    expect(screen.getByRole("button", { name: "आदि" }).classList.contains("picked")).toBe(false);
    expect(screen.getByRole("button", { name: "में" }).classList.contains("picked")).toBe(true);
    // A plain click on another word picks that word alone.
    await fireEvent.click(screen.getByRole("button", { name: "सृष्टि" }));
    expect(document.querySelectorAll(".picked")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "सृष्टि" }).classList.contains("picked")).toBe(true);
    expect(screen.getByLabelText("Align picked-up word to בָּרָא")).toBeInTheDocument();
    // And a plain click on the only picked word puts it down.
    await fireEvent.click(screen.getByRole("button", { name: "सृष्टि" }));
    expect(document.querySelectorAll(".picked")).toHaveLength(0);
    expect(realignWords).not.toHaveBeenCalled();
  });

  it("Escape puts the picked words down; the next Escape closes", async () => {
    const onClose = vi.fn();
    getAlignment.mockResolvedValue(untouched());
    render(AlignmentModal, { props: { chapter: "1", verse: "1", onClose } });
    await fireEvent.click(await screen.findByRole("button", { name: "आदि" }));
    await fireEvent.click(screen.getByRole("button", { name: "में" }), { ctrlKey: true });
    expect(document.querySelectorAll(".picked")).toHaveLength(2);
    await fireEvent.keyDown(window, { key: "Escape" });
    expect(document.querySelectorAll(".picked")).toHaveLength(0);
    expect(onClose).not.toHaveBeenCalled();
    await fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("an aligned word can be picked with a bank word and moved to another column in one call", async () => {
    const ctx = context();
    realignWords.mockResolvedValue(ctx);
    await open(ctx);
    await fireEvent.click(screen.getByRole("button", { name: "Pick up आदि from בְּרֵאשִׁית" }));
    await fireEvent.click(screen.getByRole("button", { name: "में" }), { ctrlKey: true });
    await fireEvent.click(screen.getByLabelText("Align 2 picked-up words to בָּרָא"));
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "1", ["H002"], ["T001", "T002"], ctx.alignment));
    expect(unalignWords).not.toHaveBeenCalled();
  });

  it("picked words dropped on the word bank are unaligned in one call; bank words among them are left", async () => {
    const ctx = context();
    unalignWords.mockResolvedValue(ctx);
    await open(ctx);
    await fireEvent.click(screen.getByRole("button", { name: "Pick up आदि from בְּרֵאשִׁית" }));
    await fireEvent.click(screen.getByRole("button", { name: "में" }), { ctrlKey: true });
    await fireEvent.click(screen.getByLabelText("Return 2 picked-up words to the word bank"));
    await waitFor(() => expect(unalignWords).toHaveBeenCalledWith("1", "1", ["T001"], ctx.alignment));
    expect(realignWords).not.toHaveBeenCalled();
  });

  it("a drag that starts on a picked word carries the whole selection to the column it lands on", async () => {
    const ctx = untouched();
    realignWords.mockResolvedValue(ctx);
    await open(ctx);
    await fireEvent.click(screen.getByRole("button", { name: "आदि" }));
    await fireEvent.click(screen.getByRole("button", { name: "सृष्टि" }), { ctrlKey: true });
    const cell = screen.getByLabelText("Align 2 picked-up words to בָּרָא");
    // jsdom has no layout: the column is what is "under" the pointer.
    (document as unknown as HitTest).elementFromPoint = () => cell;
    pointer("pointerdown", screen.getByRole("button", { name: "आदि" }), { clientX: 10, clientY: 10 });
    pointer("pointermove", window, { clientX: 80, clientY: 80 });
    await waitFor(() => expect(screen.getByText("आदि सृष्टि", { selector: ".drag-ghost" })).toBeInTheDocument());
    pointer("pointerup", window);
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "1", ["H002"], ["T001", "T003"], ctx.alignment));
  });

  it("a drag that starts on an unpicked word supersedes the selection and carries that word alone", async () => {
    const ctx = untouched();
    realignWords.mockResolvedValue(ctx);
    await open(ctx);
    await fireEvent.click(screen.getByRole("button", { name: "आदि" }));
    const cell = screen.getByLabelText("Align picked-up word to בָּרָא");
    (document as unknown as HitTest).elementFromPoint = () => cell;
    pointer("pointerdown", screen.getByRole("button", { name: "सृष्टि" }), { clientX: 10, clientY: 10 });
    pointer("pointermove", window, { clientX: 80, clientY: 80 });
    await waitFor(() => expect(document.querySelectorAll(".picked")).toHaveLength(0));
    pointer("pointerup", window);
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "1", ["H002"], ["T003"], ctx.alignment));
  });
});

describe("AlignmentModal target containers carry the project language (#286)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getLexiconEntry.mockResolvedValue({ segments: [] });
    runVerseChecks.mockResolvedValue([]);
  });

  it("puts lang on every column's target cell and on the word bank, never on the source words", async () => {
    project.set(projectInfo({ targetLanguageId: "pan" }));
    await open();
    const cells = [...document.querySelectorAll(".target-cell")];
    expect(cells).toHaveLength(2);
    for (const cell of cells) expect(cell.getAttribute("lang")).toBe("pan");
    expect(document.querySelector(".bank-tokens")?.getAttribute("lang")).toBe("pan");
    expect(document.querySelector(".token.source")?.closest("[lang]")).toBeNull();
    project.set(projectInfo());
  });
});
