import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
// @ts-expect-error The app tsconfig has no node types; vitest runs under node.
import { readFileSync } from "node:fs";
// @ts-expect-error As above.
import { resolve } from "node:path";
// @ts-expect-error As above.
import process from "node:process";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";

// Layered-rules Phase 4.3: the review panel lists the selected verse's
// Language QA findings (inline or not) with the same actions as the verse
// menu, so the Language QA panel is not the only place to act on one.
const { languageQaVerse, decideVerse, known } = vi.hoisted(() => ({
  languageQaVerse: vi.fn(),
  decideVerse: vi.fn(),
  known: {} as Record<string, unknown>,
}));

vi.mock("../../api/bridgeClient", () => ({
  // Everything else the panel calls on mount resolves to an empty answer.
  bridge: new Proxy(known, {
    get: (target, name: string) => {
      if (name === "languageQaVerse") return languageQaVerse;
      if (name === "decideVerse") return decideVerse;
      if (name === "runVerseChecks") return vi.fn().mockResolvedValue([]);
      if (!(name in target)) target[name] = vi.fn().mockResolvedValue({ items: [] });
      return target[name];
    },
  }),
}));

import ReviewPanel from "../ReviewPanel.svelte";
import { currentChapter, project, selectedVerse, verseTexts, verseKey } from "../../stores";
import { languageQaChannel } from "../../languageQaInline";
import { setSidePanel, sidePanels } from "../../editorPrefs";
import { reviewTabRequest } from "../../stores";
import { showLanguageQaTab } from "../../languageQaPanelUi";
import { get } from "svelte/store";
import { lqaFinding } from "./languageQaFixture";
import { scopeDialog } from "../../scopedApply";
import type { LanguageQaStatus } from "../../types/languageQa";

function channel(generation: number, state: LanguageQaStatus["state"] = "completed"): void {
  languageQaChannel.set({
    projectPath: "/p", error: "",
    status: { projectPath: "/p", state, generation } as unknown as LanguageQaStatus,
  });
}

