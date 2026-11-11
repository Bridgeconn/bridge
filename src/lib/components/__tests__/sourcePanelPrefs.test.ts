import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

const KEY = "bridge.editor.sidePanels.v1";

/** The layout is read when editorPrefs is first evaluated: reset and re-import. */
async function freshPrefs() {
  vi.resetModules();
  return import("../../editorPrefs");
}

describe("the source-text column in the saved panel layout (#67)", () => {
  beforeEach(() => localStorage.clear());

  it("a layout saved before the column existed keeps its widths and gains the column, closed", async () => {
    const before = {
      reference: { open: true, width: 360 },
      languageQa: { open: false, width: 500 },
      review: { open: true, width: 420 },
    };
    localStorage.setItem(KEY, JSON.stringify(before));
    const { sidePanels, SIDE_PANEL_LIMITS } = await freshPrefs();
    const now = get(sidePanels);
    expect(now.reference).toEqual(before.reference);
    // #487: Language QA is no longer a panel; its saved entry is dropped.
    expect("languageQa" in now).toBe(false);
    expect(now.review).toEqual(before.review);
    expect(now.source).toEqual({ open: false, width: SIDE_PANEL_LIMITS.source.initial });
  });

  // #487: a profile saved with the old Language QA column closed keeps every
  // other panel and its own column order; only the retired id goes.
  it("drops the retired Language QA panel from a saved layout and a saved order, keeping the rest", async () => {
    localStorage.setItem(KEY, JSON.stringify({
      source: { open: true, width: 333 }, reference: { open: false, width: 360 },
      languageQa: { open: false, width: 500 }, paratext: { open: false, width: 340 }, review: { open: true, width: 420 },
    }));
    localStorage.setItem("bridge.editor.sidePanelOrder.v1", JSON.stringify(["review", "languageQa", "source", "reference", "paratext"]));
    const { sidePanels, sidePanelOrder, SIDE_PANEL_ORDER } = await freshPrefs();
    expect(SIDE_PANEL_ORDER).toEqual(["source", "reference", "paratext", "review"]);
    expect(Object.keys(get(sidePanels)).sort()).toEqual(["paratext", "reference", "review", "source"]);
    expect(get(sidePanels).source).toEqual({ open: true, width: 333 });
    expect(get(sidePanelOrder)).toEqual(["review", "source", "reference", "paratext"]);
    expect(localStorage.getItem(KEY)).not.toContain("languageQa");
  });

  it("the column's open state is remembered in localStorage, like the other panels", async () => {
    const { toggleSidePanel } = await freshPrefs();
    toggleSidePanel("source");
    expect(JSON.parse(localStorage.getItem(KEY) ?? "{}").source.open).toBe(true);
    const again = await freshPrefs();
    expect(get(again.sidePanels).source.open).toBe(true);
  });

  it("a layout that is broken in another way still falls back to the defaults", async () => {
    localStorage.setItem(KEY, JSON.stringify({ reference: { open: "yes", width: 300 } }));
    const { sidePanels, SIDE_PANEL_LIMITS } = await freshPrefs();
    expect(get(sidePanels).reference.width).toBe(SIDE_PANEL_LIMITS.reference.initial);
    expect(get(sidePanels).source.open).toBe(false);
  });
});
