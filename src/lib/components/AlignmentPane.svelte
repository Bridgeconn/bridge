<script lang="ts">
  import { getContext } from "svelte";
  import { paneIds, type AlignmentLayoutContext, type DockEdge, type PaneId } from "../alignmentLayout";
  export let id: PaneId;
  export let label: string;
  const { layout, frames, dock, float, beginMove, resize } = getContext<AlignmentLayoutContext>("alignment-layout");
  let target: PaneId = paneIds.find(value => value !== id)!, edge: DockEdge = "right", placement: HTMLDetailsElement;
  $: floating = $layout.floating.includes(id);
  $: frame = $frames[id];
  const name = (value: PaneId) => value[0].toUpperCase() + value.slice(1);
</script>

<section class="pane" class:floating data-alignment-pane={id} aria-label={`${label} area`}
  style:left={`${frame?.x || 0}${frame?.unit || "%"}`} style:top={`${frame?.y || 0}${frame?.unit || "%"}`}
  style:width={`${frame?.width || 100}${frame?.unit || "%"}`} style:height={`${frame?.height || 100}${frame?.unit || "%"}`}>
  <div class="handle">
    <button type="button" class="grip" on:pointerdown={(event) => beginMove(id, event)} aria-label={`Move ${label}`} title="Drag to move or dock this area">&#x283f; {label}</button>
    <details bind:this={placement}><summary>Arrange</summary><div class="placement">
      <label>Place {label} <select aria-label={`${label} docking position`} bind:value={edge}><option value="left">left of</option><option value="right">right of</option><option value="top">above</option><option value="bottom">below</option></select></label>
      <select aria-label={`${label} docking neighbor`} bind:value={target}>{#each paneIds.filter(value => value !== id) as value}<option value={value}>{name(value)}</option>{/each}</select>
      <button type="button" on:click={() => { dock(id, target, edge); placement.open = false; }}>Dock {label}</button>
      <button type="button" on:click={() => { float(id); placement.open = false; }}>Float {label}</button>
    </div></details>
    {#if floating}<details><summary>Size</summary><label>Width <input type="number" min="180" step="24" aria-label={`${label} width`} value={Math.round(frame?.width || 300)} on:change={(event) => resize(id, "width", Number(event.currentTarget.value))} /></label><label>Height <input type="number" min="90" step="24" aria-label={`${label} height`} value={Math.round(frame?.height || 300)} on:change={(event) => resize(id, "height", Number(event.currentTarget.value))} /></label></details>{/if}
  </div>
  <div class="content"><slot /></div>
</section>

<style>
  .pane { position: absolute; box-sizing: border-box; min-width: 0; min-height: 0; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); display: flex; flex-direction: column; padding: 2px; }
  .handle { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; padding: 3px; background: var(--surface-2); flex: none; }
  button, select { font: inherit; font-size: var(--fs-xs); padding: 3px 5px; border: 1px solid var(--border); border-radius: 5px; color: var(--text); background: var(--surface); }
  button { cursor: pointer; }
  .grip { cursor: move; touch-action: none; margin-right: auto; }
  details { font-size: var(--fs-xs); }
  summary { cursor: pointer; }
  .placement { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; padding-top: 4px; }
  input { width: 64px; font: inherit; margin: 4px; }
  .content { padding: 6px; overflow: auto; flex: 1; min-height: 0; }
  .floating { z-index: 8; box-shadow: 0 5px 24px #0003; }
  .pane:has(details[open]) { z-index: 16; }
  .placement { position: absolute; top: 30px; right: 4px; z-index: 1; max-width: min(340px, 90vw); background: var(--surface); padding: 8px; border: 1px solid var(--border-strong); border-radius: 5px; box-shadow: 0 3px 12px #0003; }
</style>
