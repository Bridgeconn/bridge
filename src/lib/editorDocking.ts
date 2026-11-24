import { writable, type Readable } from "svelte/store";
import { leaves, type Frame, type LayoutNode } from "./alignmentLayout";
import type { SidePanelId } from "./editorPrefs";
export const editorTree = writable<LayoutNode | null>(null);
/** The panes the older arrangement (`tree` in a project's saved workspace)
 * placed. A fixed list: that arrangement is only read back from a save, so it
 * does not learn the panels added since (the added reference tabs, #519), and
 * a workspace saved before them stays valid. */
const TREE_PANES: readonly string[] = ["editor", "source", "reference", "paratext", "review"];
export function validEditorTree(value: unknown): value is LayoutNode | null {
  if (value === null) return true;
  const seen = new Set<string>();
  const valid = (node: any, depth = 0): boolean => depth < 12 && (typeof node === "string"
    ? TREE_PANES.includes(node)
    : !!node && typeof node.id === "string" && !seen.has(node.id) && !!seen.add(node.id)
      && ["horizontal", "vertical"].includes(node.axis) && Number.isFinite(node.ratio) && node.ratio >= .15 && node.ratio <= .85
      && valid(node.first, depth + 1) && valid(node.second, depth + 1));
  return valid(value) && leaves(value as LayoutNode).sort().join() === [...TREE_PANES].sort().join();
}
export function defaultEditorTree(): LayoutNode {
  let tree: LayoutNode = "editor";
  for (const id of TREE_PANES.slice(1)) tree = { id: `editor-${id}`, axis: "horizontal", ratio: .65, first: tree, second: id };
  return tree;
}
export interface EditorDockContext {
  frames: Readable<Partial<Record<string, Frame>>>;
  beginMove: (id: SidePanelId | "editor" | "alignment" | "crossVerse", event: PointerEvent) => void;
  cancelMove: () => boolean;
}
