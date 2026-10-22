import { afterEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";
import { get } from "svelte/store";
import { tick } from "svelte";

import SidePanel from "../components/SidePanel.svelte";
import SideRail from "../components/SideRail.svelte";
import { SIDE_PANEL_LIMITS, setSidePanel, sidePanelRecency, sidePanels, toggleSidePanel } from "../editorPrefs";
import type { SidePanels } from "../editorPrefs";
import { RAIL_WIDTH, VERSE_MIN_WIDTH, foldedPanels, foldedSidePanels, verseMinWidth } from "../panelFit";

function layout(open: Partial<Record<keyof SidePanels, boolean>>): SidePanels {
  return {
    source: { open: !!open.source, width: 320 },
    reference: { open: !!open.reference, width: 300 },
    languageQa: { open: !!open.languageQa, width: 440 },
    review: { open: !!open.review, width: 400 },
  };
}

/** The width the verse list, the rail and these panels at their minimums take. */
const needed = (ids: (keyof SidePanels)[], verse = VERSE_MIN_WIDTH): number =>
  verse + RAIL_WIDTH + ids.reduce((sum, id) => sum + SIDE_PANEL_LIMITS[id].min + 1, 0);

function setWindowWidth(px: number): void {
  Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: px });
  window.dispatchEvent(new Event("resize"));
}

describe("foldedSidePanels (#324)", () => {
  const three = layout({ source: true, reference: true, review: true });

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

describe("folding in the editor (#324)", () => {
  afterEach(() => {
    for (const id of ["source", "reference", "languageQa", "review"] as const) {
      setSidePanel(id, { open: id === "review", width: SIDE_PANEL_LIMITS[id].initial });
    }
    sidePanelRecency.set([]);
    setWindowWidth(1024);
  });

  it("hides a folded panel without touching its saved state, and shows it again when the window widens", async () => {
    setWindowWidth(1600);
    sidePanelRecency.set([]);
    setSidePanel("source", { open: true });
    setSidePanel("reference", { open: true });
    setSidePanel("review", { open: true });
    sidePanelRecency.set([]);
    render(SidePanel, { props: { id: "reference", label: "Reference" } });
    const column = () => document.getElementById("side-panel-reference") as HTMLElement;
    expect(column().hidden).toBe(false);

    setWindowWidth(984);
    await tick();
    expect([...get(foldedPanels)]).toEqual(["reference"]);
    expect(column().hidden).toBe(true);
    expect(get(sidePanels).reference.open).toBe(true);

    setWindowWidth(1366);
    await tick();
    expect(column().hidden).toBe(false);
  });

  it("shows a folded panel's rail entry as not pressed, and a click brings it back instead of closing it", async () => {
    setWindowWidth(984);
    setSidePanel("source", { open: true });
    setSidePanel("reference", { open: true });
    setSidePanel("review", { open: true });
    sidePanelRecency.set([]);
    render(SideRail);
    const reference = screen.getByRole("button", { name: /^Reference/ });
    const source = screen.getByRole("button", { name: /^Source/ });
    expect(reference.getAttribute("aria-pressed")).toBe("false");
    expect(reference.title).toMatch(/too narrow/);
    expect(source.getAttribute("aria-pressed")).toBe("true");

    await fireEvent.click(reference);
    expect(get(sidePanels).reference.open).toBe(true);
    expect(reference.getAttribute("aria-pressed")).toBe("true");
    // Source, now the one opened longest ago, folds in its place.
    expect(source.getAttribute("aria-pressed")).toBe("false");

    // An ordinary open panel still closes from the rail.
    await fireEvent.click(reference);
    expect(get(sidePanels).reference.open).toBe(false);
    expect(source.getAttribute("aria-pressed")).toBe("true");
  });

  it("a panel opened from the rail is the one shown", async () => {
    setWindowWidth(984);
    setSidePanel("source", { open: true });
    setSidePanel("review", { open: true });
    toggleSidePanel("reference");
    expect([...get(foldedPanels)]).toEqual(["source"]);
  });
});
