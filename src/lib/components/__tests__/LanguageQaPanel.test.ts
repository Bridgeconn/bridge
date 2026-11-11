// @ts-expect-error The app tsconfig has no node types; vitest runs under node.
import { readFileSync } from "node:fs";
// @ts-expect-error As above.
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { get } from "svelte/store";
import type { LanguageQaFinding, LanguageQaStatus } from "../../types/languageQa";
import {
  focusedFindingId, chapterVerseNums, currentChapter, languageQaFindingsByVerse, project, selectedVerse, verseKey,
} from "../../stores";
import { lqaFinding } from "./languageQaFixture";

const statusCall = vi.fn();
const historyCall = vi.fn();
const learnedListCall = vi.fn();
const learnedForgetCall = vi.fn();
const learnedRestoreCall = vi.fn();
const flagsListCall = vi.fn();
const flagUpdateCall = vi.fn();
const pickReviewCall = vi.fn();
const reviewPreviewCall = vi.fn();
const reviewImportCall = vi.fn();
const bookWordsCall = vi.fn();
const wordsAddCall = vi.fn();
const verseHistoryCall = vi.fn();
const verseCall = vi.fn();
const decideCall = vi.fn();
const chapterCountCall = vi.fn();
vi.mock("../../api/bridgeClient", () => ({ bridge: {
  languageQaStatus: (...args: unknown[]) => statusCall(...args),
  languageQaChapterCount: (...args: unknown[]) => chapterCountCall(...args),
  languageQaHistory: (...args: unknown[]) => historyCall(...args),
  languageQaLearnedList: (...args: unknown[]) => learnedListCall(...args),
  languageQaLearnedForget: (...args: unknown[]) => learnedForgetCall(...args),
  languageQaLearnedRestore: (...args: unknown[]) => learnedRestoreCall(...args),
  languageQaFlagsList: (...args: unknown[]) => flagsListCall(...args),
  languageQaFlagUpdate: (...args: unknown[]) => flagUpdateCall(...args),
  pickJsonFile: (...args: unknown[]) => pickReviewCall(...args),
  languageQaReviewPreview: (...args: unknown[]) => reviewPreviewCall(...args),
  languageQaReviewImport: (...args: unknown[]) => reviewImportCall(...args),
  languageQaBookWords: (...args: unknown[]) => bookWordsCall(...args),
  languageQaWordsAdd: (...args: unknown[]) => wordsAddCall(...args),
  languageQaWordsList: vi.fn().mockResolvedValue({ added: [] }),
  verseHistory: (...args: unknown[]) => verseHistoryCall(...args),
  languageQaVerse: (...args: unknown[]) => verseCall(...args),
  decideVerse: (...args: unknown[]) => decideCall(...args),
} }));
import LanguageQaPanel from "../LanguageQaPanel.svelte";
import { languageQaChannel } from "../../languageQaInline";
import { tick } from "svelte";

function snapshot(overrides: Partial<LanguageQaStatus> = {}): LanguageQaStatus {
  return {
    projectPath: "C:/project", book: "php", generation: 1, state: "completed",
    ruleVersion: "language-qa-1", totalFindings: 1, offset: 0,
    completedChapters: 1, totalChapters: 1, limitations: [],
    coverage: {
      inScope: [{ category: "sandhi", label: "Sandhi", labelTa: "சந்திப் பிழைகள்" }],
      outOfScope: [{ category: "agreement", label: "Agreement", labelTa: "திணை, பால், எண் இயைபு",
        reason: "Checked in the Round 2 review.", reasonTa: "இரண்டாம் சுற்றில்." }],
      handOff: "docs/LANGUAGE_QA_REVIEW_HANDOFF.md",
      summary: "Technical checks; no grammar certification.",
    },
    storage: "Session results.",
    language: { declared: "tam", language: "tam", script: "TAMIL", basis: "metadata",
      pack: "ta-irv", message: "Tamil character rules available." },
    findings: [lqaFinding({ id: "f1", chapter: "2", verse: "3-4", rule: "unicode.corruption",
      severity: "high", start: 0, end: 1, originalText: "�", message: "Check source encoding.",
      suggestedReplacement: null })],
    ...overrides,
  };
}

/** What languageQaInline.ts's status channel publishes: count-only status. */
function publish(overrides: Partial<LanguageQaStatus> = {}, error = ""): void {
  languageQaChannel.set({ projectPath: "C:/project", status: snapshot({ findings: [], ...overrides }), error });
}

/** The tab, on the book's list (the Review panel starts it on the verse). */
async function openBook(onNavigate = vi.fn()) {
  render(LanguageQaPanel, { projectPath: "C:/project", onNavigate });
  await fireEvent.click(await screen.findByRole("radio", { name: "Book" }));
  return onNavigate;
}

async function openBookList(onNavigate = vi.fn()) {
  const navigate = await openBook(onNavigate);
  await screen.findByText("Check source encoding.");
  return navigate;
}

const kindsButton = () => screen.getByRole("button", { name: /^Kinds · / });

it("narrows the list to the kinds still ticked and exposes the reference evidence", async () => {
  const finding = lqaFinding({ category: "quotation", rule: "quotation.reference-missing",
    message: "Possible missing quotation marks", referenceEvidence: { label: "English local", path: "local/ref",
      range: "MAT 5:3–7:27", openingText: "“Blessed", closingText: "It fell.”" } });
  statusCall.mockResolvedValue(snapshot({ findings: [finding], categoryCounts: { quotation: 1, typo: 2 } }));
  await openBook();
  await fireEvent.click(await screen.findByRole("button", { name: "Kinds · 2 ▾" }));
  await fireEvent.click(await screen.findByRole("button", { name: /Possible typo/ }));
  await waitFor(() => expect(statusCall).toHaveBeenLastCalledWith("C:/project", 0, 50, "findings", { categories: ["quotation"] }));
  expect(await screen.findByText("Reference evidence · English local")).toBeTruthy();
  expect(screen.getByText("MAT 5:3–7:27")).toBeTruthy();
});

beforeEach(() => {
  // statusCall serves only the tab's own page requests (limit 50).
  statusCall.mockReset().mockImplementation(async (_path, _offset, limit) =>
    snapshot({ findings: limit ? snapshot().findings : [] }));
  verseCall.mockReset().mockResolvedValue({ projectPath: "C:/project", generation: 1, state: "completed",
    chapter: "1", verse: "1", findings: [], hidden: [] });
  decideCall.mockReset().mockResolvedValue({});
  chapterCountCall.mockReset().mockResolvedValue(4);
  publish();
});

afterEach(() => {
  languageQaChannel.set({ projectPath: "", status: null, error: "" });
  selectedVerse.set(null);
});

