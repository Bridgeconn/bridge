<script lang="ts">
  import OverflowMenu from "./OverflowMenu.svelte";
  import { get } from "svelte/store";
  import { project, localUserId } from "../stores";
  import { onMount, setContext } from "svelte";
  import { derived, writable } from "svelte/store";
  import { defaultLayout, dockPane, gridAreasText, gridFor, resizeDivider, validLayout, without, type AlignmentLayoutContext, type DockEdge, type GridDivider, type PaneFrame, type PaneId, type Rect } from "../alignmentLayout";
  export let kind = "word";
  export let toolbar = true;
  export function layoutAction(id: string) {
    if (id === "reset") { layout.set(defaultLayout(kind)); save(); }
    else helpOpen = !helpOpen;
  }
  // #485: the stage is a CSS grid whose rows fit their content (gridFor), so
  // a docked pane never scrolls inside; the dialog around the workspace is
  // the one thing that scrolls. Only floating panes have a box of their own.
  const layout = writable(defaultLayout(kind));
  let node: HTMLElement, width = 1000, height = 500;
  const viewport = writable({ width, height });
  const name = (id: PaneId) => id[0].toUpperCase() + id.slice(1);
  /** A floating box inside the stage's width; its height is its own, the
   * stage grows to reach it (min-height below). */
  function fitted(rect: Rect): Rect {
    const w = Math.min(width, Math.max(180, rect.width)), h = Math.max(90, rect.height);
    return { x: Math.max(0, Math.min(width - w, rect.x)), y: Math.max(0, rect.y), width: w, height: h };
  }
  const frames = derived([layout, viewport], ([value]) => {
    const result: Partial<Record<PaneId, PaneFrame>> = {};
    for (const id of ["read", "source", "target"] as const) result[id] = { docked: true };
    for (const id of value.floating) result[id] = { docked: false, ...fitted(value.positions[id] || { x: 16, y: 16, width: 500, height: 300 }) };
    return result;
  });
  $: grid = gridFor(without($layout.tree, $layout.floating));
  $: areasText = gridAreasText(grid.areas);
  $: columnsText = grid.columns.map((w) => `${w}fr`).join(" ");
  $: floatBottom = Math.max(0, ...$layout.floating.map((id) => { const f = $frames[id]; return f && !f.docked ? f.y + f.height : 0; }));
  let helpOpen = false;
  const workspaceKey = () => { const p = get(project); return `bridge.alignment.docking.v3.${encodeURIComponent(get(localUserId) || "local")}.${encodeURIComponent(p?.collectionId || p?.projectId || p?.path || "default")}.${kind}`; };
  function save() { try { localStorage.setItem(workspaceKey(), JSON.stringify($layout)); } catch { /* session only */ } }
  function dock(id: PaneId, target: PaneId, edge: DockEdge) {
    if (id === target) return;
    layout.set({ ...$layout, tree: dockPane($layout.tree, id, target, edge), floating: $layout.floating.filter(v => v !== id && v !== target) }); save();
  }
  /** Where a pane is drawn right now, in stage px: its own box when floating,
   * else its grid cell as laid out. */
  function drawn(id: PaneId): Rect {
    const frame = $frames[id];
    if (frame && !frame.docked) return frame;
    const el = node?.querySelector<HTMLElement>(`[data-alignment-pane="${id}"]`);
    if (!el || !node) return { x: 16, y: 16, width: width * .6, height: height * .6 };
    const bounds = node.getBoundingClientRect(), rect = el.getBoundingClientRect();
    // Floated from a cell: no wider than 60% of the stage, so it floats
    // visibly over the rest; as tall as its content, so nothing scrolls yet.
    return { x: rect.left - bounds.left, y: rect.top - bounds.top, width: Math.min(rect.width || width * .6, width * .6), height: rect.height || height * .6 };
  }
  function float(id: PaneId) {
    layout.set({ ...$layout, floating: [...new Set([...$layout.floating, id])], positions: { ...$layout.positions, [id]: fitted($layout.positions[id] || drawn(id)) } }); save();
  }
  function resize(id: PaneId, axis: "width" | "height", value: number) {
    if (!Number.isFinite(value)) return;
    layout.set({ ...$layout, floating: [...new Set([...$layout.floating, id])], positions: { ...$layout.positions, [id]: fitted({ ...drawn(id), [axis]: value }) } }); save();
  }
  let moving: { id: PaneId; x: number; y: number; startX: number; startY: number; offsetX: number; offsetY: number; moved: boolean } | null = null;
  let candidate: { target: PaneId; edge: DockEdge; rect: Rect } | null = null;
  let sizing: GridDivider | null = null;
  function beginMove(id: PaneId, event: PointerEvent) {
    if (event.button !== 0) return;
    event.preventDefault();
    (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
    const pane = (event.currentTarget as HTMLElement).closest("[data-alignment-pane]")!.getBoundingClientRect();
    moving = { id, x: event.clientX, y: event.clientY, startX: event.clientX, startY: event.clientY, offsetX: event.clientX - pane.left, offsetY: event.clientY - pane.top, moved: false };
  }
  function pointerMove(event: PointerEvent) {
    if (sizing) {
      const bounds = node.getBoundingClientRect();
      const position = (event.clientX - bounds.left) / bounds.width * 100;
      layout.set({ ...$layout, tree: resizeDivider($layout.tree, sizing.id, (position - sizing.bounds.x) / sizing.bounds.width) }); return;
    }
    if (!moving) return;
    moving = { ...moving, x: event.clientX, y: event.clientY, moved: moving.moved || Math.hypot(event.clientX - moving.startX, event.clientY - moving.startY) > 4 };
    candidate = null;
    if (!moving.moved || event.altKey) return;
    const pane = document.elementsFromPoint(event.clientX, event.clientY).map(el => el.closest<HTMLElement>("[data-alignment-pane]"))
      .find(el => el && el.dataset.alignmentPane !== moving!.id && node.contains(el));
    if (!pane) return;
    const rect = pane.getBoundingClientRect(), x = (event.clientX - rect.left) / rect.width, y = (event.clientY - rect.top) / rect.height;
    const edges: [DockEdge, number][] = [["left", x], ["right", 1 - x], ["top", y], ["bottom", 1 - y]];
    const nearest = edges.sort((a, b) => a[1] - b[1])[0];
    if (nearest[1] > .25) return;
    const edge = nearest[0], bounds = node.getBoundingClientRect();
    candidate = { target: pane.dataset.alignmentPane as PaneId, edge, rect: {
      x: rect.left - bounds.left + (edge === "right" ? rect.width / 2 : 0), y: rect.top - bounds.top + (edge === "bottom" ? rect.height / 2 : 0),
      width: edge === "left" || edge === "right" ? rect.width / 2 : rect.width, height: edge === "top" || edge === "bottom" ? rect.height / 2 : rect.height } };
  }
  function finish() {
    if (sizing) { sizing = null; save(); }
    if (moving?.moved) {
      if (candidate) dock(moving.id, candidate.target, candidate.edge);
      else {
        const bounds = node.getBoundingClientRect(), old = $layout.positions[moving.id] || drawn(moving.id);
        layout.set({ ...$layout, floating: [...new Set([...$layout.floating, moving.id])], positions: { ...$layout.positions,
          [moving.id]: fitted({ x: moving.x - bounds.left - moving.offsetX, y: moving.y - bounds.top - moving.offsetY, width: old.width, height: old.height }) } }); save();
      }
    }
    moving = null; candidate = null;
  }
  function adjust(divider: GridDivider, event: KeyboardEvent) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault(); layout.set({ ...$layout, tree: resizeDivider($layout.tree, divider.id, divider.ratio + (event.key === "ArrowLeft" ? -.05 : .05)) }); save();
  }
  setContext<AlignmentLayoutContext>("alignment-layout", { layout, frames, dock, float, beginMove, resize });
  onMount(() => {
    try { const value = JSON.parse(localStorage.getItem(workspaceKey()) || localStorage.getItem(`bridge.alignment.docking.v2.${kind}`) || "null"); if (validLayout(value)) layout.set(value); } catch { /* default */ }
    const measure = () => { width = node.clientWidth || width; height = node.clientHeight || height; viewport.set({ width, height }); };
    measure(); if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure); observer.observe(node); return () => observer.disconnect();
  });
