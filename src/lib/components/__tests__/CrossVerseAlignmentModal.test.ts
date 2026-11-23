import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/svelte";
import { get } from "svelte/store";
import { answerConfirmation, confirmRequest } from "../../confirmAction";
import CrossVerseAlignmentModal from "../CrossVerseAlignmentModal.svelte";
// @ts-expect-error Vite's test-only raw loader is not part of the app tsconfig.
import crossPageSource from "../CrossVerseAlignmentModal.svelte?raw";
import { crossPanelLayout, wordPanelLayout } from "../../wordPanels";
import { alignmentKey, alignmentOpen } from "../../alignmentUi";
import { tabRequest } from "../../editorPrefs";

// 2026-11-16: the page's hints are the app's instant tooltip, not the
// browser's `title`. A hint is read by pointing at its element.
function hintOf(element: Element): string {
  fireEvent.mouseEnter(element);
  const text = document.querySelector('[role="tooltip"]')?.textContent ?? "";
  fireEvent.mouseLeave(element);
  return text;
}
/** The element under `root` (or `root` itself) whose hint matches. */
function byHint(root: HTMLElement, match: string | RegExp): HTMLElement {
  const found = [root, ...root.querySelectorAll<HTMLElement>("*")].find((element) => {
    const hint = hintOf(element);
    return typeof match === "string" ? hint === match : match.test(hint);
  });
  if (!found) throw new Error(`No element with the hint ${match}`);
  return found;
}
import {
  alignmentRevisionByVerse, alignmentStatusByVerse, chapterVerseNums, checkStatusByVerse, checkGroupsByVerse,
  currentChapter, findingsByVerse, noteAlignmentChanged,
} from "../../stores";
import type {
  AlignmentContext, AlignmentRange, AlignmentToken, AutoAlignJobStatus, AutoAlignWindowResult, CrossVerseLink, CrossVerseLinkResult,
} from "../../types/finding";

const {
  getAlignmentRange, realignWords, unalignWords, runVerseChecks, getLexiconEntry, crossVerseLink, crossVerseUnlink,
  analysisJobGetScopeStatus, semanticLocationGetRange, targetSemanticGetRange, crossVersePropose,
  crossVerseAiPropose, getSettings, autoAlignWindow, autoAlignRevert, autoAlignVerdict, nullSet, nullClear, splitAlignmentSource,
  restoreAlignment,
} = vi.hoisted(() => ({
  restoreAlignment: vi.fn(),
  crossVerseAiPropose: vi.fn(),
  splitAlignmentSource: vi.fn(),
  autoAlignWindow: vi.fn(),
  autoAlignRevert: vi.fn(),
  autoAlignVerdict: vi.fn(),
  nullSet: vi.fn(),
  nullClear: vi.fn(),
  getSettings: vi.fn(),
  getAlignmentRange: vi.fn(),
  realignWords: vi.fn(),
  unalignWords: vi.fn(),
  runVerseChecks: vi.fn(),
  getLexiconEntry: vi.fn(),
  crossVerseLink: vi.fn(),
  crossVerseUnlink: vi.fn(),
  analysisJobGetScopeStatus: vi.fn(),
  semanticLocationGetRange: vi.fn(),
  targetSemanticGetRange: vi.fn(),
  crossVersePropose: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: {
    getAlignmentRange, realignWords, unalignWords, runVerseChecks, getLexiconEntry, crossVerseLink, crossVerseUnlink,
    analysisJobGetScopeStatus, semanticLocationGetRange, targetSemanticGetRange, crossVersePropose,
    crossVerseAiPropose, getSettings, autoAlignWindow, autoAlignRevert, autoAlignVerdict, nullSet, nullClear, splitAlignmentSource,
    restoreAlignment,
  },
}));

function token(id: string, word: string, extra: Partial<AlignmentToken> = {}): AlignmentToken {
  return { id, word, occurrence: 1, occurrences: 1, ...extra };
}

/** A verse with source tokens H001.. and target words T001.., where the
 *  first `aligned` pairs are grouped 1:1 and the rest sit in the word bank. */
function context(verse: string, sources: string[], targets: string[], aligned: number): AlignmentContext {
  const topTokens = sources.map((w, i) => token(`H${String(i + 1).padStart(3, "0")}`, w, { strong: "G2316", lemma: `${w}·lemma` }));
  const bottomTokens = targets.map((w, i) => token(`T${String(i + 1).padStart(3, "0")}`, w));
  const groups = topTokens.map((top, i) => ({
    id: `G${String(i + 1).padStart(3, "0")}`,
    topIds: [top.id],
    bottomIds: i < aligned && bottomTokens[i] ? [bottomTokens[i].id] : [],
  }));
  return {
    chapter: "1", verse,
    alignment: {
      alignments: groups.map((g) => ({
        topWords: g.topIds.map((id) => topTokens.find((t) => t.id === id)!),
        bottomWords: g.bottomIds.map((id) => bottomTokens.find((t) => t.id === id)!),
      })),
      wordBank: bottomTokens.slice(aligned),
    },
    topTokens, bottomTokens, groups,
    status: aligned === sources.length && aligned === targets.length ? "complete" : aligned ? "partial" : "untouched",
    completionState: "pending",
    sourceAvailable: true, sourceMessage: "",
    sourceDirection: "ltr", targetDirection: "ltr",
    issues: [], canComplete: false, history: [],
    chapterStatus: { complete: 1, complete_cross_verse: 0, partial: 1, untouched: 2, invalid: 0 },
    gaps: {
      sourceUnmatched: groups.filter((g) => g.bottomIds.length === 0).length,
      targetUnmatched: targets.length - aligned,
    },
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
  };
}

const V1 = context("1", ["θεός"], ["God"], 1);
const V2 = context("2", ["λόγος", "ἦν"], ["word", "was"], 1);
const V34 = context("3-4", ["φῶς"], ["light", "shone"], 0);

/** The link the engine would record for "was" (1:2) dropped on φῶς (1:3-4). */
const LINK: CrossVerseLink = {
  id: "link-1", bookId: "php",
  source: { chapter: "1", verse: "3-4", word: "φῶς", occurrence: 1, occurrences: 1, signature: "φῶς␟1␟1", strong: "G2316" },
  target: { chapter: "1", verse: "2", word: "was", occurrence: 1, occurrences: 1, signature: "was␟1␟1" },
  state: "active", createdAt: "t", updatedAt: "t", actorId: "human",
  sourceTopId: null, targetBottomId: null,
};

function linked(): CrossVerseLinkResult {
  return {
    link: LINK,
    source: {
      ...V34,
      crossVerseLinks: [{ ...LINK, sourceTopId: "H001" }],
      crossVerseRealizedIds: ["H001"], crossVerseRealized: 1,
      gaps: { sourceUnmatched: 0, targetUnmatched: 2 },
    },
    target: {
      ...V2,
      crossVerseLinks: [{ ...LINK, targetBottomId: "T002" }],
      crossVerseAccountedIds: ["T002"], crossVerseAccounted: 1,
      gaps: { sourceUnmatched: 1, targetUnmatched: 0 },
    },
  };
}

function rangeFor(verses: string[], all: Record<string, AlignmentContext> = { "1": V1, "2": V2, "3-4": V34 }): AlignmentRange {
  return { chapter: "1", verses: verses.map((v) => all[v]), chapterStatus: V1.chapterStatus };
}

function seed() {
  chapterVerseNums.set({ "1": ["1", "2", "3-4", "5"] });
  currentChapter.set("1");
  alignmentStatusByVerse.set({});
  alignmentRevisionByVerse.set({});
  checkStatusByVerse.set({});
  checkGroupsByVerse.set({});
  findingsByVerse.set({});
}

const V5 = context("5", ["ζωή"], ["life"], 0);