describe("counts on the scope switch", () => {
  const badge = (scope: string) => document.querySelector(`[data-scope-count="${scope}"]`)?.textContent ?? null;

  it("shows the verse's, the chapter's and the book's finding counts, and keeps each button's name", async () => {
    currentChapter.set("2");
    selectedVerse.set("3");
    verseCall.mockResolvedValue({ projectPath: "C:/project", generation: 1, state: "completed", chapter: "2", verse: "3",
      findings: [lqaFinding({ id: "a", chapter: "2", verse: "3" }), lqaFinding({ id: "b", chapter: "2", verse: "3" })], hidden: [] });
    publish({ totalFindings: 31 });
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    await waitFor(() => expect(badge("verse")).toBe("2"));
    await waitFor(() => expect(badge("chapter")).toBe("4"));
    expect(badge("book")).toBe("31");
    expect(chapterCountCall).toHaveBeenCalledWith("C:/project", "2", "findings");
    expect(screen.getByRole("radio", { name: "Chapter" })).toHaveAttribute("title", "4 in this chapter");
    // The count read is not a page read: the verse scope still reads no page.
    expect(statusCall).not.toHaveBeenCalled();
  });

  it("has no verse count without a selected verse, and reads the chapter's count again when a new pass lands", async () => {
    currentChapter.set("2");
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    await waitFor(() => expect(badge("chapter")).toBe("4"));
    expect(badge("verse")).toBeNull();
    chapterCountCall.mockResolvedValue(1);
    publish({ generation: 2 });
    await waitFor(() => expect(badge("chapter")).toBe("1"));
    expect(chapterCountCall).toHaveBeenCalledTimes(2);
  });
});

