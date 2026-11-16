// Split shapes shared by the two layout pickers (2026-11-16): the editor's
// work area (editorTabs.ts) and the Word alignment tab's three panels
// (wordPanels.ts). A shape's numbers are its places in reading order; a tree
// is the same split with real ids at the leaves (alignmentLayout.ts LayoutNode).
// Pure: no stores, so the separate alignment window can use it too.
import type { LayoutNode } from "./alignmentLayout";

export type LayoutShape = number | { axis: "horizontal" | "vertical"; ratio?: number; first: LayoutShape; second: LayoutShape };
export interface LayoutPreset { id: string; label: string; shape: LayoutShape }

export const across = (first: LayoutShape, second: LayoutShape, ratio = 0.5): LayoutShape => ({ axis: "horizontal", ratio, first, second });
export const down = (first: LayoutShape, second: LayoutShape, ratio = 0.5): LayoutShape => ({ axis: "vertical", ratio, first, second });

export const shapePlaces = (shape: LayoutShape): number => (typeof shape === "number" ? 1 : shapePlaces(shape.first) + shapePlaces(shape.second));
const shapeKey = (shape: LayoutShape): string => (typeof shape === "number" ? "p" : `${shape.axis[0]}(${shapeKey(shape.first)},${shapeKey(shape.second)})`);
const treeKey = (tree: LayoutNode): string => (typeof tree === "string" ? "p" : `${tree.axis[0]}(${treeKey(tree.first)},${treeKey(tree.second)})`);

/** The preset `tree` is split as, if it is one of `presets`. */
export function presetOf(tree: LayoutNode | null, presets: readonly LayoutPreset[]): string | null {
  if (!tree) return null;
  const key = treeKey(tree);
  return presets.find((preset) => shapeKey(preset.shape) === key)?.id ?? null;
}

/** `shape` as a tree: place n is `ids[n]`. `name` goes into the split ids. */
export function shapeTree(shape: LayoutShape, ids: readonly string[], name: string): LayoutNode {
  let splits = 0;
  const stamp = Date.now().toString(36);
  const build = (part: LayoutShape): LayoutNode => (typeof part === "number" ? ids[part]
    : { id: `split-${name}-${(splits += 1)}-${stamp}`, axis: part.axis, ratio: part.ratio ?? 0.5, first: build(part.first), second: build(part.second) });
  return build(shape);
}
