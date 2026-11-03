import { describe, expect, it } from "vitest";
import { arrange, defaultLayout, dockPane, leaves, resizeDivider, validLayout, without } from "../alignmentLayout";

describe("alignment docking", () => {
  it.each(["left", "right", "top", "bottom"] as const)("docks source at the %s of target and preserves read", edge => {
    const tree = dockPane(defaultLayout().tree, "source", "target", edge);
    expect(leaves(tree).sort()).toEqual(["read", "source", "target"]);
    const { source: a, target: b, read } = arrange(tree).frames;
    expect(read!.width).toBe(100);
    if (edge === "left" || edge === "right") {
      expect(a!.y).toBe(b!.y); expect(a!.width + b!.width).toBe(100);
      expect(edge === "left" ? a!.x + a!.width === b!.x : b!.x + b!.width === a!.x).toBe(true);
    } else {
      expect(a!.width).toBe(100); expect(b!.width).toBe(100);
      expect(edge === "top" ? a!.y + a!.height === b!.y : b!.y + b!.height === a!.y).toBe(true);
    }
  });
  it("fills the vacated space while a pane floats and restores its split when docked", () => {
    const state = defaultLayout();
    expect(arrange(without(state.tree, ["read", "source"])).frames.target).toEqual({ x: 0, y: 0, width: 100, height: 100, unit: "%" });
    expect(arrange(without(state.tree, ["read", "source", "target"])).dividers).toEqual([]);
    const tree = dockPane(state.tree, "read", "target", "left");
    expect(arrange(tree).frames.read!.width).toBe(50);
    expect(arrange(tree).frames.target!.width).toBe(50);
  });
  it("resizes a nested split without changing its parent or other panes", () => {
    const state = defaultLayout(), tree = dockPane(state.tree, "source", "target", "left");
    const split = arrange(tree).dividers.find(d => d.axis === "horizontal")!;
    const result = arrange(resizeDivider(tree, split.id, .7));
    expect(result.frames.source!.width).toBe(70);
    expect(result.frames.target!.width).toBe(30);
    expect(result.frames.read).toEqual(arrange(tree).frames.read);
  });
  it("rejects duplicate panes and malformed persisted geometry", () => {
    const state = defaultLayout(); expect(validLayout(JSON.parse(JSON.stringify(state)))).toBe(true);
    expect(validLayout({ ...state, tree: { id: "bad", axis: "vertical", ratio: .5, first: "read", second: "read" } })).toBe(false);
    expect(validLayout({ ...state, floating: ["unknown"] })).toBe(false);
    expect(validLayout({ ...state, positions: { read: { x: 0, y: 0, width: -1, height: 4 } } })).toBe(false);
  });
});
