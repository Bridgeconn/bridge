<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import { tooltip } from "../tooltip";
  import UiIcon from "./UiIcon.svelte";
  import FindingContextMenu from "./FindingContextMenu.svelte";
  export let label = "More tools";
  export let actions: { id: string; label: string; disabled?: boolean; title?: string; submenu?: { id: string; label: string; disabled?: boolean }[] }[] = [];
  const dispatch = createEventDispatcher<{ action: { id: string; anchor: HTMLButtonElement } }>();
  let anchor: HTMLButtonElement;
  let position: { x: number; y: number } | null = null;
  function open() {
    anchor.focus();
    const rect = anchor.getBoundingClientRect();
    position = position ? null : { x: rect.left, y: rect.bottom + 4 };
  }
</script>

<button type="button" class="overflow-trigger" bind:this={anchor} aria-label={label}
  aria-haspopup="menu" aria-expanded={!!position} use:tooltip={label} on:click={open}
  on:keydown={(event) => { if (event.key === "ArrowDown") { event.preventDefault(); if (!position) open(); } }}><UiIcon name="more" /></button>
{#if position}
  <FindingContextMenu {...position} findingLabel={label} {actions}
    on:close={() => (position = null)}
    on:action={(event) => { position = null; anchor.focus(); dispatch("action", { id: event.detail.id, anchor }); }} />
{/if}

<style>
  .overflow-trigger { display: inline-flex; align-items: center; justify-content: center; flex: none; width: 28px; height: 28px;
    border: 1px solid transparent; border-radius: 5px; background: transparent; color: var(--text-2); cursor: pointer; padding: 4px; }
  .overflow-trigger:hover, .overflow-trigger[aria-expanded="true"] { background: var(--surface-3, #e5e7eb); border-color: var(--border-strong); }
  .overflow-trigger:focus-visible { outline: 2px solid var(--text-2); outline-offset: 1px; }
</style>
