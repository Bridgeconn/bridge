<script lang="ts">
  import { getContext, onMount } from "svelte";
  import type { Writable } from "svelte/store";
  export let id: string;
  export let label: string;
  const { layout, move, float, drop, start, kind } = getContext<{
    kind: string;
    layout: Writable<{ order: string[]; floating: string[] }>;
    move: (id: string, direction: number) => void; float: (id: string) => void;
    drop: (id: string) => void; start: (id: string) => void;
  }>("alignment-layout");
  let node: HTMLElement;
  let x = 16, y = 16;
  let tracking: { x: number; y: number; left: number; top: number } | null = null;
  $: floating = $layout.floating.includes(id);
  function clamp() {
    if (!node?.parentElement) return;
    x = Math.max(0, Math.min(x, Math.max(0, node.parentElement.clientWidth - Math.min(160, node.clientWidth))));
    y = Math.max(0, Math.min(y, Math.max(0, node.parentElement.clientHeight - 50)));
  }
  function remember() {
    clamp();
    try { localStorage.setItem(`bridge.alignment.pane.${kind}.${id}`, JSON.stringify({ x, y, width: node.style.width, height: node.style.height })); } catch { /* session only */ }
  }
  function shift(dx: number, dy: number) { x += dx; y += dy; remember(); }
  function resize(axis: "width" | "height", event: Event) {
    const value = Number((event.target as HTMLInputElement).value);
    const limit = axis === "width" ? node.parentElement?.clientWidth || 1000 : 1600;
    node.style[axis] = `${Math.max(axis === "width" ? 200 : 100, Math.min(limit, value || 300))}px`;
    remember();
  }
  onMount(() => {
    try {
      const value = JSON.parse(localStorage.getItem(`bridge.alignment.pane.${kind}.${id}`) || "null");
      if (value) { x = Number.isFinite(value.x) ? value.x : 16; y = Number.isFinite(value.y) ? value.y : 16; node.style.width = value.width || ""; node.style.height = value.height || ""; clamp(); }
    } catch { /* default layout */ }
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(clamp);
    if (node.parentElement) observer.observe(node.parentElement);
    return () => observer.disconnect();
  });
  function pointerMove(event: PointerEvent) {
    if (!tracking || !node?.parentElement) return;
    x = Math.max(0, Math.min(node.parentElement.clientWidth - 100, tracking.left + event.clientX - tracking.x));
    y = Math.max(0, Math.min(node.parentElement.clientHeight - 40, tracking.top + event.clientY - tracking.y));
  }
</script>

<svelte:window on:pointermove={pointerMove} on:pointerup={() => { tracking = null; remember(); }} />
<section bind:this={node} class="pane" class:floating style:order={$layout.order.indexOf(id)} style:left={floating ? `${x}px` : undefined} style:top={floating ? `${y}px` : undefined}
  on:dragover|preventDefault on:drop|preventDefault={() => drop(id)} aria-label={`${label} area`}>
  <div class="handle">
    <button type="button" class="grip" draggable={!floating} on:dragstart={() => start(id)}
      on:pointerdown={(e) => { if (floating) { e.preventDefault(); tracking = { x: e.clientX, y: e.clientY, left: x, top: y }; } }}
      aria-label={`Move ${label}`} title="Drag this handle to move the area">⠿ {label}</button>
    <button type="button" on:click={() => move(id, -1)} aria-label={`Move ${label} earlier`}>←</button>
    <button type="button" on:click={() => move(id, 1)} aria-label={`Move ${label} later`}>→</button>
    <button type="button" on:click={() => float(id)}>{floating ? "Dock" : "Undock"} {label}</button>
    <details><summary>Size</summary><label>Width <input type="number" min="200" step="24" aria-label={`${label} width`} value={node?.clientWidth || 300} on:change={(event) => resize("width", event)} /></label><label>Height <input type="number" min="100" step="24" aria-label={`${label} height`} value={node?.clientHeight || 300} on:change={(event) => resize("height", event)} /></label></details>
    {#if floating}
      <button type="button" on:click={() => shift(-24, 0)} aria-label={`Move ${label} left`}>←</button>
      <button type="button" on:click={() => shift(24, 0)} aria-label={`Move ${label} right`}>→</button>
      <button type="button" on:click={() => shift(0, -24)} aria-label={`Move ${label} up`}>↑</button>
      <button type="button" on:click={() => shift(0, 24)} aria-label={`Move ${label} down`}>↓</button>
    {/if}
  </div>
  <div class="content"><slot /></div>
</section>

<style>
  .pane { min-width: min(280px, 100%); max-width: 100%; flex: 1 0 auto; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); overflow: auto; resize: both; min-height: 100px; }
  .handle { display: flex; flex-wrap: wrap; gap: 4px; padding: 4px; background: var(--surface-2); position: sticky; top: 0; z-index: 2; }
  button { font: inherit; font-size: var(--fs-xs); padding: 4px 6px; border: 1px solid var(--border); border-radius: 5px; color: var(--text); background: var(--surface); cursor: pointer; }
  .grip { cursor: move; touch-action: none; margin-right: auto; }
  details { font-size: var(--fs-xs); }
  input { width: 70px; font: inherit; margin: 4px; }
  .content { padding: 6px; }
  .floating { position: absolute; z-index: 4; width: min(620px, 90%); height: 300px; box-shadow: 0 5px 24px #0003; }
</style>