describe("Language QA tab (#487)", () => {
  it("starts on the verse and reads no page until a chapter or book scope is chosen", async () => {
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    expect(await screen.findByText("Select a verse to list its findings.")).toBeTruthy();
    expect(screen.getByRole("radio", { name: "Verse" }).getAttribute("aria-checked")).toBe("true");
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(statusCall).not.toHaveBeenCalled();
    expect(screen.queryByText("Check source encoding.")).toBeNull();
  });

  it("has no bar of its own: no Pause, Undock, Close or ◂ ▸; the state line, the (i) and the tabs are pinned together", async () => {
    await openBookList();
    expect(screen.queryByRole("heading", { level: 2 })).toBeNull();
    for (const name of ["Pause checks", "Close Language QA", "Language QA panel tools", "Previous", "Next"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    const head = document.querySelector(".panel-head") as HTMLElement;
    expect(head).not.toBeNull();
    expect(head.firstElementChild?.classList.contains("state-row")).toBe(true);
    expect(head.firstElementChild?.textContent?.replace(/\s+/g, " ")).toContain("Checks completed · 1 candidates");
    expect(head.contains(screen.getByRole("button", { name: "About these checks" }))).toBe(true);
    expect(head.contains(screen.getByRole("tablist", { name: "Language QA panel" }))).toBe(true);
    // The (i) is a popover inside the pinned rows; the full status line lives there.
    expect(head.querySelector(".status-line")).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "About these checks" }));
    const about = screen.getByRole("dialog", { name: "What Language QA checks" });
    expect(head.contains(about)).toBe(true);
    expect(about.querySelector(".status-line")?.textContent?.replace(/\s+/g, " ")).toMatch(/completed · 1\/1 chapters · 1 review candidates/);
    expect(about.textContent).toContain("F8 / Shift+F8");
    expect(about.textContent).toContain("Re-check:");
    await fireEvent.click(screen.getByRole("button", { name: "Close this note" }));
    expect(screen.queryByRole("dialog", { name: "What Language QA checks" })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "About these checks" }));
    // jsdom lays nothing out: the pin is the rule as written.
    const css = readFileSync(resolve(process.cwd(), "src/lib/components/LanguageQaPanel.svelte"), "utf-8");
    expect(css).toMatch(/\.panel-head \{[^}]*position: sticky; top: 0/);
  });

  // #487: it is a tab only. It draws no panel bar and has no window of its own.
  it("never draws a panel bar of its own, and PanelWindow no longer hosts it", async () => {
    publish({ state: "running", completedChapters: 12, totalChapters: 50 });
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    expect(await screen.findByText(/Checks running 12\/50/)).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 2 })).toBeNull();
    expect(screen.queryByRole("button", { name: "Close Language QA" })).toBeNull();
    const host = readFileSync(resolve(process.cwd(), "src/lib/components/PanelWindow.svelte"), "utf-8");
    expect(host).not.toContain("LanguageQa");
  });

  it("refetches the open page when a new pass lands on the channel, and not otherwise", async () => {
    await openBookList();
    expect(statusCall).toHaveBeenCalledTimes(1);
    publish();  // same generation and state: nothing new to show
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(statusCall).toHaveBeenCalledTimes(1);
    publish({ generation: 2 });
    await waitFor(() => expect(statusCall).toHaveBeenCalledTimes(2));
  });

  it("reads the page only while the tab is on screen", async () => {
    const { component } = render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn(), active: false });
    await fireEvent.click(await screen.findByRole("radio", { name: "Book" }));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(statusCall).not.toHaveBeenCalled();
    component.$set({ active: true });
    await screen.findByText("Check source encoding.");
    expect(statusCall).toHaveBeenCalledTimes(1);
  });

  it("loads findings on demand and navigates exact verse bridges", async () => {
    const navigate = await openBookList();
    await fireEvent.click(screen.getByRole("button", { name: "PHP 2:3-4" }));
    expect(navigate).toHaveBeenCalledWith("php", "2", "3-4");
    expect(statusCall).toHaveBeenLastCalledWith("C:/project", 0, 50, "findings");
  });

  it("says when a finding is in a heading or a footnote, and shows the OV verse", async () => {
    const reference = { label: "OV 1957", ref: "MAT 18:15", text: "உன் சகோதரன் உனக்கு விரோதமாய்க் குற்றஞ்செய்தால்" };
    const findings = [
      lqaFinding({ id: "h1", chapter: "18", verse: "15", originalText: "விரோதமாக", message: "Heading lead.",
        context: "heading", contextText: "உனக்கு விரோதமாக குற்றம் செய்யும் சகோதரன்", suggestions: [],
        suggestedReplacement: null, reference }),
      lqaFinding({ id: "n1", chapter: "4", verse: "8", originalText: "கூட்டிசென்றான்", message: "Footnote lead.",
        context: "footnote" }),
    ];
    publish({ totalFindings: 2, findings });
    statusCall.mockResolvedValue(snapshot({ totalFindings: 2, findings }));
    await openBook();
    await screen.findByText("Heading lead.");
    expect(screen.getByText("in heading")).toBeTruthy();
    expect(screen.getByText("in footnote")).toBeTruthy();
    expect(screen.getByText(/Heading: உனக்கு விரோதமாக/)).toBeTruthy();
    expect(screen.getByText(/OV 1957 MAT 18:15:/)).toBeTruthy();
    expect(screen.getByText(reference.text)).toBeTruthy();
    // A heading finding offers no "Apply to" row: its text is not in the verse.
    expect(screen.queryByRole("radiogroup", { name: "Apply a suggestion to" })).toBeNull();
  });

  it("says when a finding is in the book's introduction (#253)", async () => {
    const findings = [
      lqaFinding({ id: "i1", chapter: "1", verse: "1", originalText: "மத் 8 ", message: "Space inside \\ior.",
        context: "introduction", contextText: "மத் 8 ராஜாவின் அதிகாரமும் ஊழியமும்", suggestions: [],
        suggestedReplacement: null }),
    ];
    publish({ totalFindings: 1, findings });
    statusCall.mockResolvedValue(snapshot({ totalFindings: 1, findings }));
    await openBook();
    await screen.findByText("Space inside \\ior.");
    expect(screen.getByText("in introduction")).toBeTruthy();
    expect(screen.getByText(/Book introduction: மத் 8 ராஜாவின்/)).toBeTruthy();
  });

  it("shows incomplete coverage instead of claiming a clean publication", async () => {
    const incomplete = { totalFindings: 0, findings: [], incomplete: true,
      limitations: ["Chapter 1: 4: Unbalanced \\f: 1 open, 0 close; verse not checked."] };
    publish(incomplete);
    statusCall.mockResolvedValue(snapshot(incomplete));
    await openBook();
    expect(screen.queryByText(/Coverage incomplete/)).toBeNull();
    // #376: the disclaimer and the details list are behind the (i).
    expect(screen.queryByText(/not publication approval/)).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "About these checks" }));
    expect(screen.getByText(/Coverage incomplete/)).toBeTruthy();
    const about = screen.getByRole("dialog", { name: "What Language QA checks" });
    expect(about.textContent).toContain("not publication approval");
    expect(about.textContent).toContain("Unbalanced \\f");
  });

  it("names a profile pack's language and pack, with no empty Tamil label", async () => {
    const hindi = {
      totalFindings: 0, findings: [],
      language: { declared: "hin", language: "hi", name: "Hindi", script: "DEVANAGARI", basis: "metadata",
        pack: "hi-irv", message: "Hindi spelling, encoding, punctuation and consistency checks." },
      coverage: {
        inScope: [{ category: "consistency", label: "Spelling consistency", labelTa: "" }],
        outOfScope: [{ category: "clause-agreement", label: "Agreement across a whole clause", labelTa: "",
          reason: "Only corpus-attested pairs are flagged.", reasonTa: "" }],
        handOff: "docs/LANGUAGE_QA_REVIEW_HANDOFF.md", summary: "Technical checks.",
      },
    };
    publish(hindi);
    statusCall.mockResolvedValue(snapshot(hindi));
    await openBook();
    await fireEvent.click(screen.getByRole("button", { name: "About these checks" }));
    const heading = screen.getByText(/hi-irv rules/, { selector: "p" });
    expect(heading.textContent).toMatch(/^\s*Hindi/);
    const scope = screen.getByLabelText("What Language QA checks");
    expect(scope.textContent).toContain("Spelling consistency");
    expect(scope.querySelector('span[lang="ta"]')).toBeNull();
    expect(scope.textContent).not.toContain("Tamil");
  });

  it("states what it checks and what it does not, in Tamil and English, behind the (i)", async () => {
    publish({ totalFindings: 0, findings: [] });
    statusCall.mockResolvedValue(snapshot({ totalFindings: 0, findings: [] }));
    await openBook();
    // Behind the (i) since DECISIONS 2026-10-09 (Benz), superseding 2026-09-24.
    expect(screen.queryByLabelText("What Language QA checks")).toBeNull();
    const info = screen.getByRole("button", { name: "About these checks" });
    expect(info.getAttribute("aria-expanded")).toBe("false");
    await fireEvent.click(info);
    expect(info.getAttribute("aria-expanded")).toBe("true");
    const scope = screen.getByLabelText("What Language QA checks");
    expect(scope.textContent).toContain("Language supplied by the project.");
    expect(scope.textContent).toContain("Tamil character rules available.");
    expect(scope.textContent).toContain("Session results.");
    expect(scope.textContent).toContain("Sandhi");
    expect(scope.textContent).toContain("சந்திப் பிழைகள்");
    expect(scope.textContent).toContain("Does not check");
    expect(scope.textContent).toContain("திணை, பால், எண் இயைபு");
    expect(scope.textContent).toContain("Checked in the Round 2 review.");
    expect(scope.textContent).toContain("docs/LANGUAGE_QA_REVIEW_HANDOFF.md");
    // Escape closes it and gives focus back to the (i); so does a click elsewhere.
    await fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByLabelText("What Language QA checks")).toBeNull();
    expect(document.activeElement).toBe(info);
    await fireEvent.click(info);
    await fireEvent.pointerDown(document.body);
    expect(screen.queryByLabelText("What Language QA checks")).toBeNull();
  });

  it("pins the Findings / Re-check / False positives switch under the tab bar, outside the scrolling list (#178)", async () => {
    await openBookList();
    const tabs = screen.getByRole("tablist", { name: "Language QA panel" });
    const row = tabs.nextElementSibling as HTMLElement;
    expect(row.classList.contains("list-row")).toBe(true);
    const lists = screen.getByRole("tablist", { name: "Language QA lists" });
    expect(row.contains(lists)).toBe(true);
    expect(lists.closest(".panel-body")).toBeNull();
    expect([...lists.querySelectorAll('[role="tab"]')].map((t) => t.textContent?.trim().replace(/\s+/g, " ")))
      .toEqual(["Findings (1)", "Re-check (0)", "False positives (0)"]);
    await fireEvent.click(screen.getByRole("tab", { name: /Re-check/ }));
    expect(screen.getByRole("tab", { name: /Re-check/ }).getAttribute("aria-selected")).toBe("true");
    // Only the Issues tab has lists to switch.
    await fireEvent.click(screen.getByRole("tab", { name: /^Words in / }));
    expect(screen.queryByRole("tablist", { name: "Language QA lists" })).toBeNull();
  });

  it("names the Book words tab for the open book, falls back to the code, and cuts a long name with an ellipsis (#385)", async () => {
    project.set({ path: "C:/project", bookId: "gen", bookName: "ஆதியாகமம்", chapters: ["1"] } as never);
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    const tab = await screen.findByRole("tab", { name: "Words in ஆதியாகமம்" });
    expect(tab.getAttribute("title")).toBe("Words in ஆதியாகமம்");
    expect(tab.classList.contains("book-tab")).toBe(true);
    await fireEvent.click(tab);
    expect(screen.getByText(/^Words in ஆதியாகமம் that are not in the dictionary/)).toBeTruthy();

    // Switching books renames the tab without reopening the panel.
    project.set({ path: "C:/project", bookId: "mat", bookName: "மத்தேயு", chapters: ["1"] } as never);
    expect(await screen.findByRole("tab", { name: "Words in மத்தேயு" })).toBeTruthy();

    // No name: the code, upper-cased, as the dashboard does.
    project.set({ path: "C:/project", bookId: "mat", chapters: ["1"] } as never);
    expect(await screen.findByRole("tab", { name: "Words in MAT" })).toBeTruthy();

    // jsdom lays nothing out: the ellipsis is pinned as the rule on the tab.
    const css = readFileSync(resolve(process.cwd(), "src/lib/components/LanguageQaPanel.svelte"), "utf-8");
    expect(css).toMatch(/\.panel-tabs \.book-tab \{[^}]*text-overflow: ellipsis/);
    expect(css).toMatch(/\.panel-tabs \.book-tab \{[^}]*min-width: 0/);
    project.set(null);
  });

  it("keeps the list switch, the scope and Kinds in one filter row; every kind is ticked until one is unticked; All ticks them again (#487)", async () => {
    statusCall.mockImplementation(async (_path, _offset, limit) => snapshot({
      findings: limit ? snapshot().findings : [], categoryCounts: { typo: 2, sandhi: 1 } }));
    await openBookList();
    const row = screen.getByRole("tablist", { name: "Language QA panel" }).nextElementSibling as HTMLElement;
    expect(row.classList.contains("filter-bar")).toBe(true);
    expect(row.contains(screen.getByRole("tablist", { name: "Language QA lists" }))).toBe(true);
    expect(row.contains(screen.getByRole("radiogroup", { name: "Show findings for" }))).toBe(true);
    // Kinds is a dropdown: closed, the checklist is not in the page.
    const kinds = screen.getByRole("button", { name: "Kinds · 2 ▾" });
    expect(row.contains(kinds)).toBe(true);
    expect(screen.queryByRole("group", { name: "Kinds of finding" })).toBeNull();
    await fireEvent.click(kinds);
    expect(kinds.getAttribute("aria-expanded")).toBe("true");
    expect(screen.queryByRole("button", { name: "All" })).toBeNull();
    const legend = screen.getByRole("group", { name: "Kinds of finding" });
    expect(legend).toHaveTextContent(/Possible typo\s*2/);
    const typo = screen.getByRole("button", { name: /Possible typo/ });
    expect(typo.getAttribute("aria-pressed")).toBe("true");
    expect(typo.querySelector("mark")?.className).toContain("m-lqa-typo");
    // Unticking one leaves it out; the engine is asked for the rest.
    await fireEvent.click(typo);
    expect(typo.getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByRole("button", { name: "Kinds · 1 of 2 ▾" })).toBeTruthy();
    await waitFor(() => expect(statusCall).toHaveBeenLastCalledWith("C:/project", 0, 50, "findings", { categories: ["sandhi"] }));
    await fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(typo.getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryByRole("button", { name: "All" })).toBeNull();
    await waitFor(() => expect(statusCall).toHaveBeenLastCalledWith("C:/project", 0, 50, "findings"));
    // Escape closes the dropdown and gives focus back to its button.
    await fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("group", { name: "Kinds of finding" })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Kinds · 2 ▾" }));
  });

  it("with every kind unticked the list is empty and nothing is asked of the engine", async () => {
    statusCall.mockImplementation(async (_path, _offset, limit) => snapshot({
      findings: limit ? snapshot().findings : [], categoryCounts: { unicode: 1 } }));
    await openBookList();
    await fireEvent.click(kindsButton());
    await fireEvent.click(screen.getByRole("button", { name: /Encoding|unicode/i }));
    const calls = statusCall.mock.calls.length;
    await waitFor(() => expect(screen.queryByText("Check source encoding.")).toBeNull());
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(statusCall.mock.calls.length).toBe(calls);
  });

  it("does not display a response belonging to a different project", async () => {
    statusCall.mockResolvedValue(snapshot({ projectPath: "C:/old-project" }));
    await openBook();
    await waitFor(() => expect(statusCall).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByText("Check source encoding.")).toBeNull();
    // Nor a channel status published for another project.
    languageQaChannel.set({ projectPath: "C:/old-project", status: snapshot(), error: "" });
    expect(await screen.findByText(/Checks starting/)).toBeTruthy();
  });

  it("never writes the inline-marks store, whatever page it shows", async () => {
    // The panel used to fill languageQaFindingsByVerse from its own page, so
    // any inline finding past the first 100 in the book never got a mark.
    // The store now belongs to languageQaInline.ts; paging here must not touch it.
    const seeded: Record<string, LanguageQaFinding[]> = { "1:1": [lqaFinding({ id: "keep", chapter: "1",
      verse: "1", rule: "terminology.deprecated-form", start: 0, end: 3,
      originalText: "bad", message: "Deprecated.", suggestedReplacement: "good" })] };
    languageQaFindingsByVerse.set(seeded);
    statusCall.mockImplementation(async (_path, _offset, limit) => snapshot({
      totalFindings: 120,
      findings: limit ? [lqaFinding({ id: "f2", chapter: "3", verse: "9", rule: "terminology.deprecated-form",
        start: 0, end: 3, originalText: "bad", message: "Deprecated.", suggestedReplacement: "good" })] : [],
    }));
    await openBook();
    await screen.findByText("Deprecated.");
    expect(get(languageQaFindingsByVerse)).toEqual(seeded);
    languageQaFindingsByVerse.set({});
  });

  it("lists re-check and false-positive findings separately, each paged by the engine; a false positive offers no decision", async () => {
    statusCall.mockImplementation(async (_path, _offset, limit, view) => snapshot({
      view, recheckCount: 1, falsePositiveCount: 2, totalFindings: view === "findings" ? 1 : view === "recheck" ? 1 : 2,
      findings: !limit ? [] : view === "recheck"
        ? [lqaFinding({ id: "r1", message: "Ignored before.", previouslyIgnored: true })]
        : view === "falsePositives"
          ? [lqaFinding({ id: "fp1", message: "Not a problem." }), lqaFinding({ id: "fp2", message: "Also fine." })]
          : snapshot().findings,
    }));
    await openBook();
    await fireEvent.click(await screen.findByRole("tab", { name: "Re-check (1)" }));
    await screen.findByText("Ignored before.");
    expect(statusCall).toHaveBeenLastCalledWith("C:/project", 0, 50, "recheck");
    expect(screen.getByText("Re-check", { selector: ".recheck" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "⊘ Ignore" })).toBeTruthy();
    await fireEvent.click(screen.getByRole("tab", { name: "False positives (2)" }));
    await screen.findByText("Also fine.");
    expect(statusCall).toHaveBeenLastCalledWith("C:/project", 0, 50, "falsePositives");
    expect(screen.queryByText("Ignored before.")).toBeNull();
    expect(screen.queryByRole("button", { name: "⊘ Ignore" })).toBeNull();
    expect(screen.queryByRole("button", { name: "False positive" })).toBeNull();
    expect(screen.getAllByRole("button", { name: "Copy" })).toHaveLength(2);
  });

  it("loads a finding's decision history only when asked, behind a placeholder", async () => {
    let answer: (value: unknown) => void = () => {};
    historyCall.mockReset().mockReturnValue(new Promise((resolve) => { answer = resolve; }));
    await openBookList();
    expect(historyCall).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole("button", { name: "History" }));
    expect(screen.getByText("Loading history…")).toBeTruthy();
    expect(historyCall).toHaveBeenCalledWith("C:/project", "2", "3-4", "f1");
    answer({ chapter: "2", verse: "3-4", findingId: "f1", entries: [
      { seq: 4, findingId: "f1", decision: "ignored", note: "", rule: "unicode.corruption", ruleId: "common/unicode.corruption",
        originalText: "�", chosenSuggestion: null, chosenRank: null, packVersion: "language-qa-7",
        recordedAt: "2026-09-24T10:00:00Z", revision: 1, actorId: "a" },
      { seq: 9, findingId: "f1", decision: "rejected", note: "", rule: "unicode.corruption", ruleId: "common/unicode.corruption",
        originalText: "�", chosenSuggestion: null, chosenRank: null, packVersion: "language-qa-7",
        recordedAt: "2026-09-24T11:00:00Z", revision: 2, actorId: "a" },
    ] });
    await screen.findByText("Marked as false positive");
    const items = screen.getByRole("list", { name: "Language QA decision history" }).querySelectorAll("li");
    expect(Array.from(items).map((li) => li.querySelector(".decision")?.textContent))
      .toEqual(["Ignored", "Marked as false positive"]);
  });

  it("surfaces the channel's failure", async () => {
    publish({}, "Engine unavailable");
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    expect(screen.getByRole("alert").textContent).toContain("Engine unavailable");
  });

  it("lists learned fixes only when the Dictionary tab opens, and forgets and restores one", async () => {
    const fix = { old: "தேவன்", new: "கர்த்தர்", count: 3, firstRef: "RUT 1:1", lastRef: "RUT 2:4", reviewer: "Benz",
      source: "edit" as const, enabled: true, createdAt: "t", updatedAt: "t", own: 1, books: ["gen", "rut"] };
    learnedListCall.mockReset().mockResolvedValue({ fixes: [fix], enabled: true });
    learnedForgetCall.mockReset().mockResolvedValue({ fix: { ...fix, enabled: false } });
    learnedRestoreCall.mockReset().mockResolvedValue({ fix });
    await openBookList();
    expect(learnedListCall).not.toHaveBeenCalled();

    await fireEvent.click(screen.getByRole("tab", { name: "Dictionary" }));
    expect(await screen.findByText("கர்த்தர்")).toBeTruthy();
    expect(learnedListCall).toHaveBeenCalledWith("C:/project");
    expect(screen.getByText("RUT 2:4")).toBeTruthy();
    expect(screen.getByText("GEN, RUT")).toBeTruthy();  // shared across the collection's books

    await fireEvent.click(screen.getByRole("button", { name: "Forget" }));
    await waitFor(() => expect(learnedForgetCall).toHaveBeenCalledWith("C:/project", "தேவன்", "கர்த்தர்"));
    await fireEvent.click(await screen.findByRole("button", { name: "Restore" }));
    await waitFor(() => expect(learnedRestoreCall).toHaveBeenCalledWith("C:/project", "தேவன்", "கர்த்தர்"));
    expect(await screen.findByRole("button", { name: "Forget" })).toBeTruthy();
  });

  it("lists the book's open flags in the Flags tab, navigates to one and resolves it", async () => {
    const flag = { flagId: "f1", chapter: "3", verse: "4", verseEnd: null, start: 0, end: 4, text: "அவன்", textHash: "h",
      type: "meaning" as const, note: "Is this the sense?", suggested: null, findingId: null, reviewer: "Benz",
      status: "open" as const, createdAt: "2026-10-07T10:00:00Z", updatedAt: "2026-10-07T10:00:00Z" };
    flagsListCall.mockReset().mockResolvedValue({ flags: [flag] });
    flagUpdateCall.mockReset().mockResolvedValue({ flag: { ...flag, status: "resolved" } });
    const onNavigate = vi.fn();
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate });
    await fireEvent.click(await screen.findByRole("tab", { name: "Flags" }));
    expect(await screen.findByText("Is this the sense?")).toBeTruthy();
    expect(flagsListCall).toHaveBeenCalledWith("C:/project");
    await fireEvent.click(screen.getByRole("button", { name: "PHP 3:4" }));
    expect(onNavigate).toHaveBeenCalledWith("php", "3", "4");
    await fireEvent.click(screen.getByRole("button", { name: "Resolve" }));
    await waitFor(() => expect(flagUpdateCall).toHaveBeenCalledWith("C:/project", "f1", { status: "resolved" }));
    await waitFor(() => expect(screen.queryByText("Is this the sense?")).toBeNull());
  });

  it("previews an AI review file and imports matching questions only after confirmation", async () => {
    flagsListCall.mockReset().mockResolvedValue({ flags: [] });
    pickReviewCall.mockReset().mockResolvedValue("D:/review.json");
    const preview = { packetId: "pilot-1", provenance: "ai-assisted-native-pending", sha256: "filehash",
      book: "php", language: "ta", ready: 2, existing: 1, stale: 3, otherScope: 9,
      examples: [{ id: "c1", chapter: "1", verse: "2", text: "தேவன்", note: "AI proposal" }] };
    reviewPreviewCall.mockReset().mockResolvedValue(preview);
    reviewImportCall.mockReset().mockResolvedValue({ ...preview, imported: 2 });
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    await fireEvent.click(await screen.findByRole("tab", { name: "Flags" }));
    await fireEvent.click(screen.getByRole("button", { name: "Import AI review…" }));
    expect(await screen.findByText("AI-assisted review — native confirmation pending.")).toBeTruthy();
    expect(reviewPreviewCall).toHaveBeenCalledWith("C:/project", "D:/review.json");
    expect(reviewImportCall).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole("button", { name: "Import 2 questions" }));
    await waitFor(() => expect(reviewImportCall).toHaveBeenCalledWith("C:/project", "D:/review.json", "filehash"));
    expect(await screen.findByText(/Imported 2 open questions/)).toBeTruthy();
  });

  it("records a human conclusion on an AI question and can keep uncertainty open", async () => {
    const flag = { flagId: "ai-1", chapter: "1", verse: "2", verseEnd: null, start: 0, end: 5,
      text: "தேவன்", textHash: "h", type: "spelling" as const,
      note: "AI-assisted review — native confirmation pending.", suggested: null, findingId: null,
      reviewer: "AI-assisted review", status: "open" as const, createdAt: "2026-10-30", updatedAt: "2026-10-30",
      aiReview: { packetId: "p1", caseId: "c1", sourceArchiveSha256: "a".repeat(64), provenance: "ai-assisted-native-pending" as const } };
    flagsListCall.mockReset().mockResolvedValue({ flags: [flag] });
    flagUpdateCall.mockReset().mockImplementation(async (_path, _id, patch) => {
      const saved = { ...flag, ...patch };
      flagsListCall.mockResolvedValue({ flags: [saved] });
      return { flag: saved };
    });
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    await fireEvent.click(await screen.findByRole("tab", { name: "Flags" }));
    await fireEvent.click(await screen.findByRole("button", { name: "Record check…" }));
    expect((screen.getByRole("button", { name: "Save and resolve" }) as HTMLButtonElement).disabled).toBe(true);
    await fireEvent.input(screen.getByRole("textbox", { name: "Human check" }), { target: { value: "Still uncertain; ask the native reviewer." } });
    await fireEvent.click(screen.getByRole("button", { name: "Save and keep open" }));
    await waitFor(() => expect(flagUpdateCall).toHaveBeenCalledWith("C:/project", "ai-1", {
      status: "open", note: expect.stringContaining("Still uncertain; ask the native reviewer.") }));
    expect(flagUpdateCall.mock.calls[0][2].note).toContain(flag.note);
    expect(flagUpdateCall.mock.calls[0][2].note).toContain("Human check (");
  });

  it("lists the book's edits by day in the Edits tab, with what changed, and navigates to one", async () => {
    const edit = (verse: string, timestamp: string, batchId: string | null = null) => ({
      chapter: "2", verse, timestamp, username: "Benz", verseBefore: "a", verseAfter: "b",
      plainBefore: "पुराना", plainAfter: "नया", tags: [], groupId: "", batchId, undoes: null });
    verseHistoryCall.mockReset().mockResolvedValue({ total: 2, truncated: false, entries: [
      edit("5", "2026-10-07T10:00:00.000Z", "b1"), edit("4", "2026-10-01T10:00:00.000Z")] });
    const onNavigate = vi.fn();
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate });
    await fireEvent.click(await screen.findByRole("tab", { name: "Edits" }));
    const section = await screen.findByRole("region", { name: "Edits" });
    await waitFor(() => expect(section.querySelectorAll("h3")).toHaveLength(2));
    expect(verseHistoryCall).toHaveBeenCalledWith();
    expect(section).toHaveTextContent("change set");
    expect(section.querySelector("ins")?.textContent).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: "PHP 2:4" }));
    expect(onNavigate).toHaveBeenCalledWith("php", "2", "4");
  });

  it("Book words ticks the words the IRV uses often and adds them to the dictionary", async () => {
    const row = (word: string, countIrv: number) => ({ word, status: "irv_ok" as const, countBook: 2, countIrv, countOv: 0,
      firstRef: { chapter: "1", verse: "1" } });
    bookWordsCall.mockReset().mockResolvedValue({ ready: true, total: 2, words: [row("राज्यपाल", 25), row("सोची", 2)] });
    wordsAddCall.mockReset().mockResolvedValue({ entries: [], count: 1 });
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    await fireEvent.click(await screen.findByRole("tab", { name: /^Words in / }));
    expect(await screen.findByText("राज्यपाल")).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: "Tick" }));
    expect((screen.getByRole("checkbox", { name: "Tick राज्यपाल" }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("checkbox", { name: "Tick सोची" }) as HTMLInputElement).checked).toBe(false);
    await fireEvent.click(screen.getByRole("button", { name: "Add to dictionary (this book)" }));
    await waitFor(() => expect(wordsAddCall).toHaveBeenCalledWith("C:/project", ["राज्यपाल"], "book"));
    expect(await screen.findByText(/1 word added to the dictionary\./)).toBeTruthy();
    expect(screen.getByText("in dictionary")).toBeTruthy();
  });

  it("a dictionary without corpus counts shows unavailable counts and keeps manual word selection", async () => {
    bookWordsCall.mockReset().mockResolvedValue({ ready: true, total: 1, words: [{ word: "माणूसमाणूस",
      status: "unknown", countBook: 2, countIrv: null, countOv: null, firstRef: { chapter: "1", verse: "1" } }] });
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    await fireEvent.click(await screen.findByRole("tab", { name: /^Words in / }));
    expect(await screen.findByText("माणूसमाणूस")).toBeTruthy();
    expect(screen.getAllByRole("cell", { name: "—" })).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Tick" })).toBeNull();
    const checkbox = screen.getByRole("checkbox", { name: "Tick माणूसमाणूस" });
    await fireEvent.click(checkbox);
    expect((checkbox as HTMLInputElement).checked).toBe(true);
  });
});

