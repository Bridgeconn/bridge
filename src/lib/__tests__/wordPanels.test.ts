import { beforeEach, describe, expect, it } from "vitest";
import { get } from "svelte/store";
import { leaves } from "../alignmentLayout";
import {
  WORD_PANEL_PRESETS, WORD_PANEL_SCALES, applyWordPanelPreset, bumpWordPanelScale, dockWordPanel, panelGrid as gridFor, resetWordPanels, resizeWordPanels,
  wordPanelPreset, wordPanelScales, wordPanelTree,
} from "../wordPanels";

// 2026-11-16 (Joel): the Word alignment tab's three panels.
describe("word alignment panels", () => {
  beforeEach(resetWordPanels);

  it("starts with the verse across the top and source and target side by side", () => {
    expect(gridFor(get(wordPanelTree)).areas).toEqual([["read", "read"], ["source", "target"]]);
    expect(wordPanelPreset(get(wordPanelTree))).toBe("top1bottom2");
  });

  it("applies each preset with all three panels, in the order they were in", () => {
    for (const preset of WORD_PANEL_PRESETS) {
      applyWordPanelPreset(preset.id);
      expect(leaves(get(wordPanelTree))).toEqual(["read", "source", "target"]);
      expect(wordPanelPreset(get(wordPanelTree))).toBe(preset.id);
    }
    applyWordPanelPreset("rows3");
    expect(gridFor(get(wordPanelTree)).areas).toEqual([["read"], ["source"], ["target"]]);
    applyWordPanelPreset("nope");
    expect(wordPanelPreset(get(wordPanelTree))).toBe("rows3");
  });

  it("moves a panel to a side of another and keeps all three", () => {
    dockWordPanel("target", "source", "left");
    expect(gridFor(get(wordPanelTree)).areas).toEqual([["read", "read"], ["target", "source"]]);
    dockWordPanel("read", "read", "left");
    expect(leaves(get(wordPanelTree)).sort()).toEqual(["read", "source", "target"]);
    // A later preset keeps the order the reviewer made.
    applyWordPanelPreset("columns3");
    expect(leaves(get(wordPanelTree))).toEqual(["read", "target", "source"]);
  });

  it("resizes side-by-side panels within limits", () => {
    const split = (get(wordPanelTree) as unknown as { second: { id: string } }).second.id;
    resizeWordPanels(split, 0.7);
    expect(gridFor(get(wordPanelTree)).columns).toEqual([70, 30]);
    resizeWordPanels(split, 0.99);
    expect(gridFor(get(wordPanelTree)).columns).toEqual([85, 15]);
  });

  // The panels fill the tab: a row holding only the verse fits its text,
  // the other rows share the rest, and every shared edge has a line to drag.
  it("shares the height: the verse row fits its text, the others split the rest", () => {
    expect(gridFor(get(wordPanelTree)).rows).toEqual(["auto", 100]);
    expect(gridFor(get(wordPanelTree)).dividers.map((d) => d.resizes)).toEqual(["width"]);
    applyWordPanelPreset("rows3");
    const stacked = gridFor(get(wordPanelTree));
    expect(stacked.rows).toEqual(["auto", 50, 50]);
    expect(stacked.dividers).toHaveLength(1);
    expect(stacked.dividers[0]).toMatchObject({ resizes: "height", line: 3, from: 1, to: 2, panels: ["source", "target"] });
    resizeWordPanels(stacked.dividers[0].id, 0.7);
    expect(gridFor(get(wordPanelTree)).rows).toEqual(["auto", 70, 30]);
    // The verse beside another panel is a full-height panel like the rest.
    applyWordPanelPreset("left1right2");
    const beside = gridFor(get(wordPanelTree));
    expect(beside.areas).toEqual([["read", "source"], ["read", "target"]]);
    expect(beside.rows).toEqual([50, 50]);
    expect(beside.dividers.map((d) => d.resizes).sort()).toEqual(["height", "width"]);
    applyWordPanelPreset("top2bottom1");
    expect(gridFor(get(wordPanelTree)).rows).toEqual([50, 50]);
    expect(gridFor(get(wordPanelTree)).dividers.map((d) => d.resizes).sort()).toEqual(["height", "width"]);
  });

  it("steps one panel's text size and stops at the ends", () => {
    bumpWordPanelScale("source", 1);
    expect(get(wordPanelScales)).toEqual({ read: 1, source: 1.15, target: 1 });
    for (let i = 0; i < 10; i += 1) bumpWordPanelScale("source", 1);
    expect(get(wordPanelScales).source).toBe(WORD_PANEL_SCALES[WORD_PANEL_SCALES.length - 1]);
    for (let i = 0; i < 10; i += 1) bumpWordPanelScale("read", -1);
    expect(get(wordPanelScales).read).toBe(WORD_PANEL_SCALES[0]);
  });

  it("is saved for this device", () => {
    applyWordPanelPreset("columns3");
    bumpWordPanelScale("target", 1);
    const saved = JSON.parse(localStorage.getItem("bridge.alignment.wordPanels.v1") || "null");
    expect(saved.scales.target).toBe(1.15);
    expect(leaves(saved.tree)).toEqual(["read", "source", "target"]);
  });
});
