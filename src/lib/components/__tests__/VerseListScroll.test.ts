/**
 * #179: clicking or right-clicking something already on screen must never
 * scroll the verse list. Every pointer and keyboard route into a selection
 * goes through selectFromList, which marks the verse as already scrolled
 * before the reactive scroll-to-top sees the new selection; only navigation
 * that does not start from the list (Go to, desktop sync, a report row)
 * still scrolls. The scroll container's scrollTo is the one observable.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render } from "@testing-library/svelte";
import { tick } from "svelte";

vi.mock("../../api/bridgeClient", () => ({
  bridge: {
    decideVerse: vi.fn().mockResolvedValue(undefined),
    editVerse: vi.fn().mockResolvedValue({ issueResolutionsNeedingRecheck: 0 }),
    runVerseChecks: vi.fn().mockResolvedValue([]),
    housestyleRecord: vi.fn().mockResolvedValue({}),
  },
}));

import VerseList from "../VerseList.svelte";
import { lqaFinding } from "./languageQaFixture";
import { displayFor } from "./verseDisplayFixtures";
import {
  chapterVerseNums, currentChapter, findingsByVerse, headingsByVerse, languageQaFindingsByVerse,
  selectedVerse, verseDisplay, verseKey, verseTexts,
} from "../../stores";
import type { QaFinding } from "../../types/finding";

const TEXT = "அந்த காகம் பறந்தது.";
const FLAGGED_END = Array.from("அந்த காகம்").length;

function greekRoomFinding(verse: number): QaFinding {
  return {
    id: `gr-${verse}`, project_id: "p1", book: "php", chapter: 1, verse,
    start_offset: 0, end_offset: FLAGGED_END, original_text: "அந்த காகம்", engine: "wildebeest",
    check_type: "wildebeest.notable_token", category: "unicode", severity: "medium", confidence: 0.8,
    suggested_replacement: null, explanation: "Mixed script", evidence: [], engine_version: "1",
    resource_versions: {}, status: "open", human_comment: null, created_at: "2026-09-06T00:00:00Z",
    resolved_at: null,
  };
}

const scrollTo = vi.fn();

beforeEach(() => {
  Element.prototype.scrollTo = scrollTo as never;
  scrollTo.mockClear();
  currentChapter.set("1");
  chapterVerseNums.set({ "1": ["1", "2", "3"] });
  verseTexts.set({ "1:1": TEXT, "1:2": TEXT, "1:3": TEXT });
  verseDisplay.set({ "1:1": displayFor(TEXT), "1:2": displayFor(TEXT), "1:3": displayFor(TEXT) });
  headingsByVerse.set({});
  findingsByVerse.set({ "1:1": [greekRoomFinding(1)], "1:2": [greekRoomFinding(2)], "1:3": [greekRoomFinding(3)] });
  languageQaFindingsByVerse.set({ "1:2": [lqaFinding({ id: "lqa-2", verse: "2" })] });
  selectedVerse.set("1");
});

afterEach(() => {
  cleanup();
  languageQaFindingsByVerse.set({});
});

/** What App.svelte's onSelect does: the store is the selection. */
function mount() {
  render(VerseList, { props: { onSelect: (v: string) => selectedVerse.set(v) } });
}

function mark(verse: string): HTMLElement {
  return document.querySelector(`[data-verse-key="${verseKey("1", verse)}"] mark`) as HTMLElement;
}

async function settled(): Promise<void> {
  await tick();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("the verse list does not scroll on a click (#179)", () => {
  it("right-click on a Greek Room mark of another verse opens the menu with no scroll", async () => {
    mount();
    await settled();
    scrollTo.mockClear();
    await fireEvent.contextMenu(mark("3"));
    await settled();
    expect(document.querySelector('[role="menu"]')).not.toBeNull();
    expect(selectedVerse_get()).toBe("3");
    expect(scrollTo).not.toHaveBeenCalled();
  });

  it("right-click on a Language QA mark: no scroll", async () => {
    mount();
    await settled();
    scrollTo.mockClear();
    await fireEvent.contextMenu(document.querySelector('[data-finding-ids~="lqa-2"]') as HTMLElement);
    await settled();
    expect(selectedVerse_get()).toBe("2");
    expect(scrollTo).not.toHaveBeenCalled();
  });

  it("left-click on a mark, Shift-click and Ctrl-click on a row: no scroll", async () => {
    mount();
    await settled();
    scrollTo.mockClear();
    await fireEvent.click(mark("2"));
    await settled();
    expect(selectedVerse_get()).toBe("2");
    await fireEvent.click(document.querySelector('[data-verse-key="1:3"]') as HTMLElement, { shiftKey: true });
    await settled();
    expect(selectedVerse_get()).toBe("3");
    await fireEvent.click(document.querySelector('[data-verse-key="1:1"]') as HTMLElement, { ctrlKey: true });
    await settled();
    expect(selectedVerse_get()).toBe("1");
    expect(scrollTo).not.toHaveBeenCalled();
  });

  it("keyboard menu (Shift+F10) and Enter on a focused row: no scroll", async () => {
    mount();
    await settled();
    scrollTo.mockClear();
    const row = document.querySelector('[data-verse-key="1:2"]') as HTMLElement;
    await fireEvent.keyDown(row, { key: "F10", shiftKey: true });
    await settled();
    expect(selectedVerse_get()).toBe("2");
    await fireEvent.keyDown(document.querySelector('[data-verse-key="1:3"]') as HTMLElement, { key: "Enter" });
    await settled();
    expect(selectedVerse_get()).toBe("3");
    expect(scrollTo).not.toHaveBeenCalled();
  });

  it("a selection that does not come from the list (Go to, sync, a report row) still scrolls", async () => {
    mount();
    await settled();
    scrollTo.mockClear();
    selectedVerse.set("3");
    await settled();
    expect(scrollTo).toHaveBeenCalledTimes(1);
  });
});

function selectedVerse_get(): string | null {
  let value: string | null = null;
  selectedVerse.subscribe((v) => (value = v))();
  return value;
}
