import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";

import AlignmentModal from "../AlignmentModal.svelte";
// @ts-expect-error Vite's test-only raw loader is not part of the app tsconfig.
import alignmentModalSource from "../AlignmentModal.svelte?raw";
// @ts-expect-error Vite's test-only raw loader is not part of the app tsconfig.
import wordPanelsSource from "../WordPanels.svelte?raw";
// @ts-expect-error Vite's test-only raw loader is not part of the app tsconfig.
import wordPanelSource from "../WordPanel.svelte?raw";
import { leaves } from "../../alignmentLayout";
import { crossVerseOpen } from "../../alignmentUi";
import { tabRequest } from "../../editorPrefs";
// @ts-expect-error The app tsconfig has no node types; vitest runs under node.
import { readFileSync } from "node:fs";
// The stylesheet is read from disk: Vitest hands a CSS import back empty.
const alignmentCardsSource: string = readFileSync("src/lib/alignmentCards.css", "utf-8");
import { WORD_PANEL_PRESETS, resetWordPanels, wordPanelPreset, wordPanelScales, wordPanelTree } from "../../wordPanels";
import { get } from "svelte/store";
import { answerConfirmation, confirmRequest } from "../../confirmAction";
import { alignmentRevisionByVerse, chapterVerseNums, noteAlignmentChanged, project, selectedVerse, verseDisplay, verseKey } from "../../stores";
import type { AlignmentContext, AlignmentToken, ProjectInfo } from "../../types/finding";

