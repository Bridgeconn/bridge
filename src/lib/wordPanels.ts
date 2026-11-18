// The three panels of an alignment tab (2026-11-16, Joel): the verse text to
// read, the source words and the target words. They are always all shown;
// what a reviewer chooses is how they are split (a preset from the bar's
// layout picker, or a panel dragged by its title row to a side of another),
// their share of the width and height, and each panel's text size. Kept per
// device. The panels fill the tab (`panelGrid`); a panel with more words than
// room scrolls inside itself. A word box never does.
// Two tabs use this, each with its own saved layout: Word alignment
// (`wordPanelLayout`) and Cross-verse (`crossPanelLayout`).
import { get, writable, type Writable } from "svelte/store";
import { dockPane, leaves, resizeDivider, type DockEdge, type LayoutNode } from "./alignmentLayout";
import { across, down, presetOf, shapeTree, type LayoutPreset, type LayoutShape } from "./layoutShapes";

export const WORD_PANELS = ["read", "source", "target"] as const;
export type WordPanelId = typeof WORD_PANELS[number];
export const WORD_PANEL_TITLES: Readonly<Record<WordPanelId, string>> = { read: "Verse", source: "Source words", target: "Target words" };

export const WORD_PANEL_PRESETS: readonly LayoutPreset[] = [
  { id: "top1bottom2", label: "One on top, two below", shape: down(0, across(1, 2)) },
  { id: "rows3", label: "Three rows", shape: down(0, down(1, 2)) },
  { id: "top2bottom1", label: "Two on top, one below", shape: down(across(0, 1), 2) },
  { id: "left1right2", label: "One on the left, two on the right", shape: across(0, down(1, 2)) },
  { id: "left2right1", label: "Two on the left, one on the right", shape: across(down(0, 1), 2) },
  { id: "columns3", label: "Three columns", shape: across(0, across(1, 2), 1 / 3) },
];

export const WORD_PANEL_SCALES = [0.85, 1, 1.15, 1.3, 1.5] as const;
export type WordPanelScales = Record<WordPanelId, number>;
const defaultScales = (): WordPanelScales => ({ read: 1, source: 1, target: 1 });

function validTree(value: unknown): value is LayoutNode {
  const node = (n: unknown, depth = 0): boolean => depth < 4 && (typeof n === "string" ? (WORD_PANELS as readonly string[]).includes(n)
    : Boolean(n) && typeof (n as { id: unknown }).id === "string" && ["horizontal", "vertical"].includes((n as { axis: string }).axis)
      && Number.isFinite((n as { ratio: number }).ratio) && (n as { ratio: number }).ratio >= 0.15 && (n as { ratio: number }).ratio <= 0.85
      && node((n as { first: unknown }).first, depth + 1) && node((n as { second: unknown }).second, depth + 1));
  return node(value) && leaves(value as LayoutNode).sort().join() === [...WORD_PANELS].sort().join();
}

/**
 * The panels as a CSS grid that fills the tab (2026-11-16, Joel: the panels
 * share the height and the lines between them drag, both ways, as between
 * tab groups). A split's ratio is its two sides' share of the width (side by
 * side) or of the height (stacked). One exception, when `fitRead` is set: a
 * row that holds only the verse to read is as tall as its text (`auto`), and
 * the other rows share what is left. With three leaves the grid is at most
 * 2 x 2 (or 1 x 3, 3 x 1), so a leaf on one side of a split spans what the
 * other side needs.
 */
export interface PanelDivider {
  id: string; ratio: number;
  /** "width": between two columns; "height": between two rows. */
  resizes: "width" | "height";
  /** The grid line it sits on, and the lines it spans across (1-based). */
  line: number; from: number; to: number;
  /** The panels of the split: its two sides together are what the ratio divides. */
  panels: string[];
}
export interface PanelGrid { areas: string[][]; columns: number[]; rows: (number | "auto")[]; dividers: PanelDivider[] }