describe("Language QA tab: the card's actions on a listed finding (#487)", () => {
  afterEach(() => {
    project.set(null);
    currentChapter.set("1");
  });

  it("every listed finding, whatever the scope, carries Use, Ignore, False positive, Flag, Copy, Search and History; Ignore drops it at once and records the decision", async () => {
    project.set({ path: "C:/project", bookId: "php", chapters: ["1", "2"] } as never);
    const finding = lqaFinding({ id: "b1", chapter: "2", verse: "7", originalText: "அந்த காகம்", message: "Possible missing வல்லினம்." });
    statusCall.mockImplementation(async (_path, _offset, limit) => snapshot({ findings: limit ? [finding] : [] }));
    await openBook();
    const card = (await screen.findByText("Possible missing வல்லினம்.")).closest("[data-lqa-id]") as HTMLElement;
    expect(card.getAttribute("data-lqa-id")).toBe("b1");
    for (const name of [/^Use “அந்தக் காகம்”/, "⊘ Ignore", "False positive", "⚑ Flag…", "Copy", "Search", "History"]) {
      expect(within(card).getByRole("button", { name })).toBeTruthy();
    }
    expect(within(card).getByRole("button", { name: "PHP 2:7" })).toBeTruthy();
    expect(within(card).getByText("medium")).toBeTruthy();
    expect(within(card).getByText("ta-irv/tamil.vallinam-missing")).toBeTruthy();
    expect(within(card).getByRole("radiogroup", { name: "Apply a suggestion to" })).toBeTruthy();
    let release: (value: unknown) => void = () => {};
    decideCall.mockReturnValue(new Promise((resolve) => { release = resolve; }));
    await fireEvent.click(within(card).getByRole("button", { name: "⊘ Ignore" }));
    expect(document.querySelector('[data-lqa-id="b1"]')).toBeNull();
    expect(screen.getByText("Occurrence ignored.")).toBeTruthy();
    expect(decideCall).toHaveBeenCalledWith("2", "7", "b1", "ignored", undefined, expect.objectContaining({ source: "languageQa" }));
    release({});
  });

  it("a failed decision puts the finding back and says why", async () => {
    project.set({ path: "C:/project", bookId: "php", chapters: ["1", "2"] } as never);
    decideCall.mockRejectedValue(new Error("disk full"));
    await openBookList();
    await fireEvent.click(screen.getByRole("button", { name: "False positive" }));
    expect(await screen.findByText("disk full")).toBeTruthy();
    expect(document.querySelector('[data-lqa-id="f1"]')).not.toBeNull();
  });
});

