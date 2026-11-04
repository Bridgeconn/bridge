<script lang="ts">
  import { onMount, setContext } from "svelte";
  import { derived, writable } from "svelte/store";
  import { arrange, defaultLayout, dockPane, resizeDivider, validLayout, without, type AlignmentLayoutContext, type Divider, type DockEdge, type PaneId, type Rect } from "../alignmentLayout";
  export let kind = "word";
  const layout = writable(defaultLayout(kind));
  let node: HTMLElement, width = 1000, height = 500;
  const viewport = writable({ width, height });
  const name = (id: PaneId) => id[0].toUpperCase() + id.slice(1);
  function fitted(rect: Rect): Rect {
    const w = Math.min(width, Math.max(180, rect.width)), h = Math.min(height, Math.max(90, rect.height));
    return { x: Math.max(0, Math.min(width - w, rect.x)), y: Math.max(0, Math.min(height - h, rect.y)), width: w, height: h };
  }
  const frames = derived([layout, viewport], ([value]) => {
    const result = arrange(without(value.tree, value.floating)).frames;
    for (const id of value.floating) result[id] = { ...fitted(value.positions[id] || { x: 16, y: 16, width: 500, height: 300 }), unit: "px" };
    return result;
  });
  $: dividers = arrange(without($layout.tree, $layout.floating)).dividers;
  function save() { try { localStorage.setItem(`bridge.alignment.docking.v2.${kind}`, JSON.stringify($layout)); } catch { /* session only */ } }
  function dock(id: PaneId, target: PaneId, edge: DockEdge) {
    if (id === target) return;
    layout.set({ ...$layout, tree: dockPane($layout.tree, id, target, edge), floating: $layout.floating.filter(v => v !== id && v !== target) }); save();
  }
  function float(id: PaneId) {
    layout.set({ ...$layout, floating: [...new Set([...$layout.floating, id])], positions: { ...$layout.positions, [id]: fitted($layout.positions[id] || { x: 16, y: 16, width: width * .6, height: height * .6 }) } }); save();
  }
  function resize(id: PaneId, axis: "width" | "height", value: number) {
    if (!Number.isFinite(value)) return;
    const current = $frames[id]!;
    const rect = current.unit === "px" ? current : { x: current.x / 100 * width, y: current.y / 100 * height, width: current.width / 100 * width, height: current.height / 100 * height };
    layout.set({ ...$layout, floating: [...new Set([...$layout.floating, id])], positions: { ...$layout.positions, [id]: fitted({ ...rect, [axis]: value }) } }); save();
  }
  let moving: { id: PaneId; x: number; y: number; startX: number; startY: number; offsetX: number; offsetY: number; moved: boolean } | null = null;
  let candidate: { target: PaneId; edge: DockEdge; rect: Rect } | null = null;
  let sizing: Divider | null = null;
  function beginMove(id: PaneId, event: PointerEvent) {
    if (event.button !== 0) return;
    event.preventDefault();
    (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
    const pane = (event.currentTarget as HTMLElement).closest("[data-alignment-pane]")!.getBoundingClientRect();
    moving = { id, x: event.clientX, y: event.clientY, startX: event.clientX, startY: event.clientY, offsetX: event.clientX - pane.left, offsetY: event.clientY - pane.top, moved: false };
  }
  function pointerMove(event: PointerEvent) {
    if (sizing) {
      const bounds = node.getBoundingClientRect(), horizontal = sizing.axis === "horizontal";
      const position = horizontal ? (event.clientX - bounds.left) / bounds.width * 100 : (event.clientY - bounds.top) / bounds.height * 100;
      const ratio = (position - (horizontal ? sizing.bounds.x : sizing.bounds.y)) / (horizontal ? sizing.bounds.width : sizing.bounds.height);
      layout.set({ ...$layout, tree: resizeDivider($layout.tree, sizing.id, ratio) }); return;
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
        const bounds = node.getBoundingClientRect(), old = $layout.positions[moving.id];
        layout.set({ ...$layout, floating: [...new Set([...$layout.floating, moving.id])], positions: { ...$layout.positions,
          [moving.id]: fitted({ x: moving.x - bounds.left - moving.offsetX, y: moving.y - bounds.top - moving.offsetY, width: old?.width || width * .6, height: old?.height || height * .6 }) } }); save();
      }
    }
    moving = null; candidate = null;
  }
  function adjust(divider: Divider, event: KeyboardEvent) {
    const negative = divider.axis === "horizontal" ? "ArrowLeft" : "ArrowUp", positive = divider.axis === "horizontal" ? "ArrowRight" : "ArrowDown";
    if (event.key !== negative && event.key !== positive) return;
    event.preventDefault(); layout.set({ ...$layout, tree: resizeDivider($layout.tree, divider.id, divider.ratio + (event.key === negative ? -.05 : .05)) }); save();
  }
  setContext<AlignmentLayoutContext>("alignment-layout", { layout, frames, dock, float, beginMove, resize });
  onMount(() => {
    try { const value = JSON.parse(localStorage.getItem(`bridge.alignment.docking.v2.${kind}`) || "null"); if (validLayout(value)) layout.set(value); } catch { /* default */ }
    const measure = () => { width = node.clientWidth || width; height = node.clientHeight || height; viewport.set({ width, height }); };
    measure(); if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure); observer.observe(node); return () => observer.disconnect();
  });