export function panelGrid(tree: LayoutNode, fitRead = true): PanelGrid {
  type Cell = { areas: string[][]; widths: number[]; heights: number[] };
  const build = (node: LayoutNode): Cell => {
    if (typeof node === "string") return { areas: [[node]], widths: [1], heights: [1] };
    const a = build(node.first), b = build(node.second);
    if (node.axis === "horizontal") {
      const rows = Math.max(a.areas.length, b.areas.length);
      const stretch = (cell: Cell) => Array.from({ length: rows }, (_, i) => cell.areas[Math.floor(i * cell.areas.length / rows)]);
      const ra = stretch(a), rb = stretch(b);
      return { areas: ra.map((row, i) => [...row, ...rb[i]]),
        widths: [...a.widths.map((w) => w * node.ratio), ...b.widths.map((w) => w * (1 - node.ratio))],
        heights: a.heights.length >= b.heights.length ? a.heights : b.heights };
    }
    const cols = Math.max(a.widths.length, b.widths.length);
    const widen = (cell: Cell) => cell.areas.map((row) => Array.from({ length: cols }, (_, i) => row[Math.floor(i * row.length / cols)]));
    return { areas: [...widen(a), ...widen(b)], widths: a.widths.length >= b.widths.length ? a.widths : b.widths,
      heights: [...a.heights.map((h) => h * node.ratio), ...b.heights.map((h) => h * (1 - node.ratio))] };
  };
  const { areas, widths, heights } = build(tree);
  const share = (values: number[], keep: (i: number) => boolean): number[] => {
    const total = values.reduce((sum, v, i) => sum + (keep(i) ? v : 0), 0) || 1;
    return values.map((v) => Math.round(v / total * 1000) / 10);
  };
  const autoRow = (i: number): boolean => fitRead && areas.length > 1 && areas[i].every((area) => area === "read");
  const shares = share(heights, (i) => !autoRow(i));
  const rows = heights.map((_, i) => (autoRow(i) ? "auto" as const : shares[i]));
  const rowsOf = (ids: Set<string>): number[] => areas.map((row, i) => (row.some((area) => ids.has(area)) ? i : -1)).filter((i) => i >= 0);
  const colsOf = (ids: Set<string>): number[] => {
    const found = new Set<number>();
    areas.forEach((row) => row.forEach((area, i) => { if (ids.has(area)) found.add(i); }));
    return [...found].sort((x, y) => x - y);
  };
  const dividers: PanelDivider[] = [];
  const visit = (node: LayoutNode): void => {
    if (typeof node === "string") return;
    const first = new Set(leaves(node.first)), second = new Set(leaves(node.second)), all = new Set([...first, ...second]);
    if (node.axis === "horizontal") {
      const span = rowsOf(all);
      dividers.push({ id: node.id, ratio: node.ratio, resizes: "width", line: Math.max(...colsOf(first)) + 2, from: span[0] + 1, to: span[span.length - 1] + 2, panels: [...all] });
    } else if (!rowsOf(first).every(autoRow) && !rowsOf(second).every(autoRow)) {
      // A row as tall as its text has nothing to drag.
      const span = colsOf(all);
      dividers.push({ id: node.id, ratio: node.ratio, resizes: "height", line: Math.max(...rowsOf(first)) + 2, from: span[0] + 1, to: span[span.length - 1] + 2, panels: [...all] });
    }
    visit(node.first); visit(node.second);
  };
  visit(tree);
  return { areas, columns: share(widths, () => true), rows, dividers };
}

/** One tab's three panels: where they are, their text sizes, and the moves. */
export interface PanelLayout {
  titles: Readonly<Record<WordPanelId, string>>;
  /** The verse panel's row fits its text when it has a row to itself. */
  fitRead: boolean;
  tree: Writable<LayoutNode>;
  scales: Writable<WordPanelScales>;
  /** The preset the panels are split as now, if it is one of them. */
  preset(tree: LayoutNode): string | null;
  /** Split the panels as the preset `id`; they keep their reading order. */
  applyPreset(id: string): void;
  /** Back to the first layout and the standard text sizes. */
  reset(): void;
  /** Move `id` to `edge` of `target` (a title row dragged onto another panel). */
  dock(id: WordPanelId, target: WordPanelId, edge: DockEdge): void;
  resize(dividerId: string, ratio: number): void;
  /** One step smaller or larger; nothing at either end. */
  bumpScale(id: WordPanelId, delta: -1 | 1): void;
}

