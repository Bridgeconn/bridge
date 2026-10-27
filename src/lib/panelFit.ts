import { derived, readable, type Readable } from "svelte/store";

import { SIDE_PANEL_LIMITS, SIDE_PANEL_ORDER, sidePanelRecency, sidePanels, textScale } from "./editorPrefs";
import type { SidePanelId, SidePanels } from "./editorPrefs";

/**
 * Which side panels fit beside the verse list at the current window width
 * (#324). The verse list keeps a minimum width that is always on screen; the
 * open side panels shrink first (CSS: each down to its own minimum), and when
 * even their minimums do not fit, the panel opened longest ago is folded back
 * to its rail entry until the rest fit. Folding is visual only: the saved
 * open/width preferences are untouched, so widening the window brings the
 * panel back as it was.
 */

/** The rail at the far right (SideRail.svelte's width plus its border). */
export const RAIL_WIDTH = 35;
/** Each side panel's left border. */
const PANEL_BORDER = 1;
/** The verse list's minimum at normal text size, and how much it grows per
 * unit of `textScale` above 1, so larger text keeps a usable column. */
export const VERSE_MIN_WIDTH = 340;
const VERSE_MIN_PER_SCALE = 200;

/** Never-touched panels fold in this order: the reference Bible first, the
 * review panel (open by default, where findings are acted on) last. */
const DEFAULT_FOLD_ORDER: readonly SidePanelId[] = ["reference", "source", "paratext", "languageQa", "review"];

export function verseMinWidth(scale: number): number {
  return Math.round(VERSE_MIN_WIDTH + VERSE_MIN_PER_SCALE * Math.max(0, scale - 1));
}

/**
 * The open panels that do not fit in `width` px beside a verse list of
 * `verseMin` px and the rail. `recency` lists panels most recently opened
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
    verseMin + RAIL_WIDTH + ids.reduce((sum, id) => sum + SIDE_PANEL_LIMITS[id].min + PANEL_BORDER, 0);
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

export const foldedPanels: Readable<ReadonlySet<SidePanelId>> = derived(
  [windowWidth, sidePanels, sidePanelRecency, verseMin],
  ([width, panels, recency, min]) => new Set(foldedSidePanels(width, panels, recency, min)),
);