const {
  getAlignment, realignWords, unalignWords, undoAlignment, restoreAlignment, runVerseChecks, getLexiconEntry, getVerse, splitAlignmentSource,
  crossVerseUnlink,
} = vi.hoisted(() => ({
  crossVerseUnlink: vi.fn(),
  getAlignment: vi.fn(),
  splitAlignmentSource: vi.fn(),
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
    getAlignment, realignWords, unalignWords, undoAlignment, restoreAlignment, runVerseChecks, getLexiconEntry, getVerse, splitAlignmentSource,
    crossVerseUnlink,
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
  await screen.findByRole("heading", { name: /^Word alignment/ });
  return result;
}

describe("AlignmentModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    project.set(projectInfo());
    verseDisplay.set({});
    alignmentRevisionByVerse.set({});
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
    expect(screen.getByRole("heading", { name: /^Word alignment · Genesis \(GEN\) 1:1$/ }))
      .toBeInTheDocument();
  });

  it("does not repeat the book id as its own name", async () => {
    // bookName falls back to the raw book id when the tC manifest has no
    // project.name, and "gen (GEN)" would be nonsense.
    project.set(projectInfo({ bookName: "gen" }));
    await open();
    expect(screen.getByRole("heading", { name: /^Word alignment · GEN 1:1$/ })).toBeInTheDocument();
  });

  // 2026-11-16 (Joel): the chapter tally row is gone; the status bar under
  // the editor carries the chapter's counts.
  it("has no chapter tally row", async () => {
    await open();
    expect(screen.queryByText(/31 verses/)).toBeNull();
    expect(screen.queryByText(/28 untouched/)).toBeNull();
  });

  it("shows the unaligned count as a chip, not a banner", async () => {
    await open();
    expect(screen.getByText("2 remaining")).toBeInTheDocument();
    expect(screen.queryByText(/Not fully aligned/)).not.toBeInTheDocument();
  });

  it("shows cross-verse linked words as their own chip", async () => {
    await open(context({ crossVerseAccounted: 2, crossVerseRealized: 0, crossVerseAccountedIds: ["T002", "T003"] }));
    const chip = screen.getByText(/2 linked across verses/);
    // An instant hint, not the browser's slow title (2026-11-16).
    expect(chip).not.toHaveAttribute("title");
    await fireEvent.mouseEnter(chip);
    expect(screen.getByRole("tooltip")).toHaveTextContent("completion stays with translationCore");
    await fireEvent.mouseLeave(chip);
  });

  // 2026-11-16 (Joel, from the team): a link is removed here as it is on the
  // Cross-verse page, from either end.
  function link(extra: Record<string, unknown>) {
    const end = (verse: string, word: string) => ({ chapter: "1", verse, word, occurrence: 1, occurrences: 1, signature: word });
    return { id: "L1", bookId: "gen", state: "active", createdAt: "", updatedAt: "", actorId: "u",
      source: end("2", "אֱלֹהִים"), target: end("1", "में"), sourceTopId: null, targetBottomId: null, ...extra } as never;
  }
  it("removes a cross-verse link from the linked target word, and tells the other verse", async () => {
    alignmentRevisionByVerse.set({});
    await open(context({ crossVerseAccounted: 1, crossVerseAccountedIds: ["T002"], crossVerseLinks: [link({ targetBottomId: "T002" })] }));
    crossVerseUnlink.mockResolvedValue({ link: link({}), source: context({ verse: "2" }), target: context() });
    await fireEvent.click(screen.getByRole("button", { name: "Remove cross-verse link from אֱלֹהִים in verse 2 to में" }));
    await waitFor(() => expect(crossVerseUnlink).toHaveBeenCalledWith("L1"));
    await waitFor(() => expect(screen.queryByRole("button", { name: /Remove cross-verse link/ })).not.toBeInTheDocument());
    expect(get(alignmentRevisionByVerse)[verseKey("1", "2")]).toBe(1);
    expect(get(alignmentRevisionByVerse)[verseKey("1", "1")]).toBe(1);
  });
  it("shows a source word realized in another verse under its column, with the same remove", async () => {
    const realized = link({ source: { chapter: "1", verse: "1", word: "בָּרָא", occurrence: 1, occurrences: 1, signature: "x" },
      target: { chapter: "1", verse: "2", word: "रचा", occurrence: 1, occurrences: 1, signature: "y" }, sourceTopId: "H002" });
    await open(context({ crossVerseRealized: 1, crossVerseRealizedIds: ["H002"], crossVerseLinks: [realized] }));
    crossVerseUnlink.mockResolvedValue({ link: realized, source: context(), target: context({ verse: "2" }) });
    expect(screen.getByText("रचा")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Remove cross-verse link from בָּרָא to रचा in verse 2" }));
    await waitFor(() => expect(crossVerseUnlink).toHaveBeenCalledWith("L1"));
  });

  it("headings name both word banks", async () => {
    await open();
    expect(screen.getByText("Source words")).toBeInTheDocument();
    expect(screen.getByText("Target words")).toBeInTheDocument();
  });

  // 2026-11-14 (Joel): the long instructions are hints, the verse to read can
  // be hidden, and reset and the backups are closed until asked for.
  it("puts the instructions behind hint buttons", async () => {
    await open();
    expect(screen.getByRole("button", { name: "Source words help" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Target words help" })).toBeInTheDocument();
    expect(screen.queryByText(/Click a word for its lexicon entry/)).not.toBeInTheDocument();
  });

  // 2026-11-16 (Joel): the bar is the Verses panel's: chapter, verse, the
  // verse arrows, then icons. The verse to read is always shown.
  it("always shows the verse to read: there is no hide button", async () => {
    await open();
    expect(screen.getByRole("region", { name: "Read Genesis (GEN) 1:1" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /the verse text/ })).toBeNull();
  });

  it("names the chapter and verse in the bar and steps to the next verse", async () => {
    chapterVerseNums.set({ "1": ["front", "1", "2", "3"] }); selectedVerse.set("1");
    await open();
    const nav = screen.getByRole("group", { name: "Verse navigation" });
    expect(nav).toHaveTextContent("Chapter 1");
    expect(nav).toHaveTextContent("Verse 1");
    expect(nav).toHaveTextContent("of 3");
    expect(screen.getByRole("button", { name: "Previous verse" })).toBeDisabled();
    await fireEvent.click(screen.getByRole("button", { name: "Next verse" }));
    expect(get(selectedVerse)).toBe("2");
    chapterVerseNums.set({});
  });

  it("opens Cross-verse from an icon button in the bar, and shows it when it is already open", async () => {
    crossVerseOpen.set(false);
    await open();
    const cross = screen.getByRole("button", { name: "Cross-verse alignment" });
    await fireEvent.mouseEnter(cross);
    expect(screen.getByRole("tooltip")).toHaveTextContent("this verse beside its neighbours");
    await fireEvent.mouseLeave(cross);
    await fireEvent.click(cross);
    expect(get(crossVerseOpen)).toBe(true);
    // Open already: the hint says so, and a click shows the tab without opening it again.
    const request = get(tabRequest).seq;
    await fireEvent.mouseEnter(cross);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Cross-verse alignment is already open. Click to show it");
    await fireEvent.mouseLeave(cross);
    await fireEvent.click(cross);
    expect(get(tabRequest)).toMatchObject({ id: "crossVerse", seq: request + 1 });
    crossVerseOpen.set(false);
    expect(screen.getByRole("button", { name: "Cross-verse alignment" })).toBeInTheDocument();
    expect(alignmentModalSource).toMatch(/header \{[^}]*height:\s*36px/);
  });

  // 2026-11-16 (Joel): reset and the backups are one menu on the bar.
  it("keeps reset and the backups in one menu on the bar", async () => {
    const history = Array.from({ length: 12 }, (_, i) => ({ id: `h${i + 1}`, timestamp: `2020-01-${String(20 - i).padStart(2, "0")}T10:00:00Z`, operation: "realign" }));
    const ctx = context({ history: history as never });
    await open(ctx);
    expect(screen.queryByText("History and reset")).toBeNull();
    const menu = document.querySelector<HTMLElement>('[role="menu"][aria-label="Reset and backups"]')!;
    expect(menu).not.toBeVisible();
    await fireEvent.click(screen.getByRole("button", { name: "Reset and backups" }));
    expect(menu).toBeVisible();
    expect(menu).toHaveTextContent("Reset verse alignment");
    expect(screen.queryByRole("menuitem", { name: "Undo reset" })).toBeNull();
    restoreAlignment.mockResolvedValue(ctx);
    // The newest ten, in plain words: no raw timestamp, no engine word.
    const rows = screen.getAllByRole("menuitem").filter((row) => /before a word was placed/.test(row.textContent || ""));
    expect(rows).toHaveLength(10);
    expect(rows[0]).toHaveTextContent("2020");
    expect(menu).not.toHaveTextContent("realign");
    expect(menu).not.toHaveTextContent("T10:00:00Z");
    await fireEvent.click(rows[0]);
    expect(menu).not.toBeVisible();
    await waitFor(() => expect(get(confirmRequest)).not.toBeNull());
    answerConfirmation(true);
    await waitFor(() => expect(restoreAlignment).toHaveBeenCalledWith("1", "1", "h1", ctx.alignment));
  });

  // 2026-11-16 (Joel): three panels, each with its own title row; the counts
  // and the info hint are at the right end of the row.
  it("draws the verse, the source words and the target words as three panels", async () => {
    await open();
    for (const name of ["Verse", "Source words", "Target words"]) expect(screen.getByRole("region", { name })).toBeInTheDocument();
    // The verse row fits its text; source and target share the rest, and the line between them drags.
    expect(document.querySelector<HTMLElement>(".word-panels")!.dataset.gridRows).toBe("auto minmax(96px, 100fr)");
    expect(screen.getByRole("slider", { name: "Resize panel widths" })).toBeInTheDocument();
    const target = screen.getByRole("region", { name: "Target words" });
    const bar = target.querySelector(".bar")!;
    expect(bar.querySelector(".tools")).toHaveTextContent("2 remaining");
    expect(bar.querySelector(".tools")!.lastElementChild).toBe(screen.getByRole("button", { name: "Target words help" }));
    expect(screen.queryByRole("slider", { name: "Resize the target words area" })).toBeNull();
  });

  it("sets each panel's text size on its own, and the bar's layout picker resets it", async () => {
    resetWordPanels();
    await open();
    const body = (name: string) => screen.getByRole("region", { name }).querySelector<HTMLElement>(".body")!;
    await fireEvent.click(screen.getByRole("button", { name: "Larger source words text" }));
    expect(body("Source words").dataset.scale).toBe("1.15");
    expect(body("Target words").dataset.scale).toBe("1");
    expect(get(wordPanelScales)).toEqual({ read: 1, source: 1.15, target: 1 });
    await fireEvent.click(screen.getByRole("button", { name: "Layout" }));
    expect(screen.getAllByRole("menuitemradio")).toHaveLength(WORD_PANEL_PRESETS.length);
    expect(screen.getByRole("menuitemradio", { name: "One on top, two below" })).toHaveAttribute("aria-checked", "true");
    await fireEvent.click(screen.getByRole("menuitemradio", { name: "Three rows" }));
    expect(wordPanelPreset(get(wordPanelTree))).toBe("rows3");
    await fireEvent.click(screen.getByRole("button", { name: "Layout" }));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Reset to default" }));
    expect(wordPanelPreset(get(wordPanelTree))).toBe("top1bottom2");
    expect(body("Source words").dataset.scale).toBe("1");
  });

  it("moves a panel dragged by its title row to the side of the panel it is dropped on", async () => {
    vi.stubGlobal("PointerEvent", MouseEvent);
    resetWordPanels();
    await open();
    const panel = (id: string) => document.querySelector<HTMLElement>(`[data-word-panel="${id}"]`)!;
    const rect = (el: Element, r: Partial<DOMRect>) => { (el as HTMLElement).getBoundingClientRect = () => ({ left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0, toJSON: () => ({}), ...r }) as DOMRect; };
    rect(panel("source"), { left: 0, top: 100, width: 400, height: 300, right: 400, bottom: 400 });
    rect(panel("target"), { left: 400, top: 100, width: 400, height: 300, right: 800, bottom: 400 });
    expect(leaves(get(wordPanelTree))).toEqual(["read", "source", "target"]);
    // A press on a button in the row is a click, not a drag.
    await fireEvent.pointerDown(screen.getByRole("button", { name: "Target words help" }), { button: 0, clientX: 780, clientY: 110 });
    await fireEvent.pointerMove(window, { clientX: 20, clientY: 250 });
    expect(document.querySelector(".drop-preview")).toBeNull();
    await fireEvent.pointerUp(window);
    // The row itself: over the left edge of Source words, with a preview.
    await fireEvent.pointerDown(panel("target").querySelector(".bar")!, { button: 0, clientX: 500, clientY: 110 });
    await fireEvent.pointerMove(window, { clientX: 20, clientY: 250 });
    expect(document.querySelector(".drop-preview")).not.toBeNull();
    await fireEvent.pointerUp(window);
    expect(leaves(get(wordPanelTree))).toEqual(["read", "target", "source"]);
    expect(document.querySelector(".drop-preview")).toBeNull();
    vi.unstubAllGlobals();
    resetWordPanels();
  });

  it("shows the saved note over the page, and it goes by itself", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const ctx = context();
      realignWords.mockResolvedValue(ctx);
      await open(ctx);
      await fireEvent.click(screen.getByRole("button", { name: "में" }));
      await fireEvent.click(screen.getByLabelText("Align picked-up word to בָּרָא"));
      const note = await screen.findByText(/alignment checks are current/);
      expect(note.closest(".toasts")).not.toBeNull();
      expect(note.closest("[data-word-panel]")).toBeNull();
      await vi.advanceTimersByTimeAsync(4100);
      await waitFor(() => expect(screen.queryByText(/alignment checks are current/)).toBeNull());
    } finally { vi.useRealTimers(); }
  });

  // 2026-11-25 (Joel): a refused save stayed over the foot of the tab until
  // it was closed. It goes after ten seconds, as in the Verses panel.
  it("clears an error by itself after ten seconds, and at once from its close button", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      realignWords.mockRejectedValue(new Error("בָּרָא in 1:1 is marked grammatical; clear that before aligning it."));
      await open();
      const drop = async () => {
        await fireEvent.click(screen.getByRole("button", { name: "में" }));
        await fireEvent.click(screen.getByLabelText("Align picked-up word to בָּרָא"));
        return screen.findByRole("alert");
      };
      expect(await drop()).toHaveTextContent("is marked grammatical");
      await vi.advanceTimersByTimeAsync(9000);
      expect(screen.getByRole("alert")).toBeInTheDocument();
      await vi.advanceTimersByTimeAsync(1500);
      await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());

      // Pointed at, it is held; the timer starts again when the pointer leaves.
      const held = await drop();
      await fireEvent.mouseEnter(held);
      await vi.advanceTimersByTimeAsync(15000);
      expect(screen.getByRole("alert")).toBeInTheDocument();
      await fireEvent.mouseLeave(held);
      await vi.advanceTimersByTimeAsync(10500);
      await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());

      await drop();
      await fireEvent.click(screen.getByRole("button", { name: "Dismiss this message" }));
      expect(screen.queryByRole("alert")).toBeNull();
    } finally { vi.useRealTimers(); }
  });

  it("clears the picked words on a click on empty space in the target words panel", async () => {
    await open();
    const first = screen.getByRole("button", { name: "में" });
    await fireEvent.click(first);
    await fireEvent.click(screen.getByRole("button", { name: "सृष्टि" }), { ctrlKey: true });
    expect(screen.getByText("2 picked")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Return 2 picked-up words to the word bank" }));
    expect(screen.queryByText("2 picked")).toBeNull();
    expect(first).toHaveAttribute("aria-pressed", "false");
    expect(unalignWords).not.toHaveBeenCalled();
  });

  // 2026-11-17 (Joel): Shift-click from one unaligned word to another must not
  // take the aligned word between them with it.
  it("skips an aligned word between two unaligned ones on a Shift-click run", async () => {
    const tokens = [token("T001", "आदि"), token("T002", "में"), token("T003", "सृष्टि")];
    const ctx = context({
      bottomTokens: tokens,
      groups: [{ id: "G001", topIds: ["H001"], bottomIds: ["T002"] }, { id: "G002", topIds: ["H002"], bottomIds: [] }],
    });
    realignWords.mockResolvedValue(ctx);
    await open(ctx);
    await fireEvent.click(screen.getByRole("button", { name: "आदि" }));
    await fireEvent.click(screen.getByRole("button", { name: "सृष्टि" }), { shiftKey: true });
    expect(screen.getByText("2 picked")).toBeInTheDocument();
    // The aligned word, in its column, is not picked.
    expect(screen.getByRole("button", { name: "Pick up में from בְּרֵאשִׁית" })).toHaveAttribute("aria-pressed", "false");
    await fireEvent.click(screen.getByLabelText("Align 2 picked-up words to בָּרָא"));
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "1", ["H002"], ["T001", "T003"], ctx.alignment));
  });

  it("gives an aligned word small remove and order controls with instant hints", async () => {
    const ctx = context({ groups: [{ id: "G001", topIds: ["H001"], bottomIds: ["T001", "T002"] }, { id: "G002", topIds: ["H002"], bottomIds: [] }] });
    await open(ctx);
    const remove = screen.getByRole("button", { name: "Unalign आदि from בְּרֵאשִׁית" });
    expect(remove).toHaveClass("card-btn");
    // One toolbar per card, in reading order: earlier, later, remove.
    const tools = remove.closest(".card-tools")!;
    expect(Array.from(tools.querySelectorAll("button")).map((b) => b.getAttribute("aria-label"))).toEqual(
      ["Move आदि earlier", "Move आदि later", "Unalign आदि from בְּרֵאשִׁית"]);
    expect(rule(alignmentModalSource, ".card-tools")).toMatch(/display:\s*none/);
    expect(remove).not.toHaveAttribute("title");
    await fireEvent.mouseEnter(remove);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Remove");
    await fireEvent.mouseLeave(remove);
    expect(screen.getByRole("button", { name: "Move आदि earlier" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Move आदि later" })).toBeEnabled();
    // No browser tooltip is left anywhere in the tab.
    expect(alignmentModalSource).not.toMatch(/\stitle=/);
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

  // 2026-11-15 (Joel): the Cross-verse page is a second tab, open beside this
  // one. A save there (or a verse edit) is read here without being asked.
  it("reads the verse again when it was saved somewhere else, and not after its own save", async () => {
    alignmentRevisionByVerse.set({});
    getAlignment.mockClear();
    const ctx = context();
    realignWords.mockResolvedValue(ctx);
    await open(ctx);
    expect(getAlignment).toHaveBeenCalledTimes(1);

    await fireEvent.click(screen.getByRole("button", { name: "में" }));
    await fireEvent.click(screen.getByLabelText("Align picked-up word to בָּרָא"));
    await waitFor(() => expect(get(alignmentRevisionByVerse)["1:1"]).toBe(1));
    await waitFor(() => expect(screen.getByText(/alignment checks are current/)).toBeInTheDocument());
    expect(getAlignment).toHaveBeenCalledTimes(1);

    noteAlignmentChanged("1:2");
    await Promise.resolve();
    expect(getAlignment).toHaveBeenCalledTimes(1);

    noteAlignmentChanged("1:1");
    await waitFor(() => expect(getAlignment).toHaveBeenCalledTimes(2));
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
    expect(interlinear).toMatch(/overflow-x:\s*(hidden|clip)/);  // #485: clip, so it is no scroll container
    expect(interlinear).not.toMatch(/overflow-x:\s*(auto|scroll)/);
  });

  // #485: the block grows to the verse; the dialog is the one scroller, and
  // the edge auto-scroll during a drag keeps a far column reachable.
  it("lets the wrapped block grow instead of scrolling it; the dialog scrolls", () => {
    const interlinear = rule(alignmentModalSource, ".interlinear");
    expect(interlinear).not.toMatch(/max-height:/);
    expect(interlinear).not.toMatch(/overflow-y:/);
    expect(interlinear).not.toMatch(/overflow:\s*(auto|scroll)/);
    expect(rule(alignmentModalSource, ".modal")).toMatch(/overflow:\s*auto/);
    expect(alignmentModalSource).toMatch(/on:pointermove=\{trackEdge\}/);
  });

  // 2026-11-16 (Joel): the header stays at the top; under it are three
  // panels that fit their words. Nothing below the header sticks or scrolls
  // inside, and a word box grows with its word.
  it("keeps the header at the top and lets every panel and word box fit its content", () => {
    expect(rule(alignmentModalSource, "header")).toMatch(/position:\s*sticky;\s*top:\s*0/);
    const bank = rule(alignmentModalSource, ".bank-tokens");
    expect(bank).not.toMatch(/max-height|overflow/);
    expect(bank).toMatch(/flex:\s*1/);
    expect(alignmentModalSource).toMatch(/<WordPanels>/);
    expect(alignmentModalSource).not.toMatch(/<AlignmentWorkspace|<AlignmentPane/);
    // The panels fill the tab; one that is full scrolls, a word box never does.
    expect(rule(wordPanelsSource, ".word-panels")).toMatch(/flex:\s*1 1 0/);
    expect(wordPanelSource).toMatch(/\.body \{[^}]*overflow-y:\s*auto/);
    // The same rules size the Cross-verse page's word boxes.
    expect(alignmentCardsSource).toMatch(/:is\(\.modal, \.page\)\.alignment-cards \.token\.source \{ width: auto;[^}]*height: auto;/);
    expect(alignmentCardsSource).toMatch(/:is\(\.modal, \.page\)\.alignment-cards \.token\.source > \.word \{[^}]*overflow: visible;/);
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

  // 2026-11-17 (Joel): no "Separate left / right". A merged column has a
  // split button on each seam; the words before the seam keep the targets.
  it.each([["Beta", ["H001"]], ["Gamma", ["H001", "H002"]]] as const)("splits a three-word column at the seam before %s, with no side to choose", async (word, kept) => {
    const base = context(), topTokens = [token("H001", "Alpha"), token("H002", "Beta"), token("H003", "Gamma")];
    const ctx = context({ topTokens, sourceDirection: "ltr",
      alignment: { alignments: [{ topWords: topTokens, bottomWords: [base.bottomTokens[0]] }], wordBank: base.bottomTokens.slice(1) },
      groups: [{ id: "joined", topIds: topTokens.map(t => t.id), bottomIds: [base.bottomTokens[0].id] }] });
    realignWords.mockResolvedValue(ctx);
    await open(ctx);
    expect(screen.queryByText(/Separate/)).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: `Split Alpha Beta Gamma before ${word}` }));
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "1", [...kept], [base.bottomTokens[0].id], ctx.alignment));
    expect(splitAlignmentSource).not.toHaveBeenCalled();
  });

  // The engine makes every other alignment edit wait for an interrupted
  // separation, so the page must still offer to finish one.
  it("offers to resume an interrupted source separation, for the word the engine names", async () => {
    const base = context();
    const ctx = context({ sourceLayout: { pending: { signature: `${base.topTokens[1].word}\u241f1\u241f1`, direction: "right" } } });
    splitAlignmentSource.mockResolvedValue({ contexts: [base] });
    await open(ctx);
    await fireEvent.click(screen.getByRole("button", { name: "Resume separation" }));
    expect(get(confirmRequest)?.confirmLabel).toBe("Resume separation");
    expect(splitAlignmentSource).not.toHaveBeenCalled();
    answerConfirmation(true);
    await waitFor(() => expect(splitAlignmentSource).toHaveBeenCalledWith("1", "1", "H002", "right", ctx.alignment, false));
  });

  it("shows no separation row when nothing is interrupted or undoable", async () => {
    await open(joined());
    expect(screen.queryByRole("button", { name: /separation/i })).toBeNull();
  });

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

  // 2026-11-18 (the team): no target word has to be placed first.
  it("Join works while neither column has a target word", async () => {
    const ctx = context({
      alignment: { alignments: [], wordBank: context().bottomTokens },
      groups: [],
    });
    realignWords.mockResolvedValue(ctx);
    await open(ctx);
    const join = screen.getByRole("button", { name: "Join בָּרָא with the previous source word" });
    expect(join).not.toBeDisabled();
    await fireEvent.click(join);
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "1", ["H001", "H002"], [], ctx.alignment));
  });

  it("Split cuts a joined column at its seam; the first word keeps the target", async () => {
    const ctx = joined();
    realignWords.mockResolvedValue(ctx);
    await open(ctx);
    await fireEvent.click(screen.getByRole("button", { name: "Split בְּרֵאשִׁית בָּרָא before בָּרָא" }));
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "1", ["H001"], ["T001"], ctx.alignment));
  });

  // 2026-11-18 (Joel): merged, then the target word taken away: it still splits.
  it("Split works on a joined column that has no target word", async () => {
    const base = context();
    const ctx = joined({
      alignment: { alignments: [{ topWords: base.topTokens, bottomWords: [] }], wordBank: base.bottomTokens },
      groups: [{ id: "G001", topIds: ["H001", "H002"], bottomIds: [] }],
    });
    realignWords.mockResolvedValue(ctx);
    await open(ctx);
    const split = screen.getByRole("button", { name: "Split בְּרֵאשִׁית בָּרָא before בָּרָא" });
    expect(split).not.toBeDisabled();
    await fireEvent.click(split);
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "1", ["H001"], [], ctx.alignment));
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

