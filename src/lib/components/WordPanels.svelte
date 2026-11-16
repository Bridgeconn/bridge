<script lang="ts">
  /** The Word alignment tab's three panels as a grid that fills the tab
   *  (2026-11-16, Joel; wordPanels.ts holds the layout and `panelGrid` the
   *  sizes). The panels share the width and the height by their splits'
   *  ratios, and the line between two of them drags, across or down, as the
   *  line between two tab groups does. A row holding only the verse to read
   *  is as tall as its text. A panel with more words than room scrolls
   *  inside itself.
   *  A panel's title row drags the panel: over another panel a tinted box
   *  shows the side it will take, as a dragged editor tab does, and it lands
   *  there on release. */
  import { setContext } from "svelte";
  import type { DockEdge } from "../alignmentLayout";
  import { panelGrid, wordPanelLayout, type PanelDivider, type PanelLayout, type WordPanelId } from "../wordPanels";

  /** Whose panels: Word alignment's unless the Cross-verse tab passes its own. */
  export let layout: PanelLayout = wordPanelLayout;
  const tree = layout.tree;

  let node: HTMLDivElement;
  $: grid = panelGrid($tree, layout.fitRead);
  $: areasText = grid.areas.map((row) => `"${row.join(" ")}"`).join(" ");
  $: columnsText = grid.columns.map((w) => `minmax(0, ${w}fr)`).join(" ");
  // A sharing row is never squeezed to nothing: below 96px the tab scrolls.
  $: rowsText = grid.rows.map((h) => (h === "auto" ? "auto" : `minmax(96px, ${h}fr)`)).join(" ");

  type Drop = { target: WordPanelId; edge: DockEdge; left: number; top: number; width: number; height: number };
  let moving: { id: WordPanelId; startX: number; startY: number; moved: boolean } | null = null;
  let candidate: Drop | null = null;
  let sizing: PanelDivider | null = null;

  function beginMove(id: WordPanelId, event: PointerEvent): void {
    if (event.button !== 0) return;
    // The row drags; the controls in it click.
    if ((event.target as HTMLElement).closest("button, a, input, select, [data-no-drag]")) return;
    moving = { id, startX: event.clientX, startY: event.clientY, moved: false };
  }
  function dropAt(x: number, y: number): Drop | null {
    if (!moving) return null;
    const own = moving.id;
    const el = Array.from(node.querySelectorAll<HTMLElement>("[data-word-panel]")).find((panel) => {
      if (panel.dataset.wordPanel === own) return false;
      const r = panel.getBoundingClientRect();
      return x >= r.left && x < r.right && y >= r.top && y < r.bottom;
    });
    if (!el) return null;
    const r = el.getBoundingClientRect(), b = node.getBoundingClientRect();
    const px = (x - r.left) / Math.max(1, r.width), py = (y - r.top) / Math.max(1, r.height);
    const edges: [DockEdge, number][] = [["left", px], ["right", 1 - px], ["top", py], ["bottom", 1 - py]];
    const [edge] = edges.sort((first, second) => first[1] - second[1])[0];
    return { target: el.dataset.wordPanel as WordPanelId, edge,
      left: r.left - b.left + (edge === "right" ? r.width / 2 : 0), top: r.top - b.top + (edge === "bottom" ? r.height / 2 : 0),
      width: edge === "left" || edge === "right" ? r.width / 2 : r.width, height: edge === "top" || edge === "bottom" ? r.height / 2 : r.height };
  }
  /** The box the split's panels cover together: what its ratio divides. */
  function extent(divider: PanelDivider): { start: number; size: number } | null {
    const rects = divider.panels.map((id) => node.querySelector<HTMLElement>(`[data-word-panel="${id}"]`)?.getBoundingClientRect()).filter((r): r is DOMRect => Boolean(r));
    if (!rects.length) return null;
    const wide = divider.resizes === "width";
    const start = Math.min(...rects.map((r) => (wide ? r.left : r.top))), end = Math.max(...rects.map((r) => (wide ? r.right : r.bottom)));
    return end > start ? { start, size: end - start } : null;
  }
  function move(event: PointerEvent): void {
    if (sizing) {
      const box = extent(sizing);
      if (box) layout.resize(sizing.id, ((sizing.resizes === "width" ? event.clientX : event.clientY) - box.start) / box.size);
      return;
    }
    if (!moving) return;
    moving = { ...moving, moved: moving.moved || Math.hypot(event.clientX - moving.startX, event.clientY - moving.startY) > 5 };
    candidate = moving.moved ? dropAt(event.clientX, event.clientY) : null;
  }
  function finish(): void {
    if (moving?.moved && candidate) layout.dock(moving.id, candidate.target, candidate.edge);
    moving = null; candidate = null; sizing = null;
  }
  function cancel(): void { moving = null; candidate = null; sizing = null; }
  function onKey(event: KeyboardEvent): void {
    if (event.key === "Escape" && (moving?.moved || sizing)) { event.preventDefault(); event.stopImmediatePropagation(); cancel(); }
  }
  function adjust(divider: PanelDivider, event: KeyboardEvent): void {
    const less = divider.resizes === "width" ? "ArrowLeft" : "ArrowUp", more = divider.resizes === "width" ? "ArrowRight" : "ArrowDown";
    if (event.key !== less && event.key !== more) return;
    event.preventDefault();
    layout.resize(divider.id, divider.ratio + (event.key === less ? -0.02 : 0.02) * (event.shiftKey ? 3 : 1));
  }
  setContext("word-panels", { beginMove, layout });
