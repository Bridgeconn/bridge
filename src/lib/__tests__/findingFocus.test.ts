/**
 * #402: one route from "this finding" to its span in the verse text. The
 * component tests cover each entry point; this file pins the helper's own
 * contract: the ring is set before the navigation runs (so the verse list can
 * skip its scroll-to-top), the mark is scrolled to the centre and flashed, a
 * click on the mark itself never scrolls, and a finding with no mark leaves
 * the ring set and moves nothing.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { findingSpan, pendingReveal, revealFinding } from "../findingFocus";
import { focusedFindingId } from "../stores";
import { lqaFinding } from "../components/__tests__/languageQaFixture";
import type { QaFinding } from "../types/finding";

function qaFinding(overrides: Partial<QaFinding> = {}): QaFinding {
  return {
    id: "q1", project_id: "p", book: "php", chapter: 1, verse: 6, start_offset: 2, end_offset: 7,
    original_text: "alpha", engine: "wildebeest", check_type: "x", category: "unicode", severity: "low",
    confidence: 0.5, suggested_replacement: null, explanation: "", evidence: [], engine_version: "1",
    resource_versions: {}, status: "open", human_comment: null, created_at: "", resolved_at: null, ...overrides,
  };
}

function plantMark(id: string): HTMLElement & { scrollIntoView: ReturnType<typeof vi.fn> } {
  const mark = document.createElement("mark");
  mark.setAttribute("data-finding-ids", `other ${id}`);
  mark.textContent = "word";
  (mark as unknown as { scrollIntoView: unknown }).scrollIntoView = vi.fn();
  document.body.appendChild(mark);
  return mark as HTMLElement & { scrollIntoView: ReturnType<typeof vi.fn> };
}

afterEach(() => {
  document.body.innerHTML = "";
  focusedFindingId.set(null);
});

describe("findingSpan", () => {
  it("reads either finding type, and is null where the span cannot be located", () => {
    expect(findingSpan(qaFinding())).toEqual({ start: 2, end: 7 });
    expect(findingSpan(qaFinding({ start_offset: null, end_offset: null }))).toBeNull();
    expect(findingSpan(lqaFinding({ start: 3, end: 9 }))).toEqual({ start: 3, end: 9 });
    expect(findingSpan(lqaFinding({ start: 3, end: 9, context: "heading", contextText: "Title" }))).toBeNull();
    expect(findingSpan(lqaFinding({ context: "footnote" }))).toBeNull();
  });
});

describe("revealFinding", () => {
  it("rings before navigating, then centres the mark and flashes it", async () => {
    const mark = plantMark("f9");
    let ringAtNavigate: string | null = null;
    let pendingAtNavigate: string | null = null;
    const navigate = vi.fn(async () => {
      ringAtNavigate = get(focusedFindingId);
      pendingAtNavigate = pendingReveal();
    });
    expect(await revealFinding("f9", { navigate })).toBe(true);
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(ringAtNavigate).toBe("f9");
    expect(pendingAtNavigate).toBe("f9");
    expect(pendingReveal()).toBeNull();
    expect(mark.scrollIntoView).toHaveBeenCalledWith({ block: "center" });
    expect(mark.classList.contains("reveal-flash")).toBe(true);
  });

  it("does not scroll for a click on the mark itself (#179), but still rings and flashes", async () => {
    const mark = plantMark("f9");
    expect(await revealFinding("f9", { scroll: false })).toBe(true);
    expect(mark.scrollIntoView).not.toHaveBeenCalled();
    expect(get(focusedFindingId)).toBe("f9");
    expect(mark.classList.contains("reveal-flash")).toBe(true);
  });

  it("keeps the ring and moves nothing when the finding has no mark", async () => {
    const other = plantMark("elsewhere");
    expect(await revealFinding("missing")).toBe(false);
    expect(get(focusedFindingId)).toBe("missing");
    expect(other.scrollIntoView).not.toHaveBeenCalled();
    expect(pendingReveal()).toBeNull();
  });
});