</script>

<svelte:window on:pointermove={pointerMove} on:pointerup={finish} on:pointercancel={() => { moving = null; candidate = null; sizing = null; }} on:keydown={(event) => { if (event.key === "Escape") { moving = null; candidate = null; sizing = null; } }} />
{#if toolbar || helpOpen}<div class="layout-toolbar">{#if toolbar}<OverflowMenu label="Alignment layout tools" actions={[{ id: "reset", label: "Reset layout" }, { id: "help", label: "Moving and resizing help" }]} on:action={(event) => layoutAction(event.detail.id)} />{/if}{#if helpOpen}<small>Drag an area's handle near another area's edge to dock it left, right, above or below. Drop away from the edges to float it; hold Alt to float anywhere. Drag the divider between side-by-side areas to change their widths.</small>{/if}</div>{/if}
<div class="alignment-layout" bind:this={node} class:moving={!!moving}
  data-grid-areas={areasText} data-grid-columns={columnsText}
  style:grid-template-areas={areasText || null} style:grid-template-columns={columnsText || null}
  style:min-height={floatBottom ? `${floatBottom}px` : null}>
  <slot />
  {#each grid.dividers as divider (divider.id)}
    <div class="divider" role="slider" tabindex="0" aria-label="Resize area widths" aria-orientation="vertical"
      aria-valuenow={Math.round(divider.ratio * 100)} aria-valuemin="15" aria-valuemax="85"
      style:grid-column={`${divider.column}`} style:grid-row={`${divider.rowStart} / ${divider.rowEnd}`}
      on:pointerdown={(event) => { event.preventDefault(); event.currentTarget.setPointerCapture?.(event.pointerId); sizing = divider; }} on:keydown={(event) => adjust(divider, event)}></div>
  {/each}
  {#if candidate && moving}
    <div class="dock-preview" style:left={`${candidate.rect.x}px`} style:top={`${candidate.rect.y}px`} style:width={`${candidate.rect.width}px`} style:height={`${candidate.rect.height}px`}>
      <span>{name(moving.id)} {candidate.edge === "top" ? "above" : candidate.edge === "bottom" ? "below" : `to the ${candidate.edge} of`} {name(candidate.target)}</span>
    </div>
  {/if}
  {#if moving?.moved}<div class="drag-label" style:left={`${moving.x + 12}px`} style:top={`${moving.y + 12}px`}>{name(moving.id)}{candidate ? " - dock here" : " - float here"}</div>{/if}
</div>

<style>
  .layout-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
  small { color: var(--text-3); }
  /* #485: no fixed height and no scroll container: rows are `auto`, so the
     stage is as tall as its content and the dialog scrolls. overflow-x: clip
     keeps a wide line from drawing a sideways bar without making the stage
     scroll (hidden would). */
  .alignment-layout { position: relative; display: grid; grid-auto-rows: auto; gap: 0 10px; align-items: start; overflow-x: clip; }
  .moving { user-select: none; }
  /* A width divider is a grid item on its column line, spanning the rows of
     its split: a hairline that colours on hover and focus, with a 10px hit
     area straddling the line. */
  .divider { position: relative; z-index: 5; justify-self: start; align-self: stretch; width: 10px; margin-left: -10px; cursor: col-resize; touch-action: none; background: transparent; }
  .divider::after { content: ""; position: absolute; top: 0; bottom: 0; left: 50%; width: 1px; background: var(--border); pointer-events: none; }
  .divider:hover::after, .divider:focus-visible::after { background: var(--accent); width: 2px; }
  .divider:focus-visible { outline: none; }
  .dock-preview { position: absolute; z-index: 20; pointer-events: none; border: 2px solid var(--text-3); background: var(--surface-2); opacity: .85; display: grid; place-items: center; box-sizing: border-box; }
  .dock-preview span { background: var(--surface); color: var(--text); padding: 8px; border-radius: 5px; }
  .drag-label { position: fixed; z-index: 1000; pointer-events: none; background: var(--text-3); color: white; border-radius: 5px; padding: 5px 9px; }
</style>
