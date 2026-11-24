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
    expect(SIDE_PANEL_ORDER).toEqual(["source", "reference", "reference2", "reference3", "reference4", "paratext", "review"]);
    // #519: the added reference tabs did not exist when this was saved; they come in closed, last in the order.
    expect(Object.keys(get(sidePanels)).sort()).toEqual(["paratext", "reference", "reference2", "reference3", "reference4", "review", "source"]);
    expect(get(sidePanels).source).toEqual({ open: true, width: 333 });
    expect(get(sidePanelOrder)).toEqual(["review", "source", "reference", "paratext", "reference2", "reference3", "reference4"]);
    expect(localStorage.getItem(KEY)).not.toContain("languageQa");
  });

  // #519: up to three reference tabs a reviewer adds, each with its own folder.
  it("a layout saved before the added reference tabs gains them closed, and one saved with a folder keeps it", async () => {
    localStorage.setItem(KEY, JSON.stringify({
      source: { open: false, width: 320 }, reference: { open: true, width: 360 },
      paratext: { open: false, width: 340 }, review: { open: true, width: 420 },
    }));
    const first = await freshPrefs();
    expect(get(first.sidePanels).reference).toEqual({ open: true, width: 360 });
    for (const id of first.REFERENCE_EXTRA_IDS) {
      expect(get(first.sidePanels)[id], id).toEqual({ open: false, width: first.SIDE_PANEL_LIMITS.reference.initial });
    }
    first.setSidePanel("reference2", { open: true, folder: "D:/bibles/esv" });
    const again = await freshPrefs();
    expect(get(again.sidePanels).reference2).toMatchObject({ open: true, folder: "D:/bibles/esv" });
    // Reset layout closes the tab; the reference stays in the rail's list.
    again.resetPanelLayout();
    expect(get(again.sidePanels).reference2).toEqual({ open: false, width: again.SIDE_PANEL_LIMITS.reference2.initial, folder: "D:/bibles/esv" });
    // A folder that is not text is not a layout this version wrote: the defaults.
    localStorage.setItem(KEY, JSON.stringify({ ...get(again.sidePanels), reference3: { open: false, width: 300, folder: 7 } }));
    expect(get((await freshPrefs()).sidePanels).reference2.folder).toBeUndefined();
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
