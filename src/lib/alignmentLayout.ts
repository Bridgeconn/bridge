import type { Readable, Writable } from "svelte/store";

export const paneIds = ["read", "source", "target"] as const;
export type PaneId = typeof paneIds[number];
export type DockEdge = "left" | "right" | "top" | "bottom";
export type LayoutNode = string | { id: string; axis: "horizontal" | "vertical"; ratio: number; first: LayoutNode; second: LayoutNode };
export interface Rect { x: number; y: number; width: number; height: number }
export interface Frame extends Rect { unit: "%" | "px" }
export interface PaneLayout { tree: LayoutNode; floating: PaneId[]; positions: Partial<Record<PaneId, Rect>> }
export interface Divider { id: string; axis: "horizontal" | "vertical"; ratio: number; bounds: Rect; at: number }
export interface AlignmentLayoutContext {
  layout: Writable<PaneLayout>; frames: Readable<Partial<Record<PaneId, Frame>>>;
  dock: (id: PaneId, target: PaneId, edge: DockEdge) => void;
  float: (id: PaneId) => void; beginMove: (id: PaneId, event: PointerEvent) => void;
  resize: (id: PaneId, axis: "width" | "height", value: number) => void;
}
export function defaultLayout(kind = "word"): PaneLayout {
  return { tree: { id: "read-body", axis: "vertical", ratio: .22, first: "read",
    second: { id: "source-target", axis: kind === "cross" ? "horizontal" : "vertical", ratio: kind === "cross" ? .5 : .65, first: "source", second: "target" } }, floating: [], positions: {} };
}
export function leaves(tree: LayoutNode): string[] { return typeof tree === "string" ? [tree] : [...leaves(tree.first), ...leaves(tree.second)]; }
export function without(tree: LayoutNode, ids: readonly string[]): LayoutNode | null {
  if (typeof tree === "string") return ids.includes(tree) ? null : tree;
  const first = without(tree.first, ids), second = without(tree.second, ids);
  return first && second ? { ...tree, first, second } : first || second;
}
export function dockPane(tree: LayoutNode, id: string, target: string, edge: DockEdge): LayoutNode {
  if (id === target) return tree;
  const remaining = without(tree, [id])!;
  const insert = (node: LayoutNode): LayoutNode => {
    if (node === target) return { id: `split-${id}-${target}-${Date.now()}`, axis: edge === "left" || edge === "right" ? "horizontal" : "vertical", ratio: .5,
      first: edge === "left" || edge === "top" ? id : target, second: edge === "left" || edge === "top" ? target : id };
    return typeof node === "string" ? node : { ...node, first: insert(node.first), second: insert(node.second) };
  };
  return insert(remaining);
}
export function arrange(tree: LayoutNode | null, bounds: Rect = { x: 0, y: 0, width: 100, height: 100 }) {
  const frames: Partial<Record<string, Frame>> = {}, dividers: Divider[] = [];
  const visit = (node: LayoutNode, rect: Rect) => {
    if (typeof node === "string") { frames[node] = { ...rect, unit: "%" }; return; }
    const horizontal = node.axis === "horizontal", amount = (horizontal ? rect.width : rect.height) * node.ratio;
    dividers.push({ id: node.id, axis: node.axis, ratio: node.ratio, bounds: rect, at: (horizontal ? rect.x : rect.y) + amount });
    visit(node.first, horizontal ? { ...rect, width: amount } : { ...rect, height: amount });
    visit(node.second, horizontal ? { ...rect, x: rect.x + amount, width: rect.width - amount } : { ...rect, y: rect.y + amount, height: rect.height - amount });
  };
  if (tree) visit(tree, bounds);
  return { frames, dividers };
}
export function resizeDivider(tree: LayoutNode, id: string, ratio: number): LayoutNode {
  if (typeof tree === "string") return tree;
  return tree.id === id ? { ...tree, ratio: Math.max(.15, Math.min(.85, ratio)) } :
    { ...tree, first: resizeDivider(tree.first, id, ratio), second: resizeDivider(tree.second, id, ratio) };
}
export function validLayout(value: unknown): value is PaneLayout {
  const node = (v: any, depth = 0): boolean => depth < 4 && (typeof v === "string" ? paneIds.includes(v as PaneId) :
    Boolean(v && typeof v.id === "string" && ["horizontal", "vertical"].includes(v.axis) && Number.isFinite(v.ratio) && v.ratio >= .15 && v.ratio <= .85 && node(v.first, depth + 1) && node(v.second, depth + 1)));
  const v = value as PaneLayout;
  return Boolean(v && node(v.tree) && leaves(v.tree).sort().join() === [...paneIds].sort().join() && Array.isArray(v.floating) &&
    new Set(v.floating).size === v.floating.length && v.floating.every(id => paneIds.includes(id)) && v.positions &&
    Object.values(v.positions).every(p => p && [p.x, p.y, p.width, p.height].every(Number.isFinite) && p.width > 0 && p.height > 0));
}