beforeEach(() => {
  seed();
  getAlignmentRange.mockImplementation(async (_chapter: string, verses: string[]) =>
    rangeFor(verses, { "1": V1, "2": V2, "3-4": V34, "5": V5 }));
  getLexiconEntry.mockResolvedValue({
    languageId: "el-x-koine",
    segments: [{ meaning: "a deity, especially the supreme Divinity", lemma: "θεός", usage: "God, god" }],
  });
  runVerseChecks.mockResolvedValue([{ id: "f1" }]);
  // No completed analysis by default: the suggestion path stays quiet.
  analysisJobGetScopeStatus.mockResolvedValue({ state: "NOT_ANALYZED", latestJob: null });
  crossVersePropose.mockResolvedValue({
    chapter: "1", verses: ["1", "2", "3-4"], proposals: [], calibrationVersion: "cross-verse-uncalibrated-v1",
  });
  // An API key is configured by default so the AI button renders; the
  // no-key case is its own test.
  getSettings.mockResolvedValue({ hasApiKey: true });
  crossVerseAiPropose.mockResolvedValue({
    chapter: "1", verses: ["1", "2", "3-4"], proposals: [], corpusProposals: [],
    calibrationVersion: "cross-verse-ai-uncalibrated-v1", modelConsulted: true,
  });
});

/** A proposal shaped as `alignment.crossVerse.propose` returns it (#139). */
function proposal(overrides: Record<string, unknown> = {}) {
  return {
    status: "PROPOSED", confidence: 0.65, margin: 0.55, contested: false,
    source: {
      chapter: "1", verse: "3-4", topId: "H001", word: "φῶς",
      signature: "φῶς␟1␟1", strong: "G54570", lemma: "φῶς",
    },
    target: { chapter: "1", verse: "2", bottomId: "T002", word: "was", signature: "was␟1␟1" },
    evidence: [
      { kind: "STRONGS_PRECEDENT", rawScore: 1, weight: 0.55, weightedScore: 0.55, jointCount: 7, sourceCount: 7 },
      { kind: "SURFACE_PRECEDENT", rawScore: 0, weight: 0.45, weightedScore: 0, jointCount: 0, sourceCount: 0 },
      { kind: "PHONETIC", rawScore: 0, weight: 0.25, weightedScore: 0 },
      { kind: "PROXIMITY", rawScore: 1, weight: 0.1, weightedScore: 0.1 },
    ],
    alternatives: [],
    ...overrides,
  };
}

async function renderPage(verse = "2", initialVerses: string[] = []) {
  const onClose = vi.fn();
  const utils = render(CrossVerseAlignmentModal, { props: { chapter: "1", verse, onClose, initialVerses } });
  await waitFor(() => expect(getAlignmentRange).toHaveBeenCalled());
  await waitFor(() => expect(screen.getAllByText("1:2").length).toBeGreaterThan(0));
  return { ...utils, onClose };
}

/** A row of the bar's automatic-alignment menu (2026-11-16: "Align
 *  automatically" and "Suggest links" moved there), opening the menu first. */
async function aiItem(name: RegExp): Promise<HTMLElement> {
  if (!screen.queryByRole("menu", { name: "Automatic alignment" })) await fireEvent.click(await screen.findByRole("button", { name: "Automatic alignment" }));
  return screen.findByRole("menuitem", { name });
}

async function pickUp(word: string, verse: string) {
  const bank = screen.getByLabelText(`Word bank of verse ${verse}`);
  await fireEvent.click(within(bank).getByRole("button", { name: word }));
}

