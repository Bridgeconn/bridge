<script lang="ts">
  // Minimize, maximize / restore and close for a window with no native title
  // bar. One component, so the main window (TopBar.svelte) and every separate
  // window (WindowBar.svelte) draw the same three buttons (Joel, 2026-11-14).
  import { onMount } from "svelte";
  import { tooltip } from "../tooltip";
  import { getCurrentWindow } from "@tauri-apps/api/window";

  /** What Close does. Default: ask the window to close. A separate window
   *  passes its own, which tells the main window instead. */
  export let onClose: (() => void) | null = null;
  export let closeDisabled = false;

  let maximized = false;
  onMount(() => {
    let disposed = false;
    let unlisten: (() => void) | undefined;
    try {
      const appWindow = getCurrentWindow();
      const updateMaximized = async () => {
        const value = await appWindow.isMaximized();
        if (!disposed) maximized = value;
      };
      void updateMaximized().catch(console.error);
      void appWindow.onResized(() => { void updateMaximized().catch(console.error); })
        .then((stop) => { if (disposed) stop(); else unlisten = stop; })
        .catch(console.error);
    } catch (error) {
      console.error("Window state is unavailable", error);
    }
    return () => { disposed = true; unlisten?.(); };
  });

  async function windowAction(action: "minimize" | "toggleMaximize" | "close") {
    // Drop focus first: a window coming back from the taskbar gives focus
    // back to the button, and its hint would show with no pointer on it.
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    if (action === "close" && onClose) { onClose(); return; }
    try {
      const appWindow = getCurrentWindow();
      await appWindow[action]();
      if (action === "toggleMaximize") maximized = await appWindow.isMaximized();
    } catch (error) {
      console.error(`Window ${action} failed`, error);
    }
  }
</script>

<div class="window-controls" role="group" aria-label="Window controls">
  <button type="button" aria-label="Minimize window" use:tooltip={"Minimize"} on:click={() => windowAction("minimize")}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10"/></svg></button>
  <button type="button" aria-label={maximized ? "Restore window" : "Maximize window"} use:tooltip={maximized ? "Restore" : "Maximize"} on:click={() => windowAction("toggleMaximize")}><svg viewBox="0 0 16 16" aria-hidden="true">{#if maximized}<path d="M5 5V3h8v8h-2M3 5h8v8H3z"/>{:else}<path d="M3 3h10v10H3z"/>{/if}</svg></button>
  <button type="button" class="window-close" aria-label="Close window" use:tooltip={"Close"} disabled={closeDisabled} on:click={() => windowAction("close")}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3 3 10 10M3 13 13 3"/></svg></button>
</div>

<style>
  .window-controls { display: flex; align-self: stretch; margin-left: 2px; flex-shrink: 0; }
  .window-controls button { display: grid; place-items: center; width: 34px; border: 0; padding: 0; background: transparent; color: var(--text); cursor: pointer; }
  .window-controls button:disabled { opacity: .4; cursor: not-allowed; }
  /* The hover is the Settings icon's: a 26 px rounded square in the accent
     colours (danger for Close), drawn on the glyph. The button itself keeps
     the bar's full height, so the window's top-right corner still closes. */
  .window-controls svg { box-sizing: content-box; width: 13px; height: 13px; padding: 6.5px; border-radius: 6px; fill: none; stroke: currentColor; stroke-width: 1.2; transition: color .15s, background .15s; }
  .window-controls button:hover:not(:disabled) svg, .window-controls button:focus-visible svg { color: var(--accent); background: var(--accent-bg); }
  .window-controls .window-close:hover:not(:disabled) svg, .window-controls .window-close:focus-visible svg { color: var(--danger); background: var(--danger-bg); }
  .window-controls button:focus-visible { outline: 2px solid var(--accent); outline-offset: -3px; }
  @media (prefers-reduced-motion: reduce) {
    .window-controls svg { transition: none; }
  }
  @media (max-width: 760px) {
    .window-controls { margin-left: 0; }
    .window-controls button { width: 32px; }
  }
</style>
