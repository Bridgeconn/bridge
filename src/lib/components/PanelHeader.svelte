<script lang="ts">
  // #379 (Benz's item 7): the one header bar every editor side panel shows,
  // with a line under it. Title on the left, the panel's own actions (follow
  // box, Change, Pause, the (i)) in the slot, then the layout controls (#389:
  // ◂ ▸ move the column, ⧉ undocks it into a box inside the window, ⇲ docks
  // it back), and a ✕ Close on the right that does what the rail button does.
  // One padding, one title size, one background.
  //
  // Each panel mounts this as its first child rather than SidePanel drawing
  // it: a Svelte 4 slot can be filled only by the component that writes the
  // markup, and the actions are bound to each panel's own state (its follow
  // box, its Pause), which the column cannot reach. The bar is the same
  // component in every panel, so every panel gets the same header.
  import { dockSidePanel, movePanel, setSidePanel, sidePanelOrder, sidePanels, undockSidePanel } from "../editorPrefs";
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
  /** The ◂ ▸ / undock controls: only where the bar heads an editor column or
   *  an undocked box, not the Language QA box of the other screens. */
  export let layout = true;

  $: at = $sidePanelOrder.indexOf(id);
  $: floating = Boolean($sidePanels[id].float);

  function close(): void {
    if (onClose) onClose();
    else setSidePanel(id, { open: false });
  }

  /** Undock where the column stands, so the box appears over its own place. */
  function undock(): void {
    const column = typeof document === "undefined" ? null : document.getElementById(`side-panel-${id}`);
    const rect = column?.getBoundingClientRect();
    undockSidePanel(id, rect && rect.width > 0 ? { x: rect.left, y: rect.top, width: rect.width, height: rect.height } : undefined);
  }
</script>

<div class="panel-bar" data-panel-bar={id}>
  <h2 class="panel-title" title={hint || title}>{title}</h2>
  {#if $$slots.default}
    <div class="panel-actions"><slot /></div>
  {/if}
  {#if layout}
    <div class="panel-layout">
      {#if !floating}
        <button type="button" class="layout-btn" aria-label={`Move ${label} left`} title="Move this panel left"
          disabled={at <= 0} on:click={() => movePanel(id, -1)}>◂</button>
        <button type="button" class="layout-btn" aria-label={`Move ${label} right`} title="Move this panel right"
          disabled={at < 0 || at >= $sidePanelOrder.length - 1} on:click={() => movePanel(id, 1)}>▸</button>
        <button type="button" class="layout-btn" aria-label={`Undock ${label}`}
          title="Undock: show this panel as a box you can move over the text" on:click={undock}>⧉</button>
      {:else}
        <button type="button" class="layout-btn" aria-label={`Dock ${label}`}
          title="Dock: put this panel back in its column" on:click={() => dockSidePanel(id)}>⇲</button>
      {/if}
    </div>
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
  /* #389: the layout controls, the size of Close, no gap between them so the
     bar stays one line at 260px. Plain glyphs (gotcha 9) with the action as
     the accessible name and tooltip. */
  .panel-layout { display: flex; align-items: center; flex-shrink: 0; gap: 0; }
  .layout-btn, .panel-close { flex-shrink: 0; width: 22px; height: 22px; padding: 0; border-radius: 5px; border: 0;
    background: transparent; color: var(--text-3); cursor: pointer; font: inherit; font-size: var(--fs-3xs); line-height: 1; }
  .layout-btn:hover:not(:disabled), .layout-btn:focus-visible,
  .panel-close:hover, .panel-close:focus-visible { background: var(--accent-bg); color: var(--accent); outline: none; }
  .layout-btn:disabled { opacity: .35; cursor: default; }
</style>