describe("CrossVerseAlignmentModal", () => {
  // 2026-11-17 (Joel): no "Separate left / right". A merged cell has a split
  // button on each seam; the words before the seam keep the targets.
  it.each([["Beta", ["H001"]], ["Gamma", ["H001", "H002"]]] as const)("splits a three-word cell at the seam before %s, with no side to choose", async (word, kept) => {
    const ctx = context("2", ["Alpha", "Beta", "Gamma"], ["target"], 1);
    ctx.groups = [{ id: "joined", topIds: ctx.topTokens.map(t => t.id), bottomIds: [ctx.bottomTokens[0].id] }];
    ctx.alignment = { alignments: [{ topWords: ctx.topTokens, bottomWords: ctx.bottomTokens }], wordBank: [] };
    getAlignmentRange.mockImplementation(async (_chapter: string, verses: string[]) => rangeFor(verses, { "1": V1, "2": ctx, "3-4": V34 }));
    realignWords.mockResolvedValue(ctx);
    await renderPage();
    expect(screen.queryByText(/Separate/)).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: `Split Alpha Beta Gamma before ${word} in verse 2` }));
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "2", [...kept], [ctx.bottomTokens[0].id], ctx.alignment));
    expect(splitAlignmentSource).not.toHaveBeenCalled();
  });
  it("opens on the selected verse ±1 and shows every verse in both columns plus the verdict strip", async () => {
    await renderPage("2");
    expect(getAlignmentRange).toHaveBeenCalledWith("1", ["1", "2", "3-4"]);
    // Each verse's reference is in both alignment panels (the Verses panel shows the bare number); the bridge verse keeps its string.
    expect(screen.getAllByText("1:1")).toHaveLength(2);
    expect(screen.getAllByText("1:3-4")).toHaveLength(2);
    const strip = screen.getByRole("region", { name: "Source words" });
    // No automatic pass has run: every verse is "Not aligned yet".
    expect(within(strip).getAllByText(/Not aligned yet/)).toHaveLength(3);
    expect(within(strip).getByText("2 source · 2 target words")).toBeInTheDocument();
    expect(within(strip).getByText(/2 source · 3 target unmatched/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /verses 1–3-4/ })).toBeInTheDocument();
    // Nothing is asked of a provider on open.
    expect(autoAlignWindow).not.toHaveBeenCalled();
  });

  it("labels a source word with its renderings, not its lemma, and keeps lemma and definition on hover", async () => {
    const { container } = await renderPage("2");
    const source = [...container.querySelectorAll<HTMLElement>("button.token.source")]
      .find((element) => element.textContent?.includes("λόγος"))!;
    // The lemma is another Greek string, so it is no longer the visible label.
    await waitFor(() => expect(within(source).getByText("God, god")).toBeInTheDocument());
    expect(within(source).queryByText("λόγος·lemma")).not.toBeInTheDocument();
    // The hint is short (the lemma and the renderings); the whole definition is one click away.
    expect(source).not.toHaveAttribute("title");
    const hint = hintOf(source);
    expect(hint).toContain("λόγος·lemma");
    expect(hint).toContain("God, god");
    expect(hint).toContain("Click for the full entry");
    expect(hint).not.toContain("a deity, especially the supreme Divinity");
  });

  it("a same-verse drop realigns through alignment.realign, resending the column's existing words, then reruns local checks", async () => {
    realignWords.mockResolvedValue({ ...V2, status: "complete", gaps: { sourceUnmatched: 0, targetUnmatched: 0 } });
    // Every selected check has run on the verse (#251): re-running only the
    // alignment checks keeps its ✓.
    checkGroupsByVerse.set({ "1:2": ["tN", "tW", "tc", "alignment", "text", "languageQa"] });
    await renderPage("2");
    // Click-to-pick-up is the same one-step drop the pointer drag delivers.
    await pickUp("was", "2");
    await fireEvent.click(screen.getByLabelText(/Align picked-up word to λόγος in verse 2/));
    await waitFor(() => expect(realignWords).toHaveBeenCalledTimes(1));
    expect(realignWords).toHaveBeenCalledWith("1", "2", ["H001"], ["T001", "T002"], V2.alignment);
    await waitFor(() => expect(runVerseChecks).toHaveBeenCalledWith("1", "2", ["alignment"]));
    expect(get(alignmentStatusByVerse)["1:2"]).toBe("complete");
    expect(get(checkStatusByVerse)["1:2"]).toBe("succeeded");
    expect(get(findingsByVerse)["1:2"]).toEqual([{ id: "f1" }]);
    expect(unalignWords).not.toHaveBeenCalled();
    expect(crossVerseLink).not.toHaveBeenCalled();
  });

  it("a cross-verse drop records a Bridge-private link (#117), patches both verses and rechecks each", async () => {
    crossVerseLink.mockResolvedValue(linked());
    await renderPage("2");
    await pickUp("was", "2");
    await fireEvent.click(screen.getByLabelText(/Align picked-up word to φῶς in verse 3-4/));
    await waitFor(() => expect(crossVerseLink).toHaveBeenCalledTimes(1));
    // Source is the column (verse 3-4's φῶς), target is the dragged word (verse 2's "was").
    expect(crossVerseLink).toHaveBeenCalledWith(
      { chapter: "1", verse: "3-4", topId: "H001" },
      { chapter: "1", verse: "2", bottomId: "T002" },
    );
    expect(realignWords).not.toHaveBeenCalled();
    await waitFor(() => expect(runVerseChecks).toHaveBeenCalledWith("1", "3-4", ["alignment"]));
    await waitFor(() => expect(runVerseChecks).toHaveBeenCalledWith("1", "2", ["alignment"]));
    expect(await screen.findByText(/Cross-verse link saved/)).toBeInTheDocument();

    // The source row shows where the token is realized ...
    const cell = screen.getByLabelText(/Target words aligned to φῶς in verse 3-4/);
    expect(within(cell).getByText("was")).toBeInTheDocument();
    expect(within(cell).getByText(/realized in v\.2/)).toBeInTheDocument();
    // ... the word stays in its own verse's bank, marked and no longer draggable ...
    const bank2 = screen.getByLabelText("Word bank of verse 2");
    expect(within(bank2).queryByRole("button", { name: "was" })).not.toBeInTheDocument();
    expect(within(bank2).getByText("↔ v.3-4")).toBeInTheDocument();
    expect(byHint(bank2, /Realizes φῶς from verse 3-4/)).toBeInTheDocument();
    // ... and the range total counts it as linked, not as a gap. tC status is untouched.
    const strip = screen.getByRole("region", { name: "Source words" });
    expect(within(strip).getByText(/1 source · 2 target unmatched/)).toBeInTheDocument();
    expect(get(alignmentStatusByVerse)["1:2"]).toBe("partial");
    // Both ends of the link count as written (#291); neither verse's status moved.
    expect(get(alignmentRevisionByVerse)).toEqual({ "1:3-4": 1, "1:2": 1 });
  });

  it("the × on a linked chip or an accounted word removes the link through alignment.crossVerse.unlink", async () => {
    getAlignmentRange.mockImplementation(async (_c: string, verses: string[]) =>
      rangeFor(verses, { "1": V1, "2": linked().target, "3-4": linked().source }));
    crossVerseUnlink.mockResolvedValue({ link: LINK, source: V34, target: V2 });
    await renderPage("2");
    await fireEvent.click(screen.getByRole("button", { name: /Remove cross-verse link from φῶς to was in verse 2/ }));
    await waitFor(() => expect(crossVerseUnlink).toHaveBeenCalledWith("link-1"));
    expect(await screen.findByText(/Cross-verse link removed/)).toBeInTheDocument();
    const bank2 = screen.getByLabelText("Word bank of verse 2");
    expect(within(bank2).getByRole("button", { name: "was" })).toBeInTheDocument();
  });

  it("shows an invalidated link with its reason and lets it be removed", async () => {
    const invalid: CrossVerseLink = { ...LINK, state: "invalid", invalidReason: "was is no longer in the text of 1:2.", sourceTopId: "H001" };
    getAlignmentRange.mockImplementation(async (_c: string, verses: string[]) =>
      rangeFor(verses, { "1": V1, "2": V2, "3-4": { ...V34, crossVerseLinks: [invalid] } }));
    await renderPage("2");
    const cell = screen.getByLabelText(/Target words aligned to φῶς in verse 3-4/);
    expect(within(cell).getByText(/link invalid v\.2/)).toBeInTheDocument();
    expect(byHint(cell, "was is no longer in the text of 1:2.")).toBeInTheDocument();
    // An invalid link accounts for nothing: φῶς is still a gap.
    const strip = screen.getByRole("region", { name: "Source words" });
    expect(within(strip).getByText(/2 source · 3 target unmatched/)).toBeInTheDocument();
  });

  it("dropping a word into another verse's word bank is refused with guidance", async () => {
    await renderPage("2");
    await pickUp("was", "2");
    await fireEvent.click(screen.getByLabelText(/word bank of verse 1$/i));
    expect(await screen.findByText(/not into its word bank/)).toBeInTheDocument();
    expect(unalignWords).not.toHaveBeenCalled();
    expect(crossVerseLink).not.toHaveBeenCalled();
  });

  it("the × on an aligned card unaligns within its own verse", async () => {
    unalignWords.mockResolvedValue(V1);
    await renderPage("2");
    await fireEvent.click(screen.getByRole("button", { name: "Unalign God from θεός" }));
    await waitFor(() => expect(unalignWords).toHaveBeenCalledWith("1", "1", ["T001"], V1.alignment));
    await waitFor(() => expect(runVerseChecks).toHaveBeenCalledWith("1", "1", ["alignment"]));
  });

  it("clicking a verse's state beside its number filters both columns to that verse's gaps", async () => {
    await renderPage("2");
    const strip = screen.getByRole("region", { name: "Source words" });
    await fireEvent.click(within(strip).getByRole("button", { name: /v\.2/ }));
    // Only verse 2 remains, only its unmatched source (ἦν) and unaligned target (was).
    expect(screen.queryAllByText("1:1")).toHaveLength(0);
    expect(screen.queryByText("λόγος")).not.toBeInTheDocument();
    expect(screen.getByText("ἦν")).toBeInTheDocument();
    expect(screen.queryByText("word")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "was" })).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Show all" }));
    expect(screen.getAllByText("1:1")).toHaveLength(2);
  });

  it("changing the range refetches with the new verse strings", async () => {
    await renderPage("2");
    await fireEvent.click(screen.getByRole("button", { name: /^From: verse/ }));
    await fireEvent.click(within(screen.getByRole("listbox", { name: "From: verses" })).getByRole("option", { name: "2" }));
    await waitFor(() => expect(getAlignmentRange).toHaveBeenLastCalledWith("1", ["2", "3-4"]));
    // 2026-11-16 (Joel): the row of verse chips is gone; From and To set the range.
    expect(screen.queryByRole("group", { name: "Verses in range" })).toBeNull();
  });

  it("starts from the given verses instead of anchor ±1 when opened from a multi-selection or a finding (#118)", async () => {
    await renderPage("2", ["5", "2"]);
    expect(getAlignmentRange).toHaveBeenCalledWith("1", ["2", "5"]);
    expect(screen.getByRole("heading", { name: /verses 2–5/ })).toBeInTheDocument();
    // Only the given verses are shown, although the span covers 3-4 too.
    expect(screen.queryByLabelText("Word bank of verse 3-4")).toBeNull();
    expect(screen.getByLabelText("Word bank of verse 5")).toBeInTheDocument();
    // No suggestion is fetched for an explicit range.
    expect(analysisJobGetScopeStatus).not.toHaveBeenCalled();
  });

  it("widens the default range with the last Stage 6B run's cross-verse verses and can go back (#118)", async () => {
    analysisJobGetScopeStatus.mockResolvedValue({
      state: "ANALYZED", latestJob: { stageStatuses: { LOCATION: { runId: "run-1" } } },
    });
    semanticLocationGetRange.mockResolvedValue({
      targetInventoryId: "inv-1",
      relationships: [{ properties: ["CROSS_VERSE"], targetTokenInstanceIds: ["t5"] }],
    });
    targetSemanticGetRange.mockResolvedValue({ tokens: [{ id: "t5", displayedReference: "PHP 1:5" }] });
    await renderPage("2");
    await waitFor(() => expect(getAlignmentRange).toHaveBeenLastCalledWith("1", ["1", "2", "3-4", "5"]));
    expect(await screen.findByText(/widened with v\.5/)).toBeInTheDocument();
    expect(screen.getAllByText("1:5")).toHaveLength(2);
    await fireEvent.click(screen.getByRole("button", { name: "Back to 2 ±1" }));
    await waitFor(() => expect(getAlignmentRange).toHaveBeenLastCalledWith("1", ["1", "2", "3-4"]));
    expect(screen.queryByText(/widened with/)).not.toBeInTheDocument();
  });

  // 2026-11-15 (Joel): Word alignment is a second tab, open beside this page.
  it("reads the range again when one of its verses was saved somewhere else", async () => {
    await renderPage("2");
    await waitFor(() => expect(screen.queryByText(/Updating range/)).not.toBeInTheDocument());
    const before = getAlignmentRange.mock.calls.length;
    noteAlignmentChanged("1:9");
    await Promise.resolve();
    expect(getAlignmentRange.mock.calls.length).toBe(before);
    noteAlignmentChanged("1:2");
    await waitFor(() => expect(getAlignmentRange.mock.calls.length).toBe(before + 1));
    expect(getAlignmentRange).toHaveBeenLastCalledWith("1", ["1", "2", "3-4"]);
  });

  it("stays open when the chapter changes underneath it: the host moves it", async () => {
    const { onClose } = await renderPage("2");
    currentChapter.set("2");
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(onClose).not.toHaveBeenCalled();
  });

  describe("corpus suggestions, inline (#139, #222)", () => {
    async function suggest() {
      await fireEvent.click((await aiItem(/Suggest links/)));
      await waitFor(() => expect(crossVersePropose).toHaveBeenCalled());
    }

    function cellOf(word: string, verse: string) {
      return screen.getByLabelText(new RegExp(`Target words aligned to ${word} in verse ${verse}`));
    }

    it("asks for nothing until the reviewer asks: a proposal is a claim, not a default", async () => {
      await renderPage("2");
      expect(crossVersePropose).not.toHaveBeenCalled();
      await suggest();
      expect(crossVersePropose).toHaveBeenCalledWith("1", ["1", "2", "3-4"]);
    });

    it("shows the claim in the cell it would fill, with why on hover", async () => {
      crossVersePropose.mockResolvedValue({
        chapter: "1", verses: ["1", "2", "3-4"], proposals: [proposal()],
        calibrationVersion: "cross-verse-uncalibrated-v1",
      });
      await renderPage("2");
      await suggest();
      const cell = cellOf("φῶς", "3-4");
      expect(within(cell).getByText("was ?")).toBeInTheDocument();
      expect(byHint(cell, /rendered "was" 7× in completed verses/)).toBeInTheDocument();
    });

    it("accepting is an ordinary cross-verse link, and nothing was written before it", async () => {
      crossVersePropose.mockResolvedValue({
        chapter: "1", verses: ["1", "2", "3-4"], proposals: [proposal()],
        calibrationVersion: "cross-verse-uncalibrated-v1",
      });
      crossVerseLink.mockResolvedValue(linked());
      await renderPage("2");
      await suggest();
      expect(crossVerseLink).not.toHaveBeenCalled();
      await fireEvent.click(screen.getByRole("button", { name: "Accept was for φῶς" }));
      await waitFor(() => expect(crossVerseLink).toHaveBeenCalledWith(
        { chapter: "1", verse: "3-4", topId: "H001" },
        { chapter: "1", verse: "2", bottomId: "T002" },
      ));
      await waitFor(() => expect(runVerseChecks).toHaveBeenCalledWith("1", "3-4", ["alignment"]));
    });

    it("an ambiguous proposal has no one-click accept", async () => {
      crossVersePropose.mockResolvedValue({
        chapter: "1", verses: ["1", "2", "3-4"],
        proposals: [proposal({ status: "AMBIGUOUS", contested: true, margin: 0 })],
        calibrationVersion: "cross-verse-uncalibrated-v1",
      });
      await renderPage("2");
      await suggest();
      const cell = cellOf("φῶς", "3-4");
      expect(within(cell).getByText(/ambiguous/)).toBeInTheDocument();
      expect(within(cell).queryByRole("button", { name: /Accept/ })).not.toBeInTheDocument();
    });

    it("a refused link leaves the suggestion on screen with the error", async () => {
      crossVersePropose.mockResolvedValue({
        chapter: "1", verses: ["1", "2", "3-4"], proposals: [proposal()],
        calibrationVersion: "cross-verse-uncalibrated-v1",
      });
      crossVerseLink.mockRejectedValue(new Error("was is already aligned in verse 2."));
      await renderPage("2");
      await suggest();
      await fireEvent.click(screen.getByRole("button", { name: "Accept was for φῶς" }));
      expect(await screen.findByText(/already aligned in verse 2/)).toBeInTheDocument();
      expect(within(cellOf("φῶς", "3-4")).getByText("was ?")).toBeInTheDocument();
    });

    it("dismissing removes it without writing anything", async () => {
      crossVersePropose.mockResolvedValue({
        chapter: "1", verses: ["1", "2", "3-4"], proposals: [proposal()],
        calibrationVersion: "cross-verse-uncalibrated-v1",
      });
      await renderPage("2");
      await suggest();
      await fireEvent.click(within(cellOf("φῶς", "3-4")).getByRole("button", { name: "Dismiss this suggestion" }));
      expect(within(cellOf("φῶς", "3-4")).queryByText("was ?")).not.toBeInTheDocument();
      expect(crossVerseLink).not.toHaveBeenCalled();
    });

    it("says why there is nothing to suggest rather than showing nothing", async () => {
      crossVersePropose.mockResolvedValue({
        chapter: "1", verses: ["1", "2", "3-4"], proposals: [],
        calibrationVersion: "cross-verse-uncalibrated-v1",
        unavailable: {
          reason: "no-completed-alignments",
          message: "Cross-verse suggestions are learned from this project's own completed alignments…",
        },
      });
      await renderPage("2");
      await suggest();
      expect(screen.getByText(/Cross-verse suggestions are learned from this project's own completed alignments…/)).toBeInTheDocument();
    });

    it("reports suggestions as stale when the range moves under them", async () => {
      crossVersePropose.mockResolvedValue({
        chapter: "1", verses: ["1", "2", "3-4"], proposals: [proposal()],
        calibrationVersion: "cross-verse-uncalibrated-v1",
      });
      await renderPage("2");
      await suggest();
      expect(screen.queryByText(/range changed/i)).not.toBeInTheDocument();
      await fireEvent.click(screen.getByRole("button", { name: /^To: verse/ }));
      await fireEvent.click(within(screen.getByRole("listbox", { name: "To: verses" })).getByRole("option", { name: "5" }));
      await waitFor(() => expect(getAlignmentRange).toHaveBeenLastCalledWith("1", ["1", "2", "3-4", "5"]));
      expect(await screen.findByText(/The range changed since the suggestions were worked out/)).toBeInTheDocument();
    });
  });

  describe("automatic alignment (#222)", () => {
    const sig = (w: string) => `${w}␟1␟1`;
    /** v.2 after a pass: λόγος → word placed (ai), ἦν left unplaced, "was" disputed. */
    function after(): AutoAlignWindowResult {
      const v2 = { ...V2, autoAlign: { verdict: "NEEDS_REVIEW" as const, runId: "aa-1", createdAt: "", stale: false, issues: 1, suggestions: 1 } };
      return {
        chapter: "1", verses: ["1", "2", "3-4"], runId: "aa-1", calibrationVersion: "two-pass-agreement-v1",
        corpus: { checked: false, reason: "no-completed-alignments" },
        usage: { calls: 2, totalTokens: 41280, estimatedCostUSD: 0.13 },
        results: [
          { verse: "1", verdict: "ALIGNED_CLEAN", applied: { groups: [{ tops: [sig("θεός")], bottoms: [sig("God")] }], links: [], nulls: [] },
            issues: [], suggestions: [], context: { ...V1, accounted: true, autoAlign: { verdict: "ALIGNED_CLEAN", runId: "aa-1", createdAt: "", stale: false, issues: 0, suggestions: 0 } } },
          { verse: "2", verdict: "NEEDS_REVIEW", applied: { groups: [{ tops: [sig("λόγος")], bottoms: [sig("word")] }], links: [], nulls: [] },
            issues: [{ kind: "POSSIBLE_OMISSION", side: "source", signature: sig("ἦν"), word: "ἦν", id: "H002", note: "no word for 'was' (to be)" }],
            suggestions: [{
              kind: "link", status: "UNCERTAIN", votes: { "source-first": true, "target-first": false },
              source: { side: "source", chapter: "1", verse: "3-4", signature: sig("φῶς"), word: "φῶς", id: "H001" },
              target: { side: "target", chapter: "1", verse: "2", signature: sig("was"), word: "was", id: "T002" },
              token: null, reason: "light shone", note: "", confidence: 70,
            }],
            context: v2 },
          { verse: "3-4", verdict: "NEEDS_REVIEW", applied: { groups: [], links: [], nulls: [] }, issues: [],
            suggestions: [], context: { ...V34, autoAlign: { verdict: "NEEDS_REVIEW", runId: "aa-1", createdAt: "", stale: false, issues: 0, suggestions: 1 } } },
        ],
      };
    }

    it("runs only on a click, then shows the verdicts, the omission and the suggestion in place", async () => {
      autoAlignWindow.mockResolvedValue(after());
      await renderPage("2");
      await fireEvent.click(await aiItem(/Align automatically/));
      await waitFor(() => expect(autoAlignWindow).toHaveBeenCalledWith("1", ["1", "2", "3-4"], true, expect.any(Function)));
      const strip = screen.getByRole("region", { name: "Source words" });
      expect(await within(strip).findByText(/✓ Aligned/)).toBeInTheDocument();
      expect(within(strip).getAllByText(/Needs review/).length).toBeGreaterThan(0);
      // The omission sits on ἦν's cell with the model's note and a way to say why it is fine.
      const cell = screen.getByLabelText(/Target words aligned to ἦν in verse 2/);
      expect(within(cell).getByText("possible omission")).toBeInTheDocument();
      expect(byHint(cell, "no word for 'was' (to be)")).toBeInTheDocument();
      // The disputed link shows in φῶς's cell, with both votes on hover.
      const phos = screen.getByLabelText(/Target words aligned to φῶς in verse 3-4/);
      expect(within(phos).getByText("was ?")).toBeInTheDocument();
      expect(byHint(phos, /source-first: yes · target-first: no/)).toBeInTheDocument();
      // The placed group is tagged as the pass's own.
      expect(screen.getAllByText("ai").length).toBeGreaterThan(0);
      expect(screen.getByText(/Last run: 2 requests · 41,280 tokens/)).toBeInTheDocument();
      // Every verse was rechecked so the editor's findings are current.
      await waitFor(() => expect(runVerseChecks).toHaveBeenCalledWith("1", "2", ["alignment"]));
    });

    it("is disabled with the reason when no key is configured, and for a range it cannot take", async () => {
      getSettings.mockResolvedValue({ hasApiKey: false });
      await renderPage("2");
      const button = await aiItem(/Align automatically/);
      await waitFor(() => expect(button).toBeDisabled());
      expect(hintOf(button)).toBe("Add an API key or sign in with ChatGPT in Settings to align automatically");
      expect((await aiItem(/Suggest links/))).toBeEnabled();
    });

    it("Not missing ▸ Implicit records a null decision through alignment.null.set", async () => {
      autoAlignWindow.mockResolvedValue(after());
      nullSet.mockResolvedValue({ decision: {}, context: V2 });
      await renderPage("2");
      await fireEvent.click(await aiItem(/Align automatically/));
      // The page rechecks every verse after a run; controls wait for that.
      const notMissing = await screen.findByRole("button", { name: "Not missing ▾" });
      await waitFor(() => expect(notMissing).toBeEnabled());
      await fireEvent.click(notMissing);
      await fireEvent.click(screen.getByRole("menuitem", { name: /Implicit/ }));
      await waitFor(() => expect(nullSet).toHaveBeenCalledWith("1", "2", "source", "H002", "IMPLICIT", ""));
    });

    it("accepting a disputed cross-verse suggestion is an ordinary link", async () => {
      autoAlignWindow.mockResolvedValue(after());
      crossVerseLink.mockResolvedValue(linked());
      await renderPage("2");
      await fireEvent.click(await aiItem(/Align automatically/));
      const accept = await screen.findByRole("button", { name: "Accept was for φῶς" });
      await waitFor(() => expect(accept).toBeEnabled());
      await fireEvent.click(accept);
      await waitFor(() => expect(crossVerseLink).toHaveBeenCalledWith(
        { chapter: "1", verse: "3-4", topId: "H001" },
        { chapter: "1", verse: "2", bottomId: "T002" },
      ));
    });

    it("Undo a verse calls alignment.autoAlign.revert for that verse", async () => {
      autoAlignWindow.mockResolvedValue(after());
      autoAlignRevert.mockResolvedValue({ chapter: "1", verse: "1", skipped: [], context: V1 });
      await renderPage("2");
      await fireEvent.click(await aiItem(/Align automatically/));
      const undo = await screen.findByLabelText("Undo a verse");
      await waitFor(() => expect(undo).toBeEnabled());
      await fireEvent.change(undo, { target: { value: "1" } });
      await waitFor(() => expect(autoAlignRevert).toHaveBeenCalledWith("1", "1"));
      expect(await screen.findByText(/Restored v\.1/)).toBeInTheDocument();
    });

    it("an unavailable provider is reported, not thrown", async () => {
      autoAlignWindow.mockResolvedValue({
        chapter: "1", verses: ["1", "2", "3-4"], runId: "aa-2", calibrationVersion: "two-pass-agreement-v1", results: [],
        unavailable: { reason: "no-api-key", message: "No OpenAI-compatible API key is configured." },
      });
      await renderPage("2");
      await fireEvent.click(await aiItem(/Align automatically/));
      expect(await screen.findByText(/No OpenAI-compatible API key is configured/)).toBeInTheDocument();
    });

    /** A window-job status as the engine reports it (#242). */
    function status(over: Partial<AutoAlignJobStatus> = {}): AutoAlignJobStatus {
      return {
        jobId: "j1", scope: "window", apply: true, state: "running", stage: "", chapters: ["1"], windowsTotal: 1,
        windowsDone: 0, windowsFailed: 0, percent: 0, currentWindow: { chapter: "1", verses: ["1", "2", "3-4"] },
        currentPass: null, windowResult: null, verdictCounts: {}, verdicts: {},
        usage: { calls: 0, totalTokens: 0, estimatedCostUSD: 0 }, error: null, unavailable: null, resumeOf: "",
        createdAt: "", finishedAt: null, ...over,
      };
    }

    it("the button shows the pass the job status reports, not a timer (#243)", async () => {
      let report: (s: AutoAlignJobStatus) => void = () => {};
      let finish: (r: AutoAlignWindowResult) => void = () => {};
      autoAlignWindow.mockImplementation((_c: string, _v: string[], _a: boolean, onProgress: (s: AutoAlignJobStatus) => void) => {
        report = onProgress;
        return new Promise((resolve) => { finish = resolve; });
      });
      await renderPage("2");
      await fireEvent.click(await aiItem(/Align automatically/));
      expect(await screen.findByText("Starting…")).toBeInTheDocument();
      report(status({ currentPass: { number: 1, of: 2, direction: "source-first", stage: "" } }));
      expect(await screen.findByText("Aligning… pass 1 of 2")).toBeInTheDocument();
      report(status({ currentPass: { number: 2, of: 2, direction: "target-first", stage: "" } }));
      expect(await screen.findByText("Aligning… pass 2 of 2")).toBeInTheDocument();
      report(status({ currentPass: { number: null, of: 2, direction: "", stage: "reconcile" } }));
      expect(await screen.findByText("Comparing the two passes…")).toBeInTheDocument();
      finish(after());
      expect(await aiItem(/Align again/)).toBeInTheDocument();
    });

    it("a provider timeout says nothing was changed, with the raw text one click away, and leaves the page usable", async () => {
      autoAlignWindow.mockImplementation(async (_c: string, _v: string[], _a: boolean, onProgress: (s: AutoAlignJobStatus) => void) => {
        onProgress(status({
          state: "failed", windowsDone: 1, windowsFailed: 1, error: "1 window(s) failed.",
          results: { "1:1-3-4": { chapter: "1", verses: ["1", "2", "3-4"], status: "failed", error: "The read operation timed out" } },
        }));
        throw new Error("1 window(s) failed.");
      });
      await renderPage("2");
      await fireEvent.click(await aiItem(/Align automatically/));
      const alert = await screen.findByRole("alert");
      expect(alert.textContent).toContain("The AI provider did not answer within 4 minutes; nothing was changed.");
      expect(alert.textContent).not.toContain("1 window(s) failed.");
      const details = within(alert).getByText("Show details").closest("details") as HTMLDetailsElement;
      expect(details.open).toBe(false);
      expect(within(details).getByText("The read operation timed out")).toBeInTheDocument();
      await waitFor(async () => expect(await aiItem(/Align automatically/)).toBeEnabled());
      expect((await aiItem(/Suggest links/))).toBeEnabled();
    });

    it("an error with no plain wording is shown as it is, with no details", async () => {
      autoAlignWindow.mockRejectedValue(new Error("Verse/project data changed while AI was preparing alignment"));
      await renderPage("2");
      await fireEvent.click(await aiItem(/Align automatically/));
      const alert = await screen.findByRole("alert");
      expect(alert.textContent).toContain("Verse/project data changed while AI was preparing alignment");
      expect(within(alert).queryByText("Show details")).toBeNull();
    });

    it("loads the stored verdict of a verse an earlier pass ran on", async () => {
      const v1 = { ...V1, accounted: true, autoAlign: { verdict: "ALIGNED_CLEAN" as const, runId: "aa-0", createdAt: "", stale: false, issues: 0, suggestions: 0 } };
      getAlignmentRange.mockImplementation(async (_c: string, verses: string[]) =>
        rangeFor(verses, { "1": v1, "2": V2, "3-4": V34 }));
      autoAlignVerdict.mockResolvedValue({ chapter: "1", verse: "1", verdict: {
        chapter: "1", verse: "1", verdict: "ALIGNED_CLEAN", runId: "aa-0", applyRequested: true, issues: [], suggestions: [],
        applied: { groups: [], links: [], nulls: [] }, window: ["1", "2"], createdAt: "",
      } });
      await renderPage("2");
      await waitFor(() => expect(autoAlignVerdict).toHaveBeenCalledWith("1", "1"));
      expect(autoAlignVerdict).toHaveBeenCalledTimes(1);
      expect(await within(screen.getByRole("region", { name: "Source words" })).findByText(/✓ Aligned/)).toBeInTheDocument();
    });
  });
});