describe("ReviewPanel Language QA tab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    project.set({ path: "/p", bookId: "php" } as never);
    currentChapter.set("1");
    verseTexts.set({ [verseKey("1", "6")]: "அந்த காகம் பறந்தது." });
    decideVerse.mockResolvedValue({});
    languageQaVerse.mockResolvedValue({
      projectPath: "/p", generation: 3, state: "completed", chapter: "1", verse: "6",
      findings: [lqaFinding({ id: "lqa-p", rule: "tamil.wordlist-variant", inline: false })],
      hidden: [{ ...lqaFinding({ id: "lqa-h" }), decision: "ignored" }],
    });
    channel(3);
    selectedVerse.set("6");
  });

  afterEach(() => {
    selectedVerse.set(null);
    languageQaChannel.set({ projectPath: "", status: null, error: "" });
  });

  it("lists the verse's findings, panel-only ones included, counts them on the tab, and ignores one before the engine answers", async () => {
    render(ReviewPanel);
    await waitFor(() => expect(languageQaVerse).toHaveBeenCalledWith("/p", "1", "6"));
    await waitFor(() => expect(screen.getByRole("tab", { name: /Language QA/ }).querySelector(".tab-count")?.textContent).toBe("1"));
    await fireEvent.click(screen.getByRole("tab", { name: /Language QA/ }));
    expect(await screen.findByText("ta-irv/tamil.wordlist-variant")).toBeInTheDocument();
    expect(screen.getByText(/Decided \(1\)/)).toBeInTheDocument();
    // The tab is the old panel's body too: its scope switch, lists and Kinds.
    expect(screen.getByRole("radiogroup", { name: "Show findings for" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Verse" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("tablist", { name: "Language QA panel" })).toBeInTheDocument();
    let release: (value: unknown) => void = () => {};
    decideVerse.mockReturnValue(new Promise((resolve) => { release = resolve; }));
    await fireEvent.click(screen.getByRole("button", { name: "⊘ Ignore" }));
    // Gone from the list at once; the decision is sent with the Language QA issue.
    expect(document.querySelector('[data-lqa-id="lqa-p"]')).toBeNull();
    expect(decideVerse).toHaveBeenCalledWith("1", "6", "lqa-p", "ignored", undefined,
      expect.objectContaining({ source: "languageQa" }));
    release({});
  });

  it("labels a learned fix and Forget drops every recurrence without recording a decision", async () => {
    const learned = (id: string, start: number) => lqaFinding({
      id, rule: "learned.replacement", category: "learned", layer: "housestyle", originalText: "தேவன்",
      start, end: start + 5, suggestions: [{ text: "கர்த்தர்", rank: 1, source: "learned", rationale: "Replaced with this 2× before." }],
    });
    languageQaVerse.mockResolvedValue({
      projectPath: "/p", generation: 3, state: "completed", chapter: "1", verse: "6",
      findings: [learned("l1", 0), learned("l2", 10)], hidden: [],
    });
    render(ReviewPanel);
    await fireEvent.click(screen.getByRole("tab", { name: /Language QA/ }));
    expect((await screen.findAllByText("learned fix", { selector: ".engine-badge" })).length).toBe(2);
    await fireEvent.click(screen.getAllByRole("button", { name: "Forget this fix" })[0]);
    expect(document.querySelector('[data-lqa-id="l1"]')).toBeNull();
    expect(document.querySelector('[data-lqa-id="l2"]')).toBeNull();
    // The Proxy creates the stub on the panel's first call, so read it afterwards.
    await waitFor(() => expect(known.languageQaLearnedForget).toHaveBeenCalledWith("/p", "தேவன்", "கர்த்தர்"));
    expect(decideVerse).not.toHaveBeenCalled();
  });

  it("Apply to: Whole chapter asks for every place first instead of writing this verse", async () => {
    languageQaVerse.mockResolvedValue({
      projectPath: "/p", generation: 3, state: "completed", chapter: "1", verse: "6",
      findings: [lqaFinding({ id: "lqa-s" })], hidden: [],
    });
    render(ReviewPanel);
    await fireEvent.click(screen.getByRole("tab", { name: /Language QA/ }));
    await fireEvent.click(await screen.findByRole("radio", { name: "Whole chapter" }));
    expect(screen.getByRole("radio", { name: "Whole chapter" })).toHaveAttribute("aria-checked", "true");
    await fireEvent.click(screen.getByRole("button", { name: /^Use / }));
    await waitFor(() => expect(known.languageQaScopeFind).toHaveBeenCalledWith(
      "/p", "1", "6", "lqa-s", "chapter", "அந்தக் காகம்"));
    expect(decideVerse).not.toHaveBeenCalled();
    // Nothing is removed or written until the reviewer confirms.
    expect(document.querySelector('[data-lqa-id="lqa-s"]')).not.toBeNull();
    scopeDialog.set(null);
  });

  it("refetches when a new pass lands, not on every status tick", async () => {
    render(ReviewPanel);
    await waitFor(() => expect(languageQaVerse).toHaveBeenCalledTimes(1));
    channel(3);
    channel(3);
    await Promise.resolve();
    expect(languageQaVerse).toHaveBeenCalledTimes(1);
    // A new pass, queued or running: the engine still holds the last pass's
    // findings for the verse, so they are read (#237); again once it completes.
    channel(4, "running");
    await waitFor(() => expect(languageQaVerse).toHaveBeenCalledTimes(2));
    channel(4);
    await waitFor(() => expect(languageQaVerse).toHaveBeenCalledTimes(3));
  });

  // #487: the tab has no toggle of its own. A profile saved with the old
  // Language QA column closed still shows it (the saved flag is dropped on
  // read: sourcePanelPrefs.test.ts), and a request lands on it.
  it("the tab is always present, and a request for it (the status bar button, a verse's open-issue pill) selects it", async () => {
    render(ReviewPanel);
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent?.trim().replace(/\s*\d+$/, "")))
      .toEqual(["Greek Room", "Core check", "Language QA", "AI review"]);
    setSidePanel("review", { open: false });
    showLanguageQaTab();
    await waitFor(() => expect(screen.getByRole("tab", { name: /Language QA/ }).getAttribute("aria-selected")).toBe("true"));
    expect(get(sidePanels).review.open).toBe(true);
    expect(get(reviewTabRequest)).toBeNull();
  });

  // #487 bug (Revant's desktop check, 2026-11-11): after Language QA -> AI
  // review, Language QA stayed drawn at the top with AI review under it. The
  // tab is kept mounted and hidden with the `hidden` attribute, and
  // `.lqa-panel { display: flow-root }` on that same element overrode the
  // browser's `[hidden] { display: none }`, so it was never hidden on any
  // tab; its sticky head then sat over whatever scrolled beneath.
  it("only the selected tab's panel is shown, whichever order the tabs are visited in", async () => {
    render(ReviewPanel);
    const shown = () => Array.from(document.querySelectorAll<HTMLElement>("[role='tabpanel']")).filter((panel) => !panel.hidden);
    const lqa = () => document.querySelector<HTMLElement>("[role='tabpanel'][data-tab='lqa']")!;
    const visit = [/Language QA/, /AI review/, /Greek Room/, /Language QA/, /Core check/, /AI review/, /Language QA/];
    for (const name of visit) {
      await fireEvent.click(screen.getByRole("tab", { name }));
      expect(shown(), String(name)).toHaveLength(1);
      expect(lqa().hidden, String(name)).toBe(String(name) !== String(/Language QA/));
      // The Language QA body stays mounted (its scope and lists survive), hidden or not.
      expect(lqa().querySelector("[aria-label='Language QA']")).not.toBeNull();
    }
  });

  // jsdom applies no component stylesheet, so the DOM test above cannot see
  // the override itself. This pins the rule that caused it: no element that
  // is hidden with `hidden` may be given a `display` by ReviewPanel's styles.
  it("no style rule gives a hidden tab panel a display of its own", () => {
    const source: string = readFileSync(resolve(process.cwd(), "src/lib/components/ReviewPanel.svelte"), "utf-8");
    const style = source.slice(source.indexOf("<style>")).replace(/\/\*[\s\S]*?\*\//g, "");
    const markup = source.slice(0, source.indexOf("<style>"));
    // Every class carried by an element that also carries `hidden={...}`.
    const hiddenClasses = new Set<string>();
    for (const tag of markup.match(/<[a-z][^>]*\shidden=\{[^>]*>/g) ?? []) {
      for (const name of (/class="([^"]*)"/.exec(tag)?.[1] ?? "").split(/\s+/).filter(Boolean)) hiddenClasses.add(name);
    }
    expect([...hiddenClasses]).toContain("tab-panel");
    const offenders: string[] = [];
    for (const [, selector, body] of style.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
      if (!/(^|[;\s])display\s*:/.test(body)) continue;
      for (const name of hiddenClasses) {
        const targets = selector.split(",").some((part) => new RegExp(`\\.${name}(?![\\w-])[^\\s>+~]*$`).test(part.trim()));
        const hides = /display\s*:\s*none/.test(body);
        if (targets && !hides) offenders.push(selector.trim());
      }
    }
    expect(offenders).toEqual([]);
    expect(style).toMatch(/\.tab-panel\[hidden\]\s*\{\s*display:\s*none\s*!important/);
  });

  it("puts a finding back when recording its decision fails", async () => {
    decideVerse.mockRejectedValue(new Error("disk full"));
    render(ReviewPanel);
    await fireEvent.click(screen.getByRole("tab", { name: /Language QA/ }));
    await screen.findByText("ta-irv/tamil.wordlist-variant");
    await fireEvent.click(screen.getByRole("button", { name: "False positive" }));
    expect(await screen.findByText("disk full")).toBeInTheDocument();
    expect(document.querySelector('[data-lqa-id="lqa-p"]')).not.toBeNull();
  });
});

describe("ReviewPanel folding (#236)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    project.set({ path: "/p", bookId: "php" } as never);
    currentChapter.set("1");
    verseTexts.set({ [verseKey("1", "6")]: "அந்த காகம் பறந்தது." });
    languageQaVerse.mockResolvedValue({
      projectPath: "/p", generation: 3, state: "completed", chapter: "1", verse: "6",
      findings: [lqaFinding({ id: "lqa-p", rule: "tamil.wordlist-variant", inline: false })], hidden: [],
    });
    channel(3);
    selectedVerse.set("6");
  });

  afterEach(() => {
    setSidePanel("review", { open: true });
    selectedVerse.set(null);
    languageQaChannel.set({ projectPath: "", status: null, error: "" });
  });

  it("keeps the four tabs to one line each, the helps tab as Core check with its tooltip", async () => {
    render(ReviewPanel);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent?.trim().replace(/\s*\d+$/, ""))).toEqual(
      ["Greek Room", "Core check", "Language QA", "AI review"]);
    expect(screen.getByRole("tab", { name: /Core check/ }).getAttribute("title")).toBe("Translation Notes, Words alignment");
    // #379 item 6: the reference and the open count are in the shared bar,
    // so Review shows one line like the other panels; nothing sits between
    // the bar and the tabs. #486: the Align and Edit glyph buttons are gone
    // from the bar (both actions are on the verse in the editor).
    const bar = document.querySelector("[data-panel-bar='review']") as HTMLElement;
    expect(bar).not.toBeNull();
    expect(bar.querySelector(".panel-actions .open-count")?.textContent).toMatch(/^\d+ open$/);
    expect(bar.querySelector(".panel-actions button[aria-label='Align words']")).toBeNull();
    expect(bar.querySelector(".panel-actions button[aria-label='Edit verse']")).toBeNull();
    expect(bar.querySelectorAll(".panel-actions button").length).toBe(0);
    expect(document.querySelector(".panel-header")).toBeNull();
    expect(bar.nextElementSibling?.querySelector("[role='tablist']") ?? bar.nextElementSibling).not.toBeNull();
  });

  it("no tab repeats its own title inside its body; the run controls stay (#486)", async () => {
    render(ReviewPanel);
    const titlesIn = () => [...document.querySelectorAll(".tab-content .section-title")].map((el) => el.textContent?.trim() ?? "");
    // Greek Room: the run button and the chapter line, no "Greek Room QA" heading.
    expect(titlesIn().some((t) => /^Greek Room/.test(t))).toBe(false);
    expect(screen.getByRole("button", { name: /Run Greek Room/ })).toBeInTheDocument();
    expect(screen.getByTestId("greek-room-chapter-summary")).toBeInTheDocument();
    // Language QA: the findings, no "Language QA" heading.
    await fireEvent.click(screen.getByRole("tab", { name: /Language QA/ }));
    await screen.findByText("ta-irv/tamil.wordlist-variant");
    expect(titlesIn().some((t) => /^Language QA/.test(t))).toBe(false);
    // AI review: the three run buttons, no "AI review" label beside them.
    await fireEvent.click(screen.getByRole("tab", { name: /AI review/ }));
    expect(document.querySelector(".ai-run-label")?.textContent).not.toMatch(/AI review/);
    expect(screen.getByRole("button", { name: "Verse" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Chapter" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Book" })).toBeInTheDocument();
  });

  it("closes its column from its header, and the choice is remembered", async () => {
    render(ReviewPanel);
    await fireEvent.click(screen.getByRole("button", { name: "Close the review panel" }));
    expect(get(sidePanels).review.open).toBe(false);
    expect(JSON.parse(localStorage.getItem("bridge.editor.sidePanels.v1") ?? "{}").review.open).toBe(false);
  });
});
