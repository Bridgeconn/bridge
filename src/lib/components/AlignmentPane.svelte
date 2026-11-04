<script lang="ts">
  import OverflowMenu from "./OverflowMenu.svelte";
  import IconButton from "./IconButton.svelte";
  import { tooltip } from "../tooltip";
  import { getContext } from "svelte";
  import { paneIds, type AlignmentLayoutContext, type DockEdge, type PaneId } from "../alignmentLayout";
  export let id: PaneId;
  export let label: string;
  const { layout, frames, dock, float, beginMove, resize } = getContext<AlignmentLayoutContext>("alignment-layout");
  $: actions = (["left", "right", "top", "bottom"] as const).map(edge => ({ id: edge, label: `Dock ${edge === "top" ? "above" : edge === "bottom" ? "below" : edge + " of"}`,
    submenu: paneIds.filter(other => other !== id).map(target => ({ id: `dock:${target}:${edge}`, label: name(target) })) }));
  function action(value: string) { const [, target, edge] = value.split(":"); dock(id, target as PaneId, edge as DockEdge); }
  $: floating = $layout.floating.includes(id);
  $: frame = $frames[id];
  const name = (value: PaneId) => value[0].toUpperCase() + value.slice(1);
</script>

<section class="pane" class:floating data-alignment-pane={id} aria-label={`${label} area`}
  style:left={`${frame?.x || 0}${frame?.unit || "%"}`} style:top={`${frame?.y || 0}${frame?.unit || "%"}`}
  style:width={`${frame?.width || 100}${frame?.unit || "%"}`} style:height={`${frame?.height || 100}${frame?.unit || "%"}`}>
  <div class="handle">
    <button type="button" class="grip" on:pointerdown={(event) => beginMove(id, event)} aria-label={`Move ${label}`} use:tooltip={"Drag to move or dock this area; keyboard placement is in the tools menu"}>&#x283f; {label}</button>
    <IconButton icon={floating ? "dock" : "float"} label={floating ? `Dock ${label} area` : `Float ${label} area inside workspace`}
      on:click={() => floating ? dock(id, paneIds.find(other => other !== id) || "read", "right") : float(id)} />
    <OverflowMenu label={`${label} area tools`} {actions} on:action={(event) => action(event.detail.id)} />
    {#if floating}<label class="area-size">Width <input type="number" min="180" step="24" aria-label={`${label} width`} value={Math.round(frame?.width || 300)} on:change={(event) => resize(id, "width", Number(event.currentTarget.value))} /></label><label class="area-size">Height <input type="number" min="90" step="24" aria-label={`${label} height`} value={Math.round(frame?.height || 300)} on:change={(event) => resize(id, "height", Number(event.currentTarget.value))} /></label>{/if}
  </div>
  <div class="content"><slot /></div>
</section>

<style>
  .pane { position: absolute; box-sizing: border-box; min-width: 0; min-height: 0; border: 0; border-radius: 0; background: var(--surface); display: flex; flex-direction: column; padding: 0; }
  .handle { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; padding: 0 8px; min-height: 36px; border-bottom: 1px solid var(--border); background: var(--surface-2); flex: none; }
  button { font: inherit; font-size: var(--fs-xs); padding: 3px 5px; border: 1px solid var(--border); border-radius: 5px; color: var(--text); background: var(--surface); }
  button { cursor: pointer; }
  .grip { cursor: move; touch-action: none; margin-right: auto; }
  .area-size { font-size: var(--fs-2xs); }
  input { width: 64px; font: inherit; margin: 4px; }
  .content { padding: 6px; overflow: auto; flex: 1; min-height: 0; }
  .floating { z-index: 8; box-shadow: 0 5px 24px #0003; }


</style>
