/**
 * Keeps the same verse level across the Source and Target columns of the
 * Cross-verse alignment page (#495).
 *
 * The two columns are separate, rearrangeable panes (#448), each a stack of
 * verse blocks whose heights differ, so further down a range verse 7 on one
 * side sat beside verse 15 on the other. Rather than move the blocks into one
 * shared grid (which would end the rearranging), every element marked
 * `data-verse-row="<key>"` is paired with the one sharing its key in the other
 * column (`data-verse-col`), and both get the taller one's height as
 * `min-height`. Equal heights from equal starts keep every later verse level.
 *
 * Only when the two columns stand side by side: stacked or floating panes get
 * no extra space.
 */

const ROW_ATTR = "data-verse-row";
const COL_ATTR = "data-verse-col";

interface Box { left: number; right: number; top: number }

/** Two columns are side by side when they do not overlap horizontally and
 * start at about the same height. */
export function sideBySide(a: Box, b: Box): boolean {
  const apart = a.right <= b.left + 1 || b.right <= a.left + 1;
  return apart && Math.abs(a.top - b.top) <= 4;
}

/** One pass: clear what the last pass set, measure, and level each pair. */
export function levelVerseRows(root: HTMLElement): void {
  const rows = Array.from(root.querySelectorAll<HTMLElement>(`[${ROW_ATTR}]`));
  for (const row of rows) row.style.minHeight = "";
  const byKey = new Map<string, HTMLElement[]>();
  for (const row of rows) {
    const key = row.getAttribute(ROW_ATTR) ?? "";
    byKey.set(key, [...(byKey.get(key) ?? []), row]);
  }
  // Measure everything before writing anything, so one pair's new height
  // cannot disturb another pair's measurement.
  const heights: [HTMLElement, number][] = [];
  for (const pair of byKey.values()) {
    if (pair.length !== 2) continue;
    const [first, second] = pair;
    const colA = first.closest<HTMLElement>(`[${COL_ATTR}]`), colB = second.closest<HTMLElement>(`[${COL_ATTR}]`);
    if (!colA || !colB || colA === colB) continue;
    if (!sideBySide(colA.getBoundingClientRect(), colB.getBoundingClientRect())) continue;
    const a = first.getBoundingClientRect().height, b = second.getBoundingClientRect().height;
    if (Math.abs(a - b) < 0.5) continue;
    heights.push([a < b ? first : second, Math.max(a, b)]);
  }
  for (const [row, height] of heights) row.style.minHeight = `${Math.ceil(height * 100) / 100}px`;
}

/** Svelte action: level the verse rows under `node` now and whenever a row
 * changes size, a row is added or removed, or the columns move. */
export function syncVerseRows(node: HTMLElement): { destroy(): void } {
  if (typeof ResizeObserver === "undefined" || typeof MutationObserver === "undefined") return { destroy() {} };
  let frame = 0;
  let observed = new Set<Element>();
  const resize = new ResizeObserver(() => schedule());
  function run(): void {
    frame = 0;
    const current = new Set<Element>(node.querySelectorAll(`[${ROW_ATTR}], [${COL_ATTR}]`));
    for (const el of observed) if (!current.has(el)) resize.unobserve(el);
    for (const el of current) if (!observed.has(el)) resize.observe(el);
    observed = current;
    levelVerseRows(node);
  }
  function schedule(): void {
    if (!frame) frame = requestAnimationFrame(run);
  }
  // Rows come and go with the range. A pane docked elsewhere resizes its
  // column, which the ResizeObserver sees.
  const mutation = new MutationObserver(() => schedule());
  mutation.observe(node, { childList: true, subtree: true });
  resize.observe(node);
  schedule();
  return {
    destroy() {
      if (frame) cancelAnimationFrame(frame);
      resize.disconnect();
      mutation.disconnect();
      for (const row of node.querySelectorAll<HTMLElement>(`[${ROW_ATTR}]`)) row.style.minHeight = "";
    },
  };
}
