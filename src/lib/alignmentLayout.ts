import type { Readable, Writable } from "svelte/store";

export const paneIds = ["read", "source", "target"] as const;
export type PaneId = typeof paneIds[number];
export type DockEdge = "left" | "right" | "top" | "bottom";
export type LayoutNode = string | { id: string; axis: "horizontal" | "vertical"; ratio: number; first: LayoutNode; second: LayoutNode };
export interface Rect { x: number; y: number; width: number; height: number }
/** A percentage or px box: what `arrange` yields (the editor's docking
 * still lays its panels out from it). */
export interface Frame extends Rect { unit: "%" | "px" }
/** Where an alignment pane sits (#485): docked in the grid by its area name,
 * or floating over the stage with its own box in px. */
export type PaneFrame = { docked: true } | ({ docked: false } & Rect);
export interface PaneLayout { tree: LayoutNode; floating: PaneId[]; positions: Partial<Record<PaneId, Rect>> }
export interface Divider { id: string; axis: "horizontal" | "vertical"; ratio: number; bounds: Rect; at: number }
/** A width divider as a grid item: the column line it sits on and the rows it spans (1-based grid lines). */
export interface GridDivider extends Divider { column: number; rowStart: number; rowEnd: number }
export interface GridLayout { areas: string[][]; columns: number[]; dividers: GridDivider[] }
export interface AlignmentLayoutContext {
  layout: Writable<PaneLayout>; frames: Readable<Partial<Record<PaneId, PaneFrame>>>;
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
/** The tree as percentage frames of a fixed box. Kept for the width maths:
 * a horizontal split's `at` and `bounds.x/width` are what the divider drag
 * reads, and they do not depend on any height. */
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
/**
 * #485: the docked tree as a CSS grid whose rows fit their content. A
 * side-by-side split keeps its ratio as column widths; a stacked split is
 * two rows of `auto` height, its ratio kept in the saved layout but unused.
 * With three leaves the grid is at most 2x2 (or 1x3 / 3x1), so a leaf on one
 * side of a split spans the rows or columns the other side needs.
 */
export function gridFor(tree: LayoutNode | null): GridLayout {
  type Cell = { areas: string[][]; weights: number[] };
  const build = (node: LayoutNode): Cell => {
    if (typeof node === "string") return { areas: [[node]], weights: [1] };
    const a = build(node.first), b = build(node.second);
    if (node.axis === "horizontal") {
      const rows = Math.max(a.areas.length, b.areas.length);
      const stretch = (cell: Cell) => Array.from({ length: rows }, (_, i) => cell.areas[Math.floor(i * cell.areas.length / rows)]);
      const ra = stretch(a), rb = stretch(b);
      return { areas: ra.map((row, i) => [...row, ...rb[i]]),
        weights: [...a.weights.map((w) => w * node.ratio), ...b.weights.map((w) => w * (1 - node.ratio))] };
    }
    const cols = Math.max(a.weights.length, b.weights.length);
    const widen = (cell: Cell) => cell.areas.map((row) => Array.from({ length: cols }, (_, i) => row[Math.floor(i * row.length / cols)]));
    return { areas: [...widen(a), ...widen(b)], weights: a.weights.length >= b.weights.length ? a.weights : b.weights };
  };
  if (!tree) return { areas: [], columns: [], dividers: [] };
  const { areas, weights } = build(tree);
  const total = weights.reduce((s, w) => s + w, 0) || 1;
  const columns = weights.map((w) => Math.round(w / total * 1000) / 10);
  const dividers: GridDivider[] = arrange(tree).dividers.filter((d) => d.axis === "horizontal").map((d) => {
    const node = findNode(tree, d.id)!;
    const left = new Set(leaves(node.first)), all = new Set(leaves(node));
    let column = 0;
    areas.forEach((row) => row.forEach((area, i) => { if (left.has(area)) column = Math.max(column, i + 1); }));
    const rows = areas.map((row, i) => row.some((area) => all.has(area)) ? i : -1).filter((i) => i >= 0);
    return { ...d, column: column + 1, rowStart: rows[0] + 1, rowEnd: rows[rows.length - 1] + 2 };
  });
  return { areas, columns, dividers };
}
function findNode(tree: LayoutNode, id: string): Exclude<LayoutNode, string> | null {
  if (typeof tree === "string") return null;
  return tree.id === id ? tree : findNode(tree.first, id) || findNode(tree.second, id);
}
/** `grid-template-areas` text for `gridFor(...).areas`. */
export function gridAreasText(areas: string[][]): string { return areas.map((row) => `"${row.join(" ")}"`).join(" "); }
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
/**
 * #485: how far a scrolling dialog moves per frame while a word is dragged
 * near its top or bottom edge (the areas no longer scroll inside, so a long
 * verse's bank can sit below the fold). Zero away from the edges; up to
 * `max` px at the edge, growing linearly across the `edge` band.
 */
export function edgeScrollStep(pointerY: number, top: number, bottom: number, edge = 40, max = 12): number {
  if (bottom - top <= edge * 2) return 0;
  if (pointerY < top + edge) return -Math.ceil(max * Math.min(1, (top + edge - pointerY) / edge));
  if (pointerY > bottom - edge) return Math.ceil(max * Math.min(1, (pointerY - (bottom - edge)) / edge));
  return 0;
}
