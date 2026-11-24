<script lang="ts">
  // #379 (Benz's item 7): the one header bar every editor side panel shows,
  // with a line under it. Since #519 it is the Verses header's bar
  // (EditorHeader): the same height, padding and icon size, the title on the
  // left, the panel's own actions (follow box, Change, the open count) in the
  // slot, then one tool, "Move to separate window", as the Word alignment tab
  // has it. The bar has no drag handle, no tools menu and no Close: the
  // panel's tab is what is dragged and closed (EditorTabs), and the left rail
  // opens it again.
  //
  // Each panel mounts this as its first child rather than SidePanel drawing
  // it: a Svelte 4 slot can be filled only by the component that writes the
  // markup, and the actions are bound to each panel's own state (its follow
  // box), which the column cannot reach. The bar is the same component in
  // every panel, so every panel gets the same header.
  import { getContext } from "svelte";
  import { tooltip } from "../tooltip";
  import UiIcon from "./UiIcon.svelte";
  import { setSidePanel } from "../editorPrefs";
  import type { SidePanelId } from "../editorPrefs";

  export let id: SidePanelId;
  /** The bar's text, e.g. "Source · Hebrew / Aramaic", "Review PHP 1:6". */
  export let title: string;
  /** What the tool moves, for its hint: "Move {label} to a separate window". */
  export let label: string = title;
  /** The title's tooltip, where the bar's text is cut or stands for a path. */
  export let hint: string = "";

  // In its own window (2026-11-14) the bar has no tool: the window's title
  // bar closes it, and it comes back as a tab.
  const native = getContext<{ dock: () => void; close: () => void } | undefined>("panel-window");
  // A separate window is the desktop app's: in a browser the tool is there, off.
  const desktop = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

  function detach(): void {
    setSidePanel(id, { detached: true, open: true });
  }
</script>

<div class="panel-bar" data-panel-bar={id}>
  <h2 class="panel-title" title={hint || title}>{title}</h2>
  {#if $$slots.default}
    <div class="panel-actions"><slot /></div>
  {/if}
  {#if !native}
    <button type="button" class="panel-tool" aria-label="Move to separate window" disabled={!desktop}
      use:tooltip={desktop ? `Move ${label} to a separate window` : "A separate window needs the desktop app"}
      on:click={detach}><UiIcon name="detach" /></button>
  {/if}
</div>

<style>
  /* The Verses header's bar (EditorHeader): 36px, so the line under it meets
     the neighbour's in a split, 10px from the edge, 8px between its parts. One
     row that never wraps: it is a size container, so a panel hides what it can
     spare of its own actions in a narrow group (ReferencePanel's "follow"),
     and the title gives way first, with an ellipsis. */
  .panel-bar { container: panel-bar / inline-size; flex-shrink: 0; display: flex; align-items: center; gap: 8px; min-width: 0; padding: 0 10px;
    box-sizing: border-box; height: 36px; min-height: 36px;
    border-bottom: 1px solid var(--border); background: var(--surface); color: var(--text-2); font-size: var(--fs-2xs); }
  .panel-actions :global(button:not(.info-btn)) { box-sizing: border-box; height: 24px; padding-top: 0; padding-bottom: 0; }
  .panel-title { flex: 1; min-width: 0; margin: 0; font-size: var(--fs-xs); font-weight: 700; text-align: left; color: var(--text);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .panel-actions { display: flex; align-items: center; gap: 6px; flex-shrink: 0; min-width: 0; }
  /* The header's icon button, as the Word alignment tab's tools: 28px, a 16px
     icon, grey, a grey hover. */
  .panel-tool { flex: none; display: grid; place-items: center; width: 28px; height: 28px; padding: 0; border: 0; border-radius: 7px;
    background: transparent; color: var(--text-2); cursor: pointer; transition: color .15s, background .15s; }
  .panel-tool :global(svg) { width: 16px; height: 16px; }
  .panel-tool:hover:not(:disabled) { background: var(--bg); color: var(--text); }
  .panel-tool:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .panel-tool:disabled { opacity: .45; cursor: default; }
  @media (prefers-reduced-motion: reduce) { .panel-tool { transition: none; } }
</style>
