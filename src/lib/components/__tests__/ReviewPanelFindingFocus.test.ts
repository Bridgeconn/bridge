/**
 * #402: a Review panel card lands on its finding's span. Clicking the card
 * (or its number badge) rings the mark in the verse text and scrolls it into
 * view; "Accept and edit" and the ignored card's "Edit verse" open the editor
 * with the finding's words selected. The verse text itself is VerseList's;
 * here a mark and a textarea are planted where that component would render
 * them, so what the panel asks of them is observable.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";

const { known } = vi.hoisted(() => ({ known: {} as Record<string, unknown> }));

vi.mock("../../api/bridgeClient", () => ({
  bridge: new Proxy(known, {
    get: (target, name: string) => {
      if (!(name in target)) target[name] = vi.fn().mockResolvedValue({ items: [], findings: [], hidden: [] });
      return target[name];
    },
  }),
}));

import ReviewPanel from "../ReviewPanel.svelte";
import {
  chapterVerseNums, checkGroupsByVerse, currentChapter, findingsByVerse, focusedFindingId, project, selectedVerse,
  verseKey, verseTexts,
} from "../../stores";
import { cancelVerseEdit, editingVerse } from "../../verseEditor";
import type { QaFinding } from "../../types/finding";

const TEXT = "𝔸 alpha beta gamma";
// "𝔸" is one code point but two UTF-16 units: the engine's offsets are code
// points, the textarea's selection is not.
const BETA_START = 8;
const BETA_END = 12;

function greekRoom(overrides: Partial<QaFinding> = {}): QaFinding {
  return {
    id: "gr-1", project_id: "p", book: "php", chapter: 1, verse: 6, start_offset: BETA_START, end_offset: BETA_END,
    original_text: "beta", engine: "wildebeest", check: "wildebeest", check_type: "wildebeest.x", category: "unicode",
    severity: "medium", confidence: 0.8, suggested_replacement: null, explanation: "Mixed script", evidence: [],
    engine_version: "1", resource_versions: {}, status: "open", human_comment: null, created_at: "", resolved_at: null,
    ...overrides,
  } as QaFinding;
}

/** The verse row VerseList would render for 1:6, reduced to what the panel reaches into. */
function plantVerseRow(editing: boolean): { mark: HTMLElement; scrollIntoView: ReturnType<typeof vi.fn> } {
  const row = document.createElement("div");
  row.setAttribute("data-verse-key", verseKey("1", "6"));
  const mark = document.createElement("mark");
  mark.setAttribute("data-finding-ids", "gr-1");
  mark.textContent = "beta";
  const scrollIntoView = vi.fn();
  (mark as unknown as { scrollIntoView: unknown }).scrollIntoView = scrollIntoView;
  row.appendChild(mark);
  if (editing) {
    const area = document.createElement("textarea");
    area.value = TEXT;
    row.appendChild(area);
  }
  document.body.appendChild(row);
  return { mark, scrollIntoView };
}

describe("ReviewPanel cards land on the finding's span (#402)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    project.set({ path: "/p", bookId: "php" } as never);
    currentChapter.set("1");
    chapterVerseNums.set({ "1": ["6"] });
    verseTexts.set({ [verseKey("1", "6")]: TEXT });
    findingsByVerse.set({ [verseKey("1", "6")]: [greekRoom()] });
    checkGroupsByVerse.set({ [verseKey("1", "6")]: ["wildebeest"] });
    selectedVerse.set("6");
  });

  afterEach(() => {
    cancelVerseEdit();
    focusedFindingId.set(null);
    selectedVerse.set(null);
    document.body.innerHTML = "";
  });

  it("a click on the card rings the mark and scrolls it to the centre; a click on a control does not", async () => {
    const { mark, scrollIntoView } = plantVerseRow(false);
    render(ReviewPanel);
    await fireEvent.click(await screen.findByRole("tab", { name: /Greek Room/ }));
    const explain = await screen.findByText("Mixed script");
    await fireEvent.click(explain);
    expect(get(focusedFindingId)).toBe("gr-1");
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledWith({ block: "center" }));
    expect(mark.classList.contains("reveal-flash")).toBe(true);

    focusedFindingId.set(null);
    scrollIntoView.mockClear();
    await fireEvent.click(screen.getByRole("button", { name: "⊘ Ignore" }));
    expect(get(focusedFindingId)).toBeNull();
    expect(scrollIntoView).not.toHaveBeenCalled();
  });

  it("the number badge is the keyboard route to the mark", async () => {
    const { scrollIntoView } = plantVerseRow(false);
    render(ReviewPanel);
    await fireEvent.click(await screen.findByRole("tab", { name: /Greek Room/ }));
    const badge = await screen.findByRole("button", { name: "Show finding 1 in the verse text" });
    await fireEvent.click(badge);
    expect(get(focusedFindingId)).toBe("gr-1");
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledWith({ block: "center" }));
  });

  it("Accept and edit opens the verse with the finding's words selected, in UTF-16 units", async () => {
    render(ReviewPanel);
    await fireEvent.click(await screen.findByRole("tab", { name: /Greek Room/ }));
    // The editor's textarea appears once VerseList re-renders for the edit;
    // here it is planted at the moment the edit starts, as that render would.
    const unsubscribe = editingVerse.subscribe((verse) => {
      if (verse === "6" && !document.querySelector("textarea")) plantVerseRow(true);
    });
    try {
      await fireEvent.click(await screen.findByRole("button", { name: "✎ Accept and edit" }));
      expect(get(editingVerse)).toBe("6");
      const area = document.querySelector("textarea") as HTMLTextAreaElement;
      await waitFor(() => expect(area.selectionStart).toBe(BETA_START + 1));
      expect(area.value.slice(area.selectionStart, area.selectionEnd)).toBe("beta");
    } finally {
      unsubscribe();
    }
  });

  it("a finding with no span opens the verse with nothing selected", async () => {
    findingsByVerse.set({ [verseKey("1", "6")]: [greekRoom({ start_offset: null, end_offset: null, original_text: "" })] });
    render(ReviewPanel);
    await fireEvent.click(await screen.findByRole("tab", { name: /Greek Room/ }));
    const unsubscribe = editingVerse.subscribe((verse) => {
      if (verse === "6" && !document.querySelector("textarea")) plantVerseRow(true);
    });
    try {
      await fireEvent.click(await screen.findByRole("button", { name: "✎ Accept and edit" }));
      expect(get(editingVerse)).toBe("6");
      await new Promise((resolve) => setTimeout(resolve, 0));
      const area = document.querySelector("textarea") as HTMLTextAreaElement;
      expect(area.selectionStart === BETA_START + 1 && area.selectionEnd === BETA_END + 1).toBe(false);
    } finally {
      unsubscribe();
    }
  });
});
