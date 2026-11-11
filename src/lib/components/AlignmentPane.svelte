<script lang="ts">
  import OverflowMenu from "./OverflowMenu.svelte";
  import { tooltip } from "../tooltip";
  import { getContext } from "svelte";
  import { paneIds, type AlignmentLayoutContext, type DockEdge, type PaneId } from "../alignmentLayout";
  export let id: PaneId;
  export let label: string;
  const { layout, frames, dock, float, beginMove, resize } = getContext<AlignmentLayoutContext>("alignment-layout");
  // #485: the Float / Dock entry sits in the tools menu, with the keyboard
  // docking; the handle itself is a slim strip, muted until the pane is
  // hovered or focused.
  $: actions = [
    { id: floating ? "dock" : "float", label: floating ? "Dock in the workspace" : "Float inside the workspace" },
    ...(["left", "right", "top", "bottom"] as const).map(edge => ({ id: edge, label: `Dock ${edge === "top" ? "above" : edge === "bottom" ? "below" : edge + " of"}`,
      submenu: paneIds.filter(other => other !== id).map(target => ({ id: `dock:${target}:${edge}`, label: name(target) })) })),
  ];
  function action(value: string) {
    if (value === "float") { float(id); return; }
    if (value === "dock") { dock(id, paneIds.find(other => other !== id) || "read", "right"); return; }
    const [, target, edge] = value.split(":"); dock(id, target as PaneId, edge as DockEdge);
  }
  $: floating = $layout.floating.includes(id);
  $: frame = $frames[id];
  $: box = frame && !frame.docked ? frame : null;
  const name = (value: PaneId) => value[0].toUpperCase() + value.slice(1);
</script>

<section class="pane" class:floating data-alignment-pane={id} aria-label={`${label} area`}
  style:grid-area={box ? null : id}
  style:left={box ? `${box.x}px` : null} style:top={box ? `${box.y}px` : null}
  style:width={box ? `${box.width}px` : null} style:height={box ? `${box.height}px` : null}>
  <div class="handle">
    <button type="button" class="grip" on:pointerdown={(event) => beginMove(id, event)} aria-label={`Move ${label}`} use:tooltip={"Drag to move or dock this area; keyboard placement is in the tools menu"}>&#x283f;<span class="grip-label">{label}</span></button>
    {#if box}<label class="area-size">Width <input type="number" min="180" step="24" aria-label={`${label} width`} value={Math.round(box.width)} on:change={(event) => resize(id, "width", Number(event.currentTarget.value))} /></label><label class="area-size">Height <input type="number" min="90" step="24" aria-label={`${label} height`} value={Math.round(box.height)} on:change={(event) => resize(id, "height", Number(event.currentTarget.value))} /></label>{/if}
    <OverflowMenu label={`${label} area tools`} {actions} on:action={(event) => action(event.detail.id)} />
  </div>
  <div class="content"><slot /></div>
</section>

<style>
  /* #485: a docked pane is a grid item sized by its content: no fixed height,
     no scrolling inside. A floating pane keeps its own box over the stage and
     is the one place content may scroll, inside the box the reviewer sized. */
  .pane { box-sizing: border-box; min-width: 0; min-height: 0; border: 0; border-radius: 0; background: var(--surface); display: flex; flex-direction: column; padding: 0; }
  .floating { position: absolute; z-index: 8; box-shadow: 0 5px 24px #0003; border: 1px solid var(--border); border-radius: 8px; }
  .floating .content { overflow: auto; flex: 1; min-height: 0; }
  /* The strip: grip at the left, the tools at the right, faint until wanted. */
  .handle { display: flex; align-items: center; gap: 4px; padding: 0 4px; min-height: 22px; flex: none; opacity: .55; transition: opacity .15s ease; }
  .pane:hover .handle, .pane:focus-within .handle, .floating .handle { opacity: 1; }
  .floating .handle { border-bottom: 1px solid var(--border); background: var(--surface-2); }
  .grip { display: inline-flex; align-items: center; gap: 5px; font: inherit; font-size: var(--fs-2xs); padding: 1px 5px; border: 0; border-radius: 5px; color: var(--text-3); background: transparent; cursor: move; touch-action: none; margin-right: auto; }
  .grip:hover, .grip:focus-visible { color: var(--text); background: var(--surface-2); }
  .grip-label { font-weight: 600; }
  .area-size { font-size: var(--fs-2xs); color: var(--text-3); }
  input { width: 64px; font: inherit; margin: 2px; }
  .content { padding: 6px; }
</style>
