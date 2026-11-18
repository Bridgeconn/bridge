// 2026-11-18: AlignmentWorkspace.svelte and AlignmentPane.svelte, which this
// file also tested, are deleted (no tab used them since 2026-11-16). What is
// left tests the pure helpers in alignmentLayout.ts.
import { describe, expect, it } from "vitest";
import { defaultLayout, dockPane, edgeScrollStep, gridAreasText, gridFor, validLayout } from "../../alignmentLayout";

describe("gridFor (#485): the docked tree as a grid whose rows fit their content", () => {
  it("stacks the word default: three rows, one column, no width divider", () => {
    const grid = gridFor(defaultLayout("word").tree);
    expect(grid.areas).toEqual([["read"], ["source"], ["target"]]);
    expect(grid.columns).toEqual([100]);
    expect(grid.dividers).toEqual([]);
  });

  it("the cross default: Read across the top, Source beside Target below, one divider on the second row", () => {
    const grid = gridFor(defaultLayout("cross").tree);
    expect(grid.areas).toEqual([["read", "read"], ["source", "target"]]);
    expect(grid.columns).toEqual([50, 50]);
    expect(grid.dividers).toHaveLength(1);
    expect(grid.dividers[0]).toMatchObject({ id: "source-target", column: 2, rowStart: 2, rowEnd: 3, ratio: .5 });
    expect(gridAreasText(grid.areas)).toBe('"read read" "source target"');
  });

  it("a leaf beside a stacked pair spans both rows; a nested width ratio multiplies", () => {
    const grid = gridFor(dockPane(defaultLayout("word").tree, "read", "source", "left"));
    // (read | source) / target: the pair shares the top row, Target spans both columns below.
    expect(grid.areas).toEqual([["read", "source"], ["target", "target"]]);
    expect(grid.dividers[0]).toMatchObject({ column: 2, rowStart: 1, rowEnd: 2 });
    const three = gridFor(dockPane(dockPane(defaultLayout("word").tree, "read", "source", "left"), "target", "source", "right"));
    expect(three.areas).toEqual([["read", "source", "target"]]);
    expect(three.columns.reduce((s, w) => s + w, 0)).toBeCloseTo(100);
    expect(three.dividers.map((d) => d.column)).toEqual([2, 3]);
  });

  it("a layout saved by the current build, vertical ratios included, still validates and lays out", () => {
    const saved = JSON.parse(JSON.stringify(defaultLayout("word")));
    saved.tree.ratio = .3; saved.tree.second.ratio = .7;
    expect(validLayout(saved)).toBe(true);
    expect(gridFor(saved.tree).areas).toEqual([["read"], ["source"], ["target"]]);
    expect(validLayout({ ...saved, floating: ["read"], positions: { read: { x: 10, y: 10, width: 300, height: 200 } } })).toBe(true);
  });
});

describe("edgeScrollStep (#485)", () => {
  it("is zero away from the edges, grows towards them, and never fires in a box too short for two bands", () => {
    expect(edgeScrollStep(300, 0, 600)).toBe(0);
    expect(edgeScrollStep(20, 0, 600)).toBe(-6);
    expect(edgeScrollStep(0, 0, 600)).toBe(-12);
    expect(edgeScrollStep(580, 0, 600)).toBe(6);
    expect(edgeScrollStep(600, 0, 600)).toBe(12);
    expect(edgeScrollStep(5, 0, 70)).toBe(0);
  });
});
