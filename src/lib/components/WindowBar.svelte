<script lang="ts">
  // The title bar of every separate window (Alignment, the four editor panels,
  // Review notes): the mark, the window's name, then the app's own minimize,
  // maximize and close. These windows have no native title bar
  // (tauri.conf.json `decorations: false`), so this is the one Close they
  // have, and the bar is what the window is dragged by (Joel, 2026-11-14).
  import BridgeMark from "./BridgeMark.svelte";
  import WindowControls from "./WindowControls.svelte";

  export let title: string;
  /** Close tells the main window, which hides this one. */
  export let onClose: () => void;
  export let closeDisabled = false;

  const desktop = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
</script>

<div class="window-bar no-print" data-tauri-drag-region data-testid="window-bar">
  <span class="mark" data-tauri-drag-region><BridgeMark size={16} /></span>
  <span class="name" data-tauri-drag-region>{title}</span>
  <div class="grow" data-tauri-drag-region />
  {#if $$slots.default}<div class="tools"><slot /></div>{/if}
  {#if desktop}<WindowControls {onClose} {closeDisabled} />{/if}
</div>

<style>
  /* The main window's bar (TopBar.svelte): 32 px, the same background and line. */
  .window-bar { height: 32px; min-height: 32px; flex-shrink: 0; box-sizing: border-box; display: flex; align-items: center; gap: 8px; min-width: 0; padding: 0 0 0 10px;
    background: var(--bg); border-bottom: 1px solid var(--border); color: var(--text); user-select: none; }
  .mark { display: flex; flex-shrink: 0; filter: drop-shadow(0 1px 2px rgba(47, 111, 237, 0.25)); }
  .name { min-width: 0; font-size: var(--fs-xs); font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .grow { flex: 1; align-self: stretch; min-width: 16px; }
  .tools { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
</style>
