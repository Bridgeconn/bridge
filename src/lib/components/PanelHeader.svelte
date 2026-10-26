<script lang="ts">
  // #379 (Benz's item 7): the one header bar every editor side panel shows,
  // with a line under it. Title on the left, the panel's own actions (follow
  // box, Change, Pause, the (i)) in the slot, a ✕ Close on the right that does
  // what the rail button does. One padding, one title size, one background.
  //
  // Each panel mounts this as its first child rather than SidePanel drawing
  // it: a Svelte 4 slot can be filled only by the component that writes the
  // markup, and the actions are bound to each panel's own state (its follow
  // box, its Pause), which the column cannot reach. The bar is the same
  // component in every panel, so every panel gets the same header.
  import { setSidePanel } from "../editorPrefs";
  import type { SidePanelId } from "../editorPrefs";

  export let id: SidePanelId;
  /** The bar's text, e.g. "Source · Hebrew / Aramaic", "Review PHP 1:6". */
  export let title: string;
  /** What the Close button closes, for its accessible name: "Close {label}". */
  export let label: string = title;
  /** The title's tooltip, where the bar's text is cut or stands for a path. */
  export let hint: string = "";
  /** What Close does when it is not simply closing the column (the floating
   *  Language QA box). Default: close the column, as the rail does. */
  export let onClose: (() => void) | null = null;

  function close(): void {
    if (onClose) onClose();
    else setSidePanel(id, { open: false });
  }
</script>

<div class="panel-bar" data-panel-bar={id}>
  <h2 class="panel-title" title={hint || title}>{title}</h2>
  {#if $$slots.default}
    <div class="panel-actions"><slot /></div>
  {/if}
  <button type="button" class="panel-close" on:click={close}
    aria-label={`Close ${label}`} title="Close (the button on the right-hand rail opens it again)">✕</button>
</div>

<style>
  /* One bar height on every panel (item 6, seen in the 2026-10-26 walk: 41
     to 47px, set by whichever button each panel put in the slot): 8px, a
     24px control row (every slotted button is 24px like Close; the (i)
     keeps its 20px circle), 8px, and the 1px line: 41px, with or without a
     button in the slot. */
  .panel-bar { flex-shrink: 0; display: flex; align-items: center; gap: 8px; min-width: 0; padding: 8px 12px;
    box-sizing: border-box; min-height: 41px;
    border-bottom: 1px solid var(--border); background: var(--surface-2); color: var(--text-2); font-size: var(--fs-2xs); }
  .panel-actions :global(button:not(.info-btn)) { box-sizing: border-box; height: 24px; padding-top: 0; padding-bottom: 0; }
  .panel-title { flex: 1; min-width: 0; margin: 0; font-size: var(--fs-xs); font-weight: 700; color: var(--text);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .panel-actions { display: flex; align-items: center; gap: 6px; flex-shrink: 0; min-width: 0; }
  .panel-close { flex-shrink: 0; width: 22px; height: 22px; padding: 0; border-radius: 5px; border: 0;
    background: transparent; color: var(--text-3); cursor: pointer; font: inherit; font-size: var(--fs-3xs); line-height: 1; }
  .panel-close:hover, .panel-close:focus-visible { background: var(--accent-bg); color: var(--accent); outline: none; }
</style>