</script>

<svelte:window on:pointermove={move} on:pointerup={finish} on:pointercancel={cancel} on:keydown|capture={onKey} />
<div class="word-panels" class:moving={!!moving?.moved} class:sizing={!!sizing} bind:this={node}
  data-grid-areas={areasText} data-grid-rows={rowsText}
  style:grid-template-areas={areasText || null} style:grid-template-columns={columnsText || null} style:grid-template-rows={rowsText || null}>
  <slot />
  {#each grid.dividers as divider (divider.id)}
    <div class="divider" class:height={divider.resizes === "height"} role="slider" tabindex="0"
      aria-label={divider.resizes === "width" ? "Resize panel widths" : "Resize panel heights"}
      aria-orientation={divider.resizes === "width" ? "vertical" : "horizontal"}
      aria-valuenow={Math.round(divider.ratio * 100)} aria-valuemin="15" aria-valuemax="85"
      style:grid-column={divider.resizes === "width" ? `${divider.line}` : `${divider.from} / ${divider.to}`}
      style:grid-row={divider.resizes === "width" ? `${divider.from} / ${divider.to}` : `${divider.line}`}
      on:pointerdown={(event) => { event.preventDefault(); sizing = divider; }} on:keydown={(event) => adjust(divider, event)}></div>
  {/each}
  {#if candidate}<div class="drop-preview" style:left={`${candidate.left}px`} style:top={`${candidate.top}px`} style:width={`${candidate.width}px`} style:height={`${candidate.height}px`} />{/if}
</div>

<style>
  /* The grid fills what the tab has under its header; its rows and columns
     are set from the layout (panelGrid). */
  .word-panels { position: relative; flex: 1 1 0; min-height: 280px; box-sizing: border-box; display: grid; gap: 8px; align-items: stretch; padding: 8px 10px 10px; min-width: 0; }
  .moving, .sizing { user-select: none; }
  .moving { cursor: grabbing; }
  /* The line between two panels sits in the gap on its grid line: nothing
     shows until it is pointed at, then the accent colour, as between two tab
     groups. */
  .divider { position: relative; z-index: 5; justify-self: start; align-self: stretch; width: 8px; margin-left: -8px; cursor: col-resize; touch-action: none; background: transparent; }
  .divider.height { justify-self: stretch; align-self: start; width: auto; height: 8px; margin-left: 0; margin-top: -8px; cursor: row-resize; }
  .divider::after { content: ""; position: absolute; top: 0; bottom: 0; left: 50%; width: 1px; margin-left: -.5px; background: transparent; border-radius: 2px; pointer-events: none; transition: background .15s; }
  .divider.height::after { top: 50%; bottom: auto; left: 0; right: 0; width: auto; height: 1px; margin-left: 0; margin-top: -.5px; }
  .divider:hover::after, .divider:focus-visible::after, .sizing .divider:active::after { background: var(--accent); width: 3px; margin-left: -1.5px; }
  .divider.height:hover::after, .divider.height:focus-visible::after, .sizing .divider.height:active::after { width: auto; height: 3px; margin-left: 0; margin-top: -1.5px; }
  .divider:focus-visible { outline: none; }
  /* The editor's tab drop preview (EditorWorkspace .drop-preview). */
  .drop-preview { position: absolute; z-index: 30; pointer-events: none; box-sizing: border-box; background: color-mix(in srgb, var(--accent) 16%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent) 45%, transparent); border-radius: 6px; transition: left .08s, top .08s, width .08s, height .08s; }
  @media (prefers-reduced-motion: reduce) { .drop-preview, .divider::after { transition: none; } }
</style>