export function createPanelLayout(options: { storageKey: string; titles: Readonly<Record<WordPanelId, string>>; fitRead: boolean; first: LayoutShape }): PanelLayout {
  const firstTree = (): LayoutNode => shapeTree(options.first, WORD_PANELS, "panels-default");
  let saved: { tree?: unknown; scales?: Partial<Record<WordPanelId, unknown>> } | null = null;
  try { saved = JSON.parse(localStorage.getItem(options.storageKey) || "null"); } catch { saved = null; }
  const startScales = defaultScales();
  for (const id of WORD_PANELS) if ((WORD_PANEL_SCALES as readonly number[]).includes(saved?.scales?.[id] as number)) startScales[id] = saved!.scales![id] as number;
  const tree = writable<LayoutNode>(validTree(saved?.tree) ? saved!.tree as LayoutNode : firstTree());
  const scales = writable<WordPanelScales>(startScales);
  const save = (): void => {
    try { localStorage.setItem(options.storageKey, JSON.stringify({ tree: get(tree), scales: get(scales) })); } catch { /* this session only */ }
  };
  tree.subscribe(save);
  scales.subscribe(save);
  return {
    titles: options.titles, fitRead: options.fitRead, tree, scales,
    preset: (value) => presetOf(value, WORD_PANEL_PRESETS),
    applyPreset(id) {
      const preset = WORD_PANEL_PRESETS.find((candidate) => candidate.id === id);
      if (preset) tree.update((value) => shapeTree(preset.shape, leaves(value), `panels-${id}`));
    },
    reset() { tree.set(firstTree()); scales.set(defaultScales()); },
    dock(id, target, edge) { if (id !== target) tree.update((value) => dockPane(value, id, target, edge)); },
    resize(dividerId, ratio) { tree.update((value) => resizeDivider(value, dividerId, ratio)); },
    bumpScale(id, delta) {
      scales.update((value) => {
        const at = WORD_PANEL_SCALES.indexOf(value[id] as typeof WORD_PANEL_SCALES[number]);
        const next = WORD_PANEL_SCALES[Math.max(0, Math.min(WORD_PANEL_SCALES.length - 1, (at < 0 ? 1 : at) + delta))];
        return next === value[id] ? value : { ...value, [id]: next };
      });
    },
  };
}

/** Word alignment: one verse. The verse across the top, as tall as its text;
 *  source and target words side by side below. */
export const wordPanelLayout = createPanelLayout({
  storageKey: "bridge.alignment.wordPanels.v1", titles: WORD_PANEL_TITLES, fitRead: true, first: WORD_PANEL_PRESETS[0].shape,
});

/** Cross-verse: a range of verses. The verses to read take a quarter of the
 *  height (they are many, so that panel scrolls like the others); source and
 *  target words side by side below. */
export const CROSS_PANEL_TITLES: Readonly<Record<WordPanelId, string>> = { read: "Verses", source: "Source words", target: "Target words" };
export const crossPanelLayout = createPanelLayout({
  storageKey: "bridge.alignment.crossPanels.v1", titles: CROSS_PANEL_TITLES, fitRead: false, first: down(0, across(1, 2), 0.25),
});

// The Word alignment tab's layout by name, as it was before the Cross-verse tab shared the module.
export const wordPanelTree = wordPanelLayout.tree;
export const wordPanelScales = wordPanelLayout.scales;
export const wordPanelPreset = wordPanelLayout.preset;
export const applyWordPanelPreset = wordPanelLayout.applyPreset;
export const resetWordPanels = wordPanelLayout.reset;
export const dockWordPanel = wordPanelLayout.dock;
export const resizeWordPanels = wordPanelLayout.resize;
export const bumpWordPanelScale = wordPanelLayout.bumpScale;