// 2026-11-16 (Joel): the page is drawn as the Word alignment tab is: its bar,
// three panels with their own saved layout, instant hints, and a note that
// is not a row of the page.
describe("CrossVerseAlignmentModal, the page as three panels", () => {
  beforeEach(() => { crossPanelLayout.reset(); wordPanelLayout.reset(); });

  it("draws the verses, the source words and the target words as panels, with the range in the bar", async () => {
    await renderPage("2");
    for (const name of ["Verses", "Source words", "Target words"]) expect(screen.getByRole("region", { name })).toBeInTheDocument();
    const bar = document.querySelector("header")!;
    expect(bar).toHaveTextContent("Chapter 1");
    // From and To are the Verses panel's grid picker, not the browser's list.
    expect(bar.querySelector("select")).toBeNull();
    const from = within(bar as HTMLElement).getByRole("button", { name: /^From: verse 1\./ });
    expect(within(bar as HTMLElement).getByRole("button", { name: /^To: verse 3-4\./ })).toBeInTheDocument();
    await fireEvent.click(from);
    const grid = screen.getByRole("listbox", { name: "From: verses" });
    expect(within(grid).getAllByRole("option").map((cell) => cell.textContent)).toEqual(["1", "2", "3-4", "5"]);
    expect(within(grid).getByRole("option", { name: "1" })).toHaveAttribute("aria-selected", "true");
    await fireEvent.click(within(grid).getByRole("option", { name: "2" }));
    expect(screen.queryByRole("listbox", { name: "From: verses" })).toBeNull();
    await waitFor(() => expect(within(bar as HTMLElement).getByRole("button", { name: /^From: verse 2\./ })).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: /^Cross-verse alignment · Chapter 1/ })).toHaveClass("sr-only");
    // The verses panel shares the height here (a range is long), and every line between panels drags.
    expect(document.querySelector<HTMLElement>(".word-panels")!.dataset.gridRows).toBe("minmax(96px, 25fr) minmax(96px, 75fr)");
    expect(screen.getByRole("slider", { name: "Resize panel heights" })).toBeInTheDocument();
    expect(screen.getByRole("slider", { name: "Resize panel widths" })).toBeInTheDocument();
    // No chapter tally: the status bar under the editor has it.
    expect(screen.queryByText(/^Chapter: /)).toBeNull();
  });

  it("keeps its own layout and text sizes, apart from the Word alignment tab's", async () => {
    await renderPage("2");
    await fireEvent.click(screen.getByRole("button", { name: "Layout" }));
    await fireEvent.click(screen.getByRole("menuitemradio", { name: "Three columns" }));
    expect(crossPanelLayout.preset(get(crossPanelLayout.tree))).toBe("columns3");
    expect(wordPanelLayout.preset(get(wordPanelLayout.tree))).toBe("top1bottom2");
    await fireEvent.click(screen.getByRole("button", { name: "Larger target words text" }));
    expect(get(crossPanelLayout.scales).target).toBe(1.15);
    expect(get(wordPanelLayout.scales).target).toBe(1);
  });

  it("shows a note over the page, not as a row of it, and uses no browser tooltip", async () => {
    realignWords.mockResolvedValue({ ...V2, status: "complete", gaps: { sourceUnmatched: 0, targetUnmatched: 0 } });
    await renderPage("2");
    await pickUp("was", "2");
    await fireEvent.click(screen.getByLabelText(/Align picked-up word to λόγος in verse 2/));
    const note = await screen.findByText(/alignment checks for 1:2 are current/);
    expect(note.closest(".toasts")).not.toBeNull();
    expect(note.closest("[data-word-panel]")).toBeNull();
    expect(crossPageSource).not.toMatch(/\stitle=/);
  });

  it("moves a word one place in a cell that holds several, as on the Word alignment tab", async () => {
    const two: AlignmentContext = { ...V2, groups: [{ id: "G001", topIds: ["H001"], bottomIds: ["T001", "T002"] }, { id: "G002", topIds: ["H002"], bottomIds: [] }] };
    getAlignmentRange.mockImplementation(async (_chapter: string, verses: string[]) => rangeFor(verses, { "1": V1, "2": two, "3-4": V34 }));
    realignWords.mockResolvedValue(two);
    await renderPage("2");
    expect(screen.getByRole("button", { name: "Move word earlier" })).toBeDisabled();
    await fireEvent.click(screen.getByRole("button", { name: "Move word later" }));
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "2", ["H001"], ["T002", "T001"], two.alignment));
    // One toolbar per card: earlier, later, remove.
    const tools = screen.getByRole("button", { name: "Unalign word from λόγος" }).closest(".card-tools")!;
    expect(tools.querySelectorAll("button")).toHaveLength(3);
  });

  // The cards and cells carry the Word alignment tab's values.
  it("styles its cells and cards as the Word alignment tab does", () => {
    const block = (selector: string) => crossPageSource.match(new RegExp(`\n  ${selector.replace(/[.\[\]()]/g, "\$&")} \{([^}]*)\}`))?.[1] ?? "";
    expect(block(".drop-cell")).toMatch(/justify-content:\s*center/);
    expect(block(".drop-cell")).toMatch(/border:\s*1px dashed transparent/);
    expect(block(".token.source")).toMatch(/background:\s*var\(--term-bg\)/);
    expect(block(".token.target.unaligned")).toMatch(/background:\s*var\(--accent-bg\)/);
    expect(block(".row")).toMatch(/align-items:\s*center/);
  });

  // 2026-11-16 (Joel): Undo and the "more" menu are on the bar, as on the
  // Word alignment tab; a verse's heading is its number only.
  it("has Undo and one reset-and-backups menu on the bar, for the whole range", async () => {
    const edited: AlignmentContext = { ...V2, history: [{ id: "h1", timestamp: "2020-01-02T10:00:00Z", operation: "realign" }] as never };
    const older: AlignmentContext = { ...V34, history: [{ id: "h0", timestamp: "2020-01-01T10:00:00Z", operation: "unalign" }] as never };
    getAlignmentRange.mockImplementation(async (_chapter: string, verses: string[]) => rangeFor(verses, { "1": V1, "2": edited, "3-4": older }));
    restoreAlignment.mockResolvedValue(edited);
    await renderPage("2");
    const bar = document.querySelector("header") as HTMLElement;
    // No per-verse controls are left in the panels.
    expect(screen.queryByRole("button", { name: /Undo and reset verse/ })).toBeNull();
    // The range's state sits beside From and To.
    const state = within(bar).getByRole("group", { name: "Alignment of the range" });
    // Verse 1 is complete, verse 2 partial, verse 3-4 untouched.
    expect(Array.from(state.querySelectorAll(".status")).map((chip) => chip.textContent)).toEqual(["1 partial", "1 untouched", "1 complete"]);
    const menu = document.querySelector<HTMLElement>('[role="menu"][aria-label="Reset and backups"]')!;
    expect(menu).not.toBeVisible();
    await fireEvent.click(within(bar).getByRole("button", { name: "Reset and backups" }));
    expect(menu).toBeVisible();
    expect(within(menu).getByRole("menuitem", { name: /Reset chapter alignment/ })).toBeInTheDocument();
    expect(within(menu).getAllByRole("menuitem", { name: /Reset verse alignment/ })).toHaveLength(3);
    expect(menu).toHaveTextContent("Verse 1:2");
    // The range's backups, newest first, each named by its verse.
    const backups = within(menu).getAllByRole("menuitem").filter((row) => /before a word/.test(row.textContent || ""));
    expect(backups.map((row) => row.textContent?.split(" · ")[0])).toEqual(["1:2", "1:3-4"]);
    await fireEvent.keyDown(window, { key: "Escape" });
    expect(menu).not.toBeVisible();
    // Undo steps back the newest change in the range: verse 2's.
    const undo = within(bar).getByRole("button", { name: "Undo last change" });
    expect(hintOf(undo)).toContain("1:2");
    await fireEvent.click(undo);
    await waitFor(() => expect(restoreAlignment).toHaveBeenCalledWith("1", "2", "h1", edited.alignment));
  });

  it("has nothing to undo in a range with no change, and reads one verse as the Word alignment bar does", async () => {
    await renderPage("2");
    expect(screen.getByRole("button", { name: "Undo last change" })).toBeDisabled();
    await fireEvent.click(screen.getByRole("button", { name: /^From: verse/ }));
    await fireEvent.click(within(screen.getByRole("listbox", { name: "From: verses" })).getByRole("option", { name: "3-4" }));
    await waitFor(() => expect(screen.getByRole("group", { name: "Alignment of the range" })).toHaveTextContent(/^Verse: /));
  });

  // 2026-11-16 (Joel): automatic alignment, link suggestions and the chapter
  // reset are one menu on the bar; the row of buttons and the verse chips are gone.
  it("keeps automatic alignment and link suggestions in one menu on the bar", async () => {
    await renderPage("2");
    const bar = document.querySelector("header") as HTMLElement;
    const button = within(bar).getByRole("button", { name: "Automatic alignment" });
    const menu = document.querySelector<HTMLElement>('[role="menu"][aria-label="Automatic alignment"]')!;
    expect(menu).not.toBeVisible();
    // Nothing of it is drawn outside the menu.
    expect(screen.queryByRole("button", { name: /Align automatically|Suggest links|Reset chapter alignment/ })).toBeNull();
    await fireEvent.click(button);
    expect(menu).toBeVisible();
    expect(within(menu).getAllByRole("menuitem").map((item) => item.querySelector(".ai-name")?.textContent)).toEqual(
      ["Align automatically", "Suggest links"]);
    // Each row says what it does, so no separate info icon is needed.
    expect(within(menu).getByRole("menuitem", { name: /Suggest links/ })).toHaveTextContent("No AI provider is needed");
    await fireEvent.keyDown(window, { key: "Escape" });
    expect(menu).not.toBeVisible();
    // Choosing a row closes the menu and runs it.
    await fireEvent.click(await aiItem(/Suggest links/));
    expect(menu).not.toBeVisible();
    await waitFor(() => expect(crossVersePropose).toHaveBeenCalled());
  });

  // 2026-11-16 (Joel): the row of verse cards under the bar is gone. Which
  // verses are shown is a grid in the Verses panel's title row, where every
  // shown verse is drawn as chosen and a click switches one off or on.
  // 2026-11-16 (Joel): the way to Word alignment from this page, as that tab
  // has one to this page; a tab that is open already is shown, and says so.
  it("opens Word alignment from an icon on the bar, and shows it when it is already open", async () => {
    alignmentOpen.set(false);
    await renderPage("2");
    const word = within(document.querySelector("header") as HTMLElement).getByRole("button", { name: "Word alignment" });
    expect(hintOf(word)).toBe("Word alignment: the words of verse 2 alone");
    await fireEvent.click(word);
    expect(get(alignmentOpen)).toBe(true);
    expect(get(alignmentKey)).toBe("1:2");
    const request = get(tabRequest).seq;
    expect(hintOf(word)).toBe("Word alignment is already open. Click to show it");
    await fireEvent.click(word);
    expect(get(tabRequest)).toMatchObject({ id: "alignment", seq: request + 1 });
    alignmentOpen.set(false);
  });

  it("reads each verse under its bare number, with a hairline between verses", async () => {
    await renderPage("2");
    const verses = screen.getByRole("region", { name: "Verses" });
    expect(Array.from(verses.querySelectorAll(".read-num")).map((el) => el.textContent)).toEqual(["1", "2", "3-4"]);
    expect(verses).not.toHaveTextContent("1:2");
    const row = crossPageSource.match(/\n  \.range-reading \{([^}]*)\}/)?.[1] ?? "";
    expect(row).toMatch(/border-top:\s*1px solid/);
    expect(row).toMatch(/margin:\s*0;/);
  });

  it("chooses the verses shown from a grid in the Verses panel, and has no row of verse cards", async () => {
    await renderPage("2");
    expect(document.querySelector(".verdict-strip")).toBeNull();
    const verses = screen.getByRole("region", { name: "Verses" });
    const button = within(verses).getByRole("button", { name: "Verses shown" });
    // The last control of the row, and always shown.
    expect(verses.querySelector(".bar .tools")!.lastElementChild).toBe(button);
    await fireEvent.click(button);
    const grid = screen.getByRole("group", { name: "Verses shown" });
    const cells = within(grid).getAllByRole("button");
    expect(cells.map((cell) => `${cell.textContent}:${cell.getAttribute("aria-pressed")}`)).toEqual(["1:true", "2:true", "3-4:true"]);
    // Switching one off reloads the range without it, in all three panels; the grid stays open.
    await fireEvent.click(within(grid).getByRole("button", { name: "Verse 3-4" }));
    await waitFor(() => expect(getAlignmentRange).toHaveBeenLastCalledWith("1", ["1", "2"]));
    await waitFor(() => expect(screen.queryAllByText("1:3-4")).toHaveLength(0));
    expect(within(screen.getByRole("group", { name: "Verses shown" })).getByRole("button", { name: "Verse 3-4" })).toHaveAttribute("aria-pressed", "false");
    // And back on.
    await fireEvent.click(within(screen.getByRole("group", { name: "Verses shown" })).getByRole("button", { name: "Verse 3-4" }));
    await waitFor(() => expect(getAlignmentRange).toHaveBeenLastCalledWith("1", ["1", "2", "3-4"]));
    await fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("group", { name: "Verses shown" })).toBeNull();
  });

  it("picks several words of one verse and places them together; a pick in another verse starts again", async () => {
    realignWords.mockResolvedValue(V34);
    await renderPage("2");
    const bank = screen.getByLabelText("Word bank of verse 3-4");
    await fireEvent.click(within(bank).getByRole("button", { name: "light" }));
    await fireEvent.click(within(bank).getByRole("button", { name: "shone" }), { ctrlKey: true });
    expect(screen.getByText("2 picked")).toBeInTheDocument();
    // Ctrl-click in another verse does not mix verses: it starts a new pick.
    await fireEvent.click(screen.getByRole("button", { name: "was" }), { ctrlKey: true });
    expect(screen.queryByText("2 picked")).toBeNull();
    await fireEvent.keyDown(window, { key: "Escape" });
    await fireEvent.click(within(bank).getByRole("button", { name: "light" }));
    await fireEvent.click(within(bank).getByRole("button", { name: "shone" }), { shiftKey: true });
    await fireEvent.click(screen.getByLabelText("Align 2 picked-up words to φῶς in verse 3-4"));
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "3-4", ["H001"], ["T001", "T002"], V34.alignment));
    expect(realignWords).toHaveBeenCalledTimes(1);
  });

  // A verse block is as tall as its partner in the other column, so its word
  // bank must fill it: the empty room under the words starts a selection too.
  it("lets a selection box start anywhere in a verse's block, not only on the row of words", async () => {
    await renderPage("2");
    const bank = screen.getByLabelText("Word bank of verse 3-4");
    const block = bank.closest(".verse-block")!;
    expect(block.closest(".targets")).not.toBeNull();
    expect(crossPageSource).toMatch(/\.targets \.verse-block \{ display: flex; flex-direction: column; \}/);
    expect(crossPageSource).toMatch(/\.targets \.bank \{ flex: 1 1 auto; \}/);
    // The bank is the last thing in the block, so nothing under it is outside it.
    expect(block.lastElementChild).toBe(bank);
  });

  // 2026-11-17 (Joel): the same on this page.
  it("skips an aligned word between two unaligned ones on a Shift-click run", async () => {
    const three = context("2", ["α", "β"], ["one", "two", "three"], 0);
    const middle: AlignmentContext = { ...three, groups: [{ id: "G001", topIds: ["H001"], bottomIds: ["T002"] }, { id: "G002", topIds: ["H002"], bottomIds: [] }] };
    getAlignmentRange.mockImplementation(async (_chapter: string, verses: string[]) => rangeFor(verses, { "1": V1, "2": middle, "3-4": V34 }));
    realignWords.mockResolvedValue(middle);
    await renderPage("2");
    const bank = screen.getByLabelText("Word bank of verse 2");
    await fireEvent.click(within(bank).getByRole("button", { name: "one" }));
    await fireEvent.click(within(bank).getByRole("button", { name: "three" }), { shiftKey: true });
    expect(screen.getByText("2 picked")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pick up two from α" })).toHaveAttribute("aria-pressed", "false");
    await fireEvent.click(screen.getByLabelText("Align 2 picked-up words to β in verse 2"));
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "2", ["H002"], ["T001", "T003"], middle.alignment));
  });

  it("links several picked words to a source word of another verse, one link each", async () => {
    crossVerseLink.mockResolvedValue({ link: LINK, source: V2, target: V34 });
    await renderPage("2");
    const bank = screen.getByLabelText("Word bank of verse 3-4");
    await fireEvent.click(within(bank).getByRole("button", { name: "light" }));
    await fireEvent.click(within(bank).getByRole("button", { name: "shone" }), { ctrlKey: true });
    await fireEvent.click(screen.getByLabelText("Align 2 picked-up words to ἦν in verse 2"));
    await waitFor(() => expect(crossVerseLink).toHaveBeenCalledTimes(2));
    expect(crossVerseLink).toHaveBeenNthCalledWith(1, { chapter: "1", verse: "2", topId: "H002" }, { chapter: "1", verse: "3-4", bottomId: "T001" });
    expect(crossVerseLink).toHaveBeenNthCalledWith(2, { chapter: "1", verse: "2", topId: "H002" }, { chapter: "1", verse: "3-4", bottomId: "T002" });
    expect(await screen.findByText(/2 words linked across verses/)).toBeInTheDocument();
  });

  it("joins a source word with the one before it", async () => {
    realignWords.mockResolvedValue(V2);
    await renderPage("2");
    await fireEvent.click(screen.getByRole("button", { name: "Join ἦν with the previous source word in verse 2" }));
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "2", ["H001", "H002"], ["T001"], V2.alignment));
    // Verse 3-4 has one source word: nothing to join.
    expect(screen.queryByRole("button", { name: /with the previous source word in verse 3-4/ })).toBeNull();
  });

  // 2026-11-18 (the team): no target word has to be placed first.
  it("joins two source words that have no target word", async () => {
    const empty: AlignmentContext = { ...V2, groups: [] };
    getAlignmentRange.mockImplementation(async (_chapter: string, verses: string[]) => rangeFor(verses, { "1": V1, "2": empty, "3-4": V34 }));
    realignWords.mockResolvedValue(empty);
    await renderPage("2");
    const join = screen.getByRole("button", { name: "Join ἦν with the previous source word in verse 2" });
    expect(join).not.toBeDisabled();
    await fireEvent.click(join);
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "2", ["H001", "H002"], [], empty.alignment));
  });

  // Two source words that share a cross-verse link are drawn as one cell too,
  // but they are not one alignment group: a realign cannot part them, so the
  // cell has no split button. Its link is removed with the x on its card.
  it("shows no split button on a cell merged only by a cross-verse link", async () => {
    const group = {
      groupId: "cv-1", state: "active" as const, relation: "many-to-one" as never,
      sourceChapter: "1", sourceVerse: "2", targetChapter: "1", targetVerse: "3-4",
      sources: [{ word: "λόγος", topId: "H001" }, { word: "ἦν", topId: "H002" }],
      targets: [{ word: "light", bottomId: "T001" }],
      sourceTopIds: ["H001", "H002"], targetBottomIds: ["T001"], linkIds: ["link-a", "link-b"],
    };
    const linkedCell = { ...V2, groups: [], crossVerseGroups: [group] } as unknown as AlignmentContext;
    getAlignmentRange.mockImplementation(async (_chapter: string, verses: string[]) => rangeFor(verses, { "1": V1, "2": linkedCell, "3-4": V34 }));
    await renderPage("2");
    expect(document.querySelector(".source-words.joined")).not.toBeNull();
    expect(screen.queryByRole("button", { name: /^Split .* in verse 2$/ })).toBeNull();
  });

  it("splits a joined cell at its seam; the first word keeps the target", async () => {
    const joined: AlignmentContext = { ...V2, groups: [{ id: "G001", topIds: ["H001", "H002"], bottomIds: ["T001"] }] };
    getAlignmentRange.mockImplementation(async (_chapter: string, verses: string[]) => rangeFor(verses, { "1": V1, "2": joined, "3-4": V34 }));
    realignWords.mockResolvedValue(joined);
    await renderPage("2");
    await fireEvent.click(screen.getByRole("button", { name: "Split λόγος ἦν before ἦν in verse 2" }));
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "2", ["H001"], ["T001"], joined.alignment));
  });

  // 2026-11-18 (Joel): merged, then the target word taken away: it still splits.
  it("splits a joined cell that has no target word", async () => {
    const joined: AlignmentContext = { ...V2, groups: [{ id: "G001", topIds: ["H001", "H002"], bottomIds: [] }] };
    getAlignmentRange.mockImplementation(async (_chapter: string, verses: string[]) => rangeFor(verses, { "1": V1, "2": joined, "3-4": V34 }));
    realignWords.mockResolvedValue(joined);
    await renderPage("2");
    const split = screen.getByRole("button", { name: "Split λόγος ἦν before ἦν in verse 2" });
    expect(split).not.toBeDisabled();
    await fireEvent.click(split);
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "2", ["H001"], [], joined.alignment));
  });

  it("lets an aligned word be picked up and moved, and marks each card as a place to drop", async () => {
    realignWords.mockResolvedValue(V2);
    await renderPage("2");
    const card = screen.getByRole("button", { name: "Pick up word from λόγος" });
    expect(card.closest("[data-drop-slot]")).toHaveAttribute("data-drop-slot", "2|T001");
    await fireEvent.click(card);
    await fireEvent.click(screen.getByLabelText("Align picked-up word to ἦν in verse 2"));
    await waitFor(() => expect(realignWords).toHaveBeenCalledWith("1", "2", ["H002"], ["T001"], V2.alignment));
    // An aligned word is not linked to another verse while it is aligned.
    await waitFor(() => expect(screen.getByRole("button", { name: "Pick up word from λόγος" })).toBeEnabled());
    await fireEvent.click(screen.getByRole("button", { name: "Pick up word from λόγος" }));
    await fireEvent.click(screen.getByLabelText("Align picked-up word to φῶς in verse 3-4"));
    expect(crossVerseLink).not.toHaveBeenCalled();
    expect(await screen.findByText(/Remove it from its cell first/)).toBeInTheDocument();
  });
});
