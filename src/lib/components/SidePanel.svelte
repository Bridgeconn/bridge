<script lang="ts">
  // One of the editor's side panels. It is a tab of the work area
  // (2026-11-14, editorTabs.ts): placed in its group's frame, below the tab
  // strip, or hidden while another tab of the group shows. `keepMounted`
  // hides a closed panel instead of removing it, for panels that do work
  // while unseen (the review panel's live checks, Language QA's F8 walk).
  //
  // The floating box inside the window (#389 step 3) is gone (Joel,
  // 2026-11-14): a panel is a tab or, dragged out of Bridge, its own window.
  import { getContext } from "svelte";
  import type { EditorDockContext } from "../editorDocking";
  import { SIDE_PANEL_LIMITS, sidePanels } from "../editorPrefs";
  import type { SidePanelId } from "../editorPrefs";
  import { paneStyle, visibleTabs } from "../editorTabs";

  export let id: SidePanelId;
  export let label: string;
  export let keepMounted = false;

  const docking = getContext<EditorDockContext | undefined>("editor-docking");
  const frames = docking?.frames;
  $: frame = frames ? $frames?.[id] : undefined;
  // Its group's frame, below the tab strip (editorTabs.ts).
  $: frameStyle = paneStyle(frame);

  let innerWidth = typeof window === "undefined" ? 1366 : window.innerWidth;

  $: limits = SIDE_PANEL_LIMITS[id];
  $: open = $sidePanels[id].open && !$sidePanels[id].detached;
  // Another tab of its group is showing: hidden, still open.
  $: behindTab = open && !$visibleTabs.has(id);
  // Outside a workspace (no frame): a column at its saved width, never more
  // than 45% of the window.
  $: maxWidth = Math.max(limits.min, Math.min(limits.max, Math.floor(innerWidth * 0.45)));
  $: width = Math.min($sidePanels[id].width, maxWidth);
</script>

<svelte:window bind:innerWidth />

{#if open || keepMounted}
  <!-- One slot instance survives tab, group and split changes. -->
  <section data-editor-pane={id} class="side-panel" id={`side-panel-${id}`} aria-label={label}
    hidden={!open || behindTab}
    style={frameStyle || `width:${width}px;min-width:${limits.min}px`}>
    <div class="panel-body"><slot /></div>
  </section>
{/if}

<style>
  .side-panel { position: relative; flex-shrink: 1; display: flex; flex-direction: column; min-height: 0;
    overflow: hidden; border-left: 1px solid var(--border); background: var(--surface); }
  .side-panel[hidden] { display: none; }
  .panel-body { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
</style>