describe("Language QA tab: paging (#487)", () => {
  function paged(total: number) {
    statusCall.mockImplementation(async (_path, offset, limit) => snapshot({
      totalFindings: total, offset,
      findings: limit ? [lqaFinding({ id: `p${offset}`, chapter: "1", verse: "1", message: `Row ${offset + 1}.` })] : [],
    }));
  }

  it("turns pages with Previous / Next and a go-to-page box; the rows on show stay until the next page arrives", async () => {
    paged(120);
    await openBook();
    await screen.findByText("Row 1.");
    const pager = document.querySelector(".paging") as HTMLElement;
    expect(pager).not.toBeNull();
    expect(pager.textContent).toContain("Page 1 of 3");
    expect((within(pager).getByRole("button", { name: "Previous" }) as HTMLButtonElement).disabled).toBe(true);
    await fireEvent.click(within(pager).getByRole("button", { name: "Next" }));
    await waitFor(() => expect(statusCall).toHaveBeenLastCalledWith("C:/project", 50, 50, "findings"));
    await screen.findByText("Row 51.");
    expect(pager.textContent).toContain("Page 2 of 3");
    // Go to page 3: the box takes a number, Enter or Go sends it.
    await fireEvent.input(within(pager).getByRole("spinbutton", { name: "Go to page" }), { target: { value: "3" } });
    await fireEvent.submit(pager.querySelector("form") as HTMLFormElement);
    await waitFor(() => expect(statusCall).toHaveBeenLastCalledWith("C:/project", 100, 50, "findings"));
    await screen.findByText("Row 101.");
    expect((within(pager).getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
    // A late page: the old rows stay until the new ones arrive.
    let finish!: (value: LanguageQaStatus) => void;
    statusCall.mockImplementationOnce(() => new Promise<LanguageQaStatus>((resolve) => { finish = resolve; }));
    await fireEvent.click(within(pager).getByRole("button", { name: "Previous" }));
    await tick();
    expect(screen.getByText("Row 101.")).toBeTruthy();
    finish(snapshot({ totalFindings: 120, offset: 50, findings: [lqaFinding({ id: "p50", chapter: "1", verse: "1", message: "Row 51." })] }));
    await screen.findByText("Row 51.");
    expect(screen.queryByText("Row 101.")).toBeNull();
  });

  it("the pager is pinned to the bottom of the tab, and shows only for a paged list", async () => {
    const css = readFileSync(resolve(process.cwd(), "src/lib/components/LanguageQaPanel.svelte"), "utf-8");
    expect(css).toMatch(/\.paging \{[^}]*position: sticky; bottom: 0/);
    paged(20);
    await openBook();
    await screen.findByText("Row 1.");
    expect(document.querySelector(".paging")).toBeNull();
  });
});

describe("Language QA tab: kinds, scope and F8", () => {
  afterEach(() => {
    project.set(null);
    focusedFindingId.set(null);
    languageQaFindingsByVerse.set({});
    chapterVerseNums.set({});
    selectedVerse.set(null);
    currentChapter.set("1");
  });

  it("lists one chapter, or the selected verse's findings, as the scope says", async () => {
    currentChapter.set("2");
    selectedVerse.set("3-4");
    verseCall.mockResolvedValue({ projectPath: "C:/project", generation: 1, state: "completed", chapter: "2", verse: "3-4",
      findings: [lqaFinding({ id: "v1", chapter: "2", verse: "3-4", originalText: "அவண்", message: "Verse finding.", category: "typo" })],
      hidden: [] });
    await openBookList();
    await fireEvent.click(screen.getByRole("radio", { name: "Chapter" }));
    await waitFor(() => expect(statusCall).toHaveBeenLastCalledWith("C:/project", 0, 50, "findings", { chapter: "2" }));
    await fireEvent.click(screen.getByRole("radio", { name: "Verse" }));
    expect(await screen.findByText("Verse finding.")).toBeTruthy();
    expect(verseCall).toHaveBeenCalledWith("C:/project", "2", "3-4");
    await fireEvent.click(kindsButton());
    expect(screen.getByRole("group", { name: "Kinds of finding" })).toHaveTextContent(/Possible typo\s*1/);
  });

  it("reads the verse list again when the pass after an edit completes (#237)", async () => {
    currentChapter.set("2");
    selectedVerse.set("3-4");
    const verseResult = (message: string) => ({ projectPath: "C:/project", generation: 2, state: "completed",
      chapter: "2", verse: "3-4", hidden: [],
      findings: [lqaFinding({ id: message, chapter: "2", verse: "3-4", message, category: "typo" })] });
    await openBookList();
    // The edit: a new generation, queued. The engine still holds the last
    // pass's findings for the verse until this one finishes.
    verseCall.mockResolvedValue(verseResult("Before the edit."));
    publish({ generation: 2, state: "queued" });
    await fireEvent.click(screen.getByRole("radio", { name: "Verse" }));
    expect(await screen.findByText("Before the edit.")).toBeTruthy();
    // Same generation, now completed: the list must be read again.
    verseCall.mockResolvedValue(verseResult("The new misspelling."));
    publish({ generation: 2, state: "completed" });
    expect(await screen.findByText("The new misspelling.")).toBeTruthy();
  });

  it("F8 and Shift+F8 walk the marks in reading order, and typing in a box is left alone", async () => {
    project.set({ path: "C:/project", bookId: "php", chapters: ["1", "2"] } as never);
    currentChapter.set("1");
    chapterVerseNums.set({ "1": ["1", "2"] });
    const late = lqaFinding({ id: "b", chapter: "1", verse: "1", start: 9, end: 12, originalText: "late" });
    const early = lqaFinding({ id: "a", chapter: "1", verse: "1", start: 0, end: 4, originalText: "early" });
    const second = lqaFinding({ id: "c", chapter: "1", verse: "2", start: 2, end: 5, originalText: "next" });
    languageQaFindingsByVerse.set({ [verseKey("1", "1")]: [late, early], [verseKey("1", "2")]: [second] });
    const onNavigate = await openBookList();
    await fireEvent.keyDown(window, { key: "F8" });
    expect(get(focusedFindingId)).toBe("a");
    expect(get(selectedVerse)).toBe("1");
    expect(screen.getByRole("status")).toHaveTextContent("Finding 1 of 3 in chapter 1: early");
    await fireEvent.keyDown(window, { key: "F8" });
    await fireEvent.keyDown(window, { key: "F8" });
    expect(get(focusedFindingId)).toBe("c");
    await fireEvent.keyDown(window, { key: "F8", shiftKey: true });
    expect(get(focusedFindingId)).toBe("b");
    const input = document.createElement("input");
    document.body.appendChild(input);
    await fireEvent.keyDown(input, { key: "F8" });
    expect(get(focusedFindingId)).toBe("b");
    input.remove();
    await fireEvent.keyDown(window, { key: "F8" });
    await fireEvent.keyDown(window, { key: "F8" });
    expect(onNavigate).toHaveBeenCalledWith("php", "2", "");
  });

  /** A mark where VerseList would draw it, with a scroll spy. */
  function plantMark(id: string): ReturnType<typeof vi.fn> {
    const mark = document.createElement("mark");
    mark.setAttribute("data-finding-ids", id);
    const scrollIntoView = vi.fn();
    (mark as unknown as { scrollIntoView: unknown }).scrollIntoView = scrollIntoView;
    document.body.appendChild(mark);
    return scrollIntoView;
  }

  it("a card's reference opens the verse, then rings and centres the finding's mark (#402)", async () => {
    const scrollIntoView = plantMark("f1");
    const onNavigate = vi.fn(async () => {
      // The ring is set before the verse opens, so the verse list knows not
      // to pull the verse to the top under the mark's own scroll.
      expect(get(focusedFindingId)).toBe("f1");
    });
    await openBookList(onNavigate);
    await fireEvent.click(screen.getByRole("button", { name: "PHP 2:3-4" }));
    expect(onNavigate).toHaveBeenCalledWith("php", "2", "3-4");
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledWith({ block: "center" }));
    expect(document.querySelector("mark.reveal-flash")).not.toBeNull();
  });

  it("a heading finding's reference only opens the verse (#402)", async () => {
    statusCall.mockImplementation(async (_path, _offset, limit) => snapshot({ findings: limit ? [
      lqaFinding({ id: "h1", chapter: "2", verse: "1", rule: "unicode.corruption", start: 0, end: 1, originalText: "�",
        message: "Check source encoding.", suggestedReplacement: null, context: "heading", contextText: "A title" }),
    ] : [] }));
    const scrollIntoView = plantMark("h1");
    const onNavigate = await openBookList();
    await fireEvent.click(screen.getByRole("button", { name: "PHP 2:1" }));
    expect(onNavigate).toHaveBeenCalledWith("php", "2", "1");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(get(focusedFindingId)).toBeNull();
    expect(scrollIntoView).not.toHaveBeenCalled();
  });
});

describe("language-aware About (#415)", () => {
  it("suppresses Tamil glosses from shared categories for a Hindi effective pack", async () => {
    const language = { declared: "hin", language: "hi", name: "Hindi", script: "DEVANAGARI", basis: "metadata", pack: "hi-irv", message: "Hindi checks." };
    publish({ language }); statusCall.mockResolvedValue(snapshot({ language }));
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    await fireEvent.click(screen.getByRole("button", { name: "About these checks" }));
    const about = screen.getByRole("dialog", { name: "What Language QA checks" });
    expect(about.querySelector('[lang="ta"]')).toBeNull(); expect(about).toHaveTextContent("About Language QA · Hindi");
    expect(about).toHaveTextContent("Effective pack: hi-irv");
  });
  it("follows a Settings override immediately and ignores a late page for the old pack", async () => {
    let finish!: (value: LanguageQaStatus) => void;
    statusCall.mockImplementationOnce(() => new Promise<LanguageQaStatus>(resolve => finish = resolve));
    publish({});
    await openBook();
    await fireEvent.click(screen.getByRole("button", { name: "About these checks" }));
    const language = { declared: "tam", language: "hi", name: "Hindi", script: "DEVANAGARI", basis: "setting", setting: "hi-irv", pack: "hi-irv", message: "Hindi checks." };
    statusCall.mockResolvedValue(snapshot({ language, setting: "hi-irv" }));
    publish({ language, setting: "hi-irv" }); await tick(); finish(snapshot()); await tick();
    await waitFor(() => expect(screen.getByRole("dialog", { name: "What Language QA checks" })).toHaveTextContent("Effective pack: hi-irv"));
    const about = screen.getByRole("dialog", { name: "What Language QA checks" });
    expect(about).toHaveTextContent("Project language: tam"); expect(about).toHaveTextContent("Selected in Settings");
    expect(about.querySelector('[lang="ta"]')).toBeNull();
  });
  it.each(["off", "common"])("describes the %s state without implying language-specific checks", async mode => {
    const language = { declared: "zz", language: "zz", script: "LATIN", basis: mode === "off" ? "setting-off" : "undetermined", pack: "common", message: "Common checks only." };
    const value = { language, setting: mode === "off" ? "off" : "auto" };
    publish(value); statusCall.mockResolvedValue(snapshot(value));
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    await fireEvent.click(screen.getByRole("button", { name: "About these checks" }));
    const about = screen.getByRole("dialog", { name: "What Language QA checks" });
    expect(about).toHaveTextContent(mode === "off" ? "switched off" : "Only common technical checks");
    expect(about.querySelector('[lang="ta"]')).toBeNull();
    // Older engine summaries can carry the Tamil/default category inventory
    // in common-only mode. Do not advertise those as this language's checks.
    expect(about).not.toHaveTextContent("Sandhi");
  });
});