describe("AlignmentModal reorder within a column and rubber-band pick (#410)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    project.set(projectInfo());
    getLexiconEntry.mockResolvedValue({ segments: [] });
    runVerseChecks.mockResolvedValue([]);
  });

  type HitTest = { elementFromPoint: (x: number, y: number) => Element | null };
  type Rect = Pick<DOMRect, "left" | "top" | "right" | "bottom" | "width" | "height">;

  function pointer(type: string, target: Element | Window, init: MouseEventInit = {}) {
    target.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, ...init }));
  }

  function rect(el: Element, value: Rect) {
    (el as HTMLElement).getBoundingClientRect = () => ({ x: value.left, y: value.top, ...value, toJSON() {} }) as DOMRect;
  }

  /** The first source word holds two target words; the third is in the bank. */
  function twoInColumn(): AlignmentContext {
    const base = context();
    return context({
      alignment: {
        alignments: [
          { topWords: [base.topTokens[0]], bottomWords: [base.bottomTokens[0], base.bottomTokens[1]] },
          { topWords: [base.topTokens[1]], bottomWords: [] },
        ],
        wordBank: [base.bottomTokens[2]],
      },
      groups: [
        { id: "G001", topIds: ["H001"], bottomIds: ["T001", "T002"] },
        { id: "G002", topIds: ["H002"], bottomIds: [] },
      ],
    });
  }

  it("shows earlier/later buttons only when a column holds several words, with the edges disabled", async () => {
    await open();
    expect(screen.queryByRole("button", { name: "Move आदि earlier" })).toBeNull();
    const first = screen.getByRole("button", { name: "Pick up आदि from בְּרֵאשִׁית" });
    expect(first).toBeInTheDocument();
  });

  it("the later button moves a word one place later in the same column, in one realign call", async () => {
    const ctx = twoInColumn();
    realignWords.mockResolvedValue(ctx);
    await open(ctx);
    expect(screen.getByRole("button", { name: "Move आदि earlier" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Move में later" })).toBeDisabled();
    await fireEvent.click(screen.getByRole("button", { name: "Move आदि later" }));
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "1", ["H001"], ["T002", "T001"], ctx.alignment));
    await screen.findByText(/Word order changed/);
  });

  it("a word dragged onto the leading half of the first card in its own column is reordered before it", async () => {
    const ctx = twoInColumn();
    realignWords.mockResolvedValue(ctx);
    await open(ctx);
    const firstCard = screen.getByRole("button", { name: "Pick up आदि from בְּרֵאשִׁית" }).closest("[data-drop-slot]")!;
    rect(firstCard, { left: 0, top: 100, right: 80, bottom: 140, width: 80, height: 40 });
    (document as unknown as HitTest).elementFromPoint = () => firstCard;
    pointer("pointerdown", screen.getByRole("button", { name: "Pick up में from בְּרֵאשִׁית" }), { clientX: 10, clientY: 200 });
    pointer("pointermove", window, { clientX: 20, clientY: 110 });
    await waitFor(() => expect(firstCard.classList.contains("insert-before")).toBe(true));
    pointer("pointerup", window);
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "1", ["H001"], ["T002", "T001"], ctx.alignment));
  });

  it("a word dropped back where it already sits saves nothing", async () => {
    const ctx = twoInColumn();
    await open(ctx);
    const secondCard = screen.getByRole("button", { name: "Pick up में from בְּרֵאשִׁית" }).closest("[data-drop-slot]")!;
    rect(secondCard, { left: 0, top: 150, right: 80, bottom: 190, width: 80, height: 40 });
    (document as unknown as HitTest).elementFromPoint = () => secondCard;
    pointer("pointerdown", screen.getByRole("button", { name: "Pick up में from בְּרֵאשִׁית" }), { clientX: 10, clientY: 160 });
    pointer("pointermove", window, { clientX: 60, clientY: 180 });
    await waitFor(() => expect(secondCard.classList.contains("insert-after")).toBe(true));
    pointer("pointerup", window);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(realignWords).not.toHaveBeenCalled();
  });

  it("a bank word dropped on a card lands before or after it instead of last", async () => {
    const ctx = twoInColumn();
    realignWords.mockResolvedValue(ctx);
    await open(ctx);
    const firstCard = screen.getByRole("button", { name: "Pick up आदि from בְּרֵאשִׁית" }).closest("[data-drop-slot]")!;
    rect(firstCard, { left: 0, top: 100, right: 80, bottom: 140, width: 80, height: 40 });
    (document as unknown as HitTest).elementFromPoint = () => firstCard;
    pointer("pointerdown", screen.getByRole("button", { name: "सृष्टि" }), { clientX: 10, clientY: 300 });
    pointer("pointermove", window, { clientX: 60, clientY: 130 }); // trailing half: after आदि
    pointer("pointerup", window);
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "1", ["H001"], ["T001", "T003", "T002"], ctx.alignment));
  });

  it("dragging a box across the word bank picks the words it touches; the bank click that follows keeps them", async () => {
    const ctx = context({ alignment: { alignments: [], wordBank: context().bottomTokens }, groups: [], status: "untouched" });
    await open(ctx);
    const bank = document.querySelector(".bank-tokens")!;
    const words = ["आदि", "में", "सृष्टि"].map((w) => screen.getByRole("button", { name: w }));
    words.forEach((el, i) => rect(el, { left: i * 60, top: 0, right: i * 60 + 50, bottom: 30, width: 50, height: 30 }));
    pointer("pointerdown", bank, { clientX: 200, clientY: 60 });
    pointer("pointermove", window, { clientX: 70, clientY: 10 });
    await waitFor(() => expect(document.querySelector(".marquee")).toBeInTheDocument());
    expect(words[0]).toHaveAttribute("aria-pressed", "false");
    expect(words[1]).toHaveAttribute("aria-pressed", "true");
    expect(words[2]).toHaveAttribute("aria-pressed", "true");
    pointer("pointerup", window);
    await fireEvent.click(bank); // the browser's click after the pointerup
    expect(words[1]).toHaveAttribute("aria-pressed", "true");
    expect(words[2]).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/2 picked/)).toBeInTheDocument();
    // Dragging one of them carries both to the column.
    realignWords.mockResolvedValue(ctx);
    const cell = screen.getByLabelText("Align 2 picked-up words to בָּרָא");
    (document as unknown as HitTest).elementFromPoint = () => cell;
    pointer("pointerdown", words[1], { clientX: 70, clientY: 10 });
    pointer("pointermove", window, { clientX: 140, clientY: 80 });
    pointer("pointerup", window);
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "1", ["H002"], ["T002", "T003"], ctx.alignment));
  });

  it("a press on a bank word is not a box: it is the word's own drag", async () => {
    const ctx = context({ alignment: { alignments: [], wordBank: context().bottomTokens }, groups: [], status: "untouched" });
    await open(ctx);
    (document as unknown as HitTest).elementFromPoint = () => null;
    pointer("pointerdown", screen.getByRole("button", { name: "आदि" }), { clientX: 10, clientY: 10 });
    pointer("pointermove", window, { clientX: 80, clientY: 80 });
    await waitFor(() => expect(document.querySelector(".drag-ghost")).toBeInTheDocument());
    expect(document.querySelector(".marquee")).toBeNull();
    pointer("pointerup", window);
  });
});
