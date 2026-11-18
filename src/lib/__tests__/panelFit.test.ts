import { afterEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";
import { get } from "svelte/store";
import { tick } from "svelte";

import SidePanel from "../components/SidePanel.svelte";
import { SIDE_PANEL_LIMITS, setSidePanel, sidePanelRecency, sidePanels, toggleSidePanel } from "../editorPrefs";
import type { SidePanels } from "../editorPrefs";
import { VERSE_MIN_WIDTH, foldedPanels, foldedSidePanels, verseMinWidth } from "../panelFit";

function layout(open: Partial<Record<keyof SidePanels, boolean>>): SidePanels {
  return {
    source: { open: !!open.source, width: 320 },
    reference: { open: !!open.reference, width: 300 },
    paratext: { open: !!open.paratext, width: 340 },
    review: { open: !!open.review, width: 400 },
  };
}

/** The width the verse list and these panels at their minimums take (no rail since #488). */
const needed = (ids: (keyof SidePanels)[], verse = VERSE_MIN_WIDTH): number =>
  verse + ids.reduce((sum, id) => sum + SIDE_PANEL_LIMITS[id].min + 1, 0);

function setWindowWidth(px: number): void {
  Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: px });
  window.dispatchEvent(new Event("resize"));
}

describe("foldedSidePanels (#324)", () => {
  const three = layout({ source: true, reference: true, review: true });

  // #389: an undocked box takes no column, so it neither folds nor crowds the others.
  it("ignores an undocked panel", () => {
    const floating = layout({ source: true, reference: true, review: true });
    floating.reference.float = { x: 10, y: 10, width: 300, height: 400 };
    expect(foldedSidePanels(needed(["source", "review"]), floating, [], VERSE_MIN_WIDTH)).toEqual([]);
    expect(foldedSidePanels(needed(["source", "reference", "review"]) - 1, three, [], VERSE_MIN_WIDTH)).toEqual(["reference"]);
  });

  it("folds nothing while the verse list and every open panel's minimum fit", () => {
    expect(foldedSidePanels(1366, three, [], VERSE_MIN_WIDTH)).toEqual([]);
    expect(foldedSidePanels(needed(["source", "reference", "review"]), three, [], VERSE_MIN_WIDTH)).toEqual([]);
  });

  it("folds Reference, then Source, before the Review panel at narrow widths", () => {
    // 984 px (a 1000x680 window) and 911 px (1366x768 at 150%): Reference goes.
    expect(foldedSidePanels(984, three, [], VERSE_MIN_WIDTH)).toEqual(["reference"]);
    expect(foldedSidePanels(911, three, [], VERSE_MIN_WIDTH)).toEqual(["reference"]);
    // 900 px with the default panels (Review only): nothing to fold.
    expect(foldedSidePanels(900, layout({ review: true }), [], VERSE_MIN_WIDTH)).toEqual([]);
    expect(foldedSidePanels(800, three, [], VERSE_MIN_WIDTH)).toEqual(["reference", "source"]);
    // Narrower than the verse list and one panel: everything folds, the text stays.
    expect(foldedSidePanels(600, three, [], VERSE_MIN_WIDTH)).toEqual(["reference", "source", "review"]);
  });

  it("keeps the most recently opened panel, folding older ones first", () => {
    expect(foldedSidePanels(984, three, ["reference"], VERSE_MIN_WIDTH)).toEqual(["source"]);
    expect(foldedSidePanels(800, three, ["review", "reference"], VERSE_MIN_WIDTH)).toEqual(["source", "review"]);
  });

  it("never folds a closed panel, and keeps a wider verse list for larger text", () => {
    expect(foldedSidePanels(400, layout({}), [], VERSE_MIN_WIDTH)).toEqual([]);
    expect(verseMinWidth(1)).toBe(VERSE_MIN_WIDTH);
    expect(verseMinWidth(0.85)).toBe(VERSE_MIN_WIDTH);
    expect(verseMinWidth(1.5)).toBe(VERSE_MIN_WIDTH + 100);
    // At 911 px, Review still fits beside the largest text.
    expect(foldedSidePanels(911, layout({ review: true }), [], verseMinWidth(1.7))).toEqual([]);
  });
});
