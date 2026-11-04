import { writable, type Readable } from "svelte/store";
import { leaves, type Frame, type LayoutNode, type DockEdge } from "./alignmentLayout";
import { SIDE_PANEL_ORDER, type SidePanelId } from "./editorPrefs";
export const editorTree = writable<LayoutNode | null>(null);
export function validEditorTree(value: unknown): value is LayoutNode | null {
  if (value === null) return true;
  const seen = new Set<string>();
  const valid = (node: any, depth = 0): boolean => depth < 12 && (typeof node === "string"
    ? ["editor", ...SIDE_PANEL_ORDER].includes(node)
    : !!node && typeof node.id === "string" && !seen.has(node.id) && !!seen.add(node.id)
      && ["horizontal", "vertical"].includes(node.axis) && Number.isFinite(node.ratio) && node.ratio >= .15 && node.ratio <= .85
      && valid(node.first, depth + 1) && valid(node.second, depth + 1));
  return valid(value) && leaves(value as LayoutNode).sort().join() === ["editor", ...SIDE_PANEL_ORDER].sort().join();
}
export function defaultEditorTree(): LayoutNode {
  let tree: LayoutNode = "editor";
  for (const id of SIDE_PANEL_ORDER) tree = { id: `editor-${id}`, axis: "horizontal", ratio: .65, first: tree, second: id };
  return tree;
}
export interface EditorDockContext {
  frames: Readable<Partial<Record<string, Frame>>>;
  beginMove: (id: SidePanelId, event: PointerEvent) => void;
  dock: (id: SidePanelId, target: string, edge: DockEdge) => void;
  cancelMove: () => boolean;
}