</script>

<svelte:window on:pointermove={pointerMove} on:pointerup={finish} on:pointercancel={() => { moving = null; candidate = null; sizing = null; }} on:keydown={(event) => { if (event.key === "Escape") { moving = null; candidate = null; sizing = null; } }} />
<div class="layout-toolbar"><button type="button" on:click={() => { layout.set(defaultLayout(kind)); save(); }}>Reset layout</button><small>Drag a handle near another area's edge to dock left, right, above or below. Drop away from edges to float; hold Alt to float anywhere. Drag dividers to resize.</small></div>
<div class="alignment-layout" bind:this={node} class:moving={!!moving}>
  <slot />
  {#each dividers as divider (divider.id)}
    <div class="divider" class:vertical={divider.axis === "horizontal"} role="slider" tabindex="0" aria-label={divider.axis === "horizontal" ? "Resize area widths" : "Resize area heights"}
      aria-orientation={divider.axis} aria-valuenow={Math.round(divider.ratio * 100)} aria-valuemin="15" aria-valuemax="85"
      style:left={`${divider.axis === "horizontal" ? divider.at : divider.bounds.x}%`} style:top={`${divider.axis === "vertical" ? divider.at : divider.bounds.y}%`}
      style:width={divider.axis === "horizontal" ? "6px" : `${divider.bounds.width}%`} style:height={divider.axis === "vertical" ? "6px" : `${divider.bounds.height}%`}
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
  button { font: inherit; border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); border-radius: 6px; padding: 5px 9px; cursor: pointer; }
  small { color: var(--text-3); }
  .alignment-layout { position: relative; height: min(620px, 65vh); min-height: 340px; flex: 1 1 auto; overflow: hidden; }
  .moving { user-select: none; }
  .divider { position: absolute; z-index: 5; background: var(--border); cursor: row-resize; transform: translateY(-3px); touch-action: none; }
  .divider.vertical { cursor: col-resize; transform: translateX(-3px); }
  .divider:hover, .divider:focus { background: var(--accent); outline: 1px solid var(--accent); }
  .dock-preview { position: absolute; z-index: 20; pointer-events: none; border: 2px solid var(--accent); background: var(--accent-bg); opacity: .85; display: grid; place-items: center; box-sizing: border-box; }
  .dock-preview span { background: var(--surface); color: var(--text); padding: 8px; border-radius: 5px; }
  .drag-label { position: fixed; z-index: 1000; pointer-events: none; background: var(--accent); color: white; border-radius: 5px; padding: 5px 9px; }
</style>
