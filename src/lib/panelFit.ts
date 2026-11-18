import { derived, readable, type Readable } from "svelte/store";

import { SIDE_PANEL_LIMITS, SIDE_PANEL_ORDER, textScale } from "./editorPrefs";
import type { SidePanelId, SidePanels } from "./editorPrefs";
import { tabLayout, visibleTabs } from "./editorTabs";

/**
 * Which side panels fit beside the verse list at the current window width
 * (#324). The verse list keeps a minimum width that is always on screen; the
 * open side panels shrink first (CSS: each down to its own minimum), and when
 * even their minimums do not fit, the panel opened longest ago is folded
 * (the View menu marks it and brings it back) until the rest fit. Folding is visual only: the saved
 * open/width preferences are untouched, so widening the window brings the
 * panel back as it was.
 */

/** Each side panel's left border. */
const PANEL_BORDER = 1;
/** The verse list's minimum at normal text size, and how much it grows per
 * unit of `textScale` above 1, so larger text keeps a usable column. */
export const VERSE_MIN_WIDTH = 340;
const VERSE_MIN_PER_SCALE = 200;

/** Never-touched panels fold in this order: the reference Bible first, the
 * review panel (open by default, where findings are acted on) last. */
const DEFAULT_FOLD_ORDER: readonly SidePanelId[] = ["reference", "source", "paratext", "review"];

export function verseMinWidth(scale: number): number {
  return Math.round(VERSE_MIN_WIDTH + VERSE_MIN_PER_SCALE * Math.max(0, scale - 1));
}

/**
 * The open panels that do not fit in `width` px beside a verse list of
 * `verseMin` px. `recency` lists panels most recently opened
 * last; they are the last to fold. Panels not in it fold first, in the
 * default order.
 */
export function foldedSidePanels(
  width: number,
  panels: SidePanels,
  recency: readonly SidePanelId[],
  verseMin: number,
): SidePanelId[] {
  // An undocked box (#389) takes no column width, so it never folds and
  // never makes another panel fold.
  const open = SIDE_PANEL_ORDER.filter((id) => panels[id].open && !panels[id].float);
  const rank = (id: SidePanelId): number => {
    const at = recency.indexOf(id);
    return at >= 0 ? DEFAULT_FOLD_ORDER.length + at : DEFAULT_FOLD_ORDER.indexOf(id);
  };
  // Fold order: lowest rank first.
  const byFold = [...open].sort((a, b) => rank(a) - rank(b));
  const need = (ids: readonly SidePanelId[]): number =>
    verseMin + ids.reduce((sum, id) => sum + SIDE_PANEL_LIMITS[id].min + PANEL_BORDER, 0);
  const folded: SidePanelId[] = [];
  let kept = byFold;
  while (kept.length && need(kept) > width) {
    folded.push(kept[0]);
    kept = kept.slice(1);
  }
  return folded;
}

/** The window's width, which is the panes row's: nothing sits beside it. */
export const windowWidth: Readable<number> = readable(
  typeof window === "undefined" ? 1366 : window.innerWidth,
  (set) => {
    if (typeof window === "undefined") return undefined;
    const update = (): void => set(window.innerWidth);
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  },
);

export const verseMin: Readable<number> = derived(textScale, (scale) => verseMinWidth(scale));

/** The panels folded for width. Nothing folds since the work area became
 * tab groups (2026-11-14, editorTabs.ts): a group shares the area by its own
 * divider, and a tab behind another takes no room. `foldedSidePanels` above
 * is the old rule, kept with its tests; this store stays for its readers. */
export const foldedPanels: Readable<ReadonlySet<SidePanelId>> = readable(new Set<SidePanelId>());

/** The verse list is on screen: its tab is the one showing in its group. */
export const versesShown: Readable<boolean> = derived(visibleTabs, (tabs) => tabs.has("editor"));

/** Nothing is in the work area: no tab is open. The editor then shows a
 * short message with a way back. */
export const workAreaEmpty: Readable<boolean> = derived(tabLayout, (layout) => Object.keys(layout.groups).length === 0);
