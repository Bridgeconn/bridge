<script lang="ts">
  // #379 (Benz's item 7): the one header bar every editor side panel shows,
  // with a line under it. Since #519 it is the Verses header's bar
  // (EditorHeader): the same height, padding and icon size, the title, the
  // panel's own actions (text size, the follow switch, Change, the open
  // count) in the slot, then one tool, "Move to separate window", as the Word
  // alignment tab has it. The bar has no drag handle, no tools menu and no
  // Close: the panel's tab is what is dragged and closed (EditorTabs), and
  // the left rail opens it again.
  //
  // A panel may put something at the bar's left (the `lead` slot: a reference
  // tab's chapter picker and arrows, as on the Verses header). The title is
  // then centred in the room between the two sides; with no lead it starts
  // the bar.
  //
  // Each panel mounts this as its first child rather than SidePanel drawing
  // it: a Svelte 4 slot can be filled only by the component that writes the
  // markup, and the actions are bound to each panel's own state (its follow
  // switch), which the column cannot reach. The bar is the same component in
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

<!-- `data-chapter-bounds`: a chapter picker in the lead places its grid inside this bar's width. -->
<div class="panel-bar" data-panel-bar={id} data-chapter-bounds>
  {#if $$slots.lead}
    <div class="panel-lead"><slot name="lead" /></div>
  {/if}
  <h2 class="panel-title" class:centred={$$slots.lead} title={hint || title}>{title}</h2>
  {#if $$slots.default}
    <div class="panel-actions"><slot /></div>
  {/if}
  {#if !native}
    <button type="button" class="ui-icon-btn panel-tool" aria-label="Move to separate window" disabled={!desktop}
      use:tooltip={desktop ? `Move ${label} to a separate window` : "A separate window needs the desktop app"}
      on:click={detach}><UiIcon name="detach" /></button>
  {/if}
</div>

<style>
  /* The Verses header's bar (EditorHeader): 36px, so the line under it meets
     the neighbour's in a split, 10px from the edge, 8px between its parts. One
     row that never wraps: it is a size container, so a panel hides what it can
     spare of its own actions in a narrow group (ReferencePanel's text size),
     and the title gives way first, with an ellipsis. */
  .panel-bar { container: panel-bar / inline-size; flex-shrink: 0; display: flex; align-items: center; gap: 8px; min-width: 0; padding: 0 10px;
    box-sizing: border-box; height: 36px; min-height: 36px;
    border-bottom: 1px solid var(--border); background: var(--surface); color: var(--text-2); font-size: var(--fs-2xs); }
  .panel-lead { display: flex; align-items: center; flex: none; min-width: 0; }
  .panel-title { flex: 1; min-width: 0; margin: 0; font-size: var(--fs-xs); font-weight: 700; text-align: left; color: var(--text);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .panel-title.centred { text-align: center; }
  .panel-actions { display: flex; align-items: center; gap: 6px; flex-shrink: 0; min-width: 0; }
  /* A worded button in the slot is 24px high; an icon button is the header's 28px. */
  .panel-actions :global(button:not(.info-btn):not(.ui-icon-btn)) { box-sizing: border-box; height: 24px; padding-top: 0; padding-bottom: 0; }
  /* Every icon button of the bar, the panel's own and the tool: the app's
     icon button (index.css .ui-icon-btn) at the Verses header's size, 28px
     with a 16px icon. */
  .panel-actions :global(.ui-icon-btn), .panel-tool { width: 28px; height: 28px; min-height: 28px; border-radius: 7px; }
  .panel-actions :global(.ui-icon-btn svg), .panel-tool :global(svg) { width: 16px; height: 16px; }
  /* A switch (the follow switch), styled as the Verses header's Raw USFM: grey
     when off, the accent colour when on, and a grey (not blue) hover, so the
     hover never looks like "on". */
  .panel-actions :global(.ui-icon-btn[aria-pressed]:hover:not(:disabled)) { background: var(--bg); color: var(--text); }
  .panel-actions :global(.ui-icon-btn[aria-pressed="true"]), .panel-actions :global(.ui-icon-btn[aria-pressed="true"]:hover:not(:disabled)) { color: var(--accent); }
</style>
