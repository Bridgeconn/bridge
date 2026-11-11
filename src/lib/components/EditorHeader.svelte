<script lang="ts">
  /** The editor panel's header (#489): the chapter, which stays at the top of
   *  the panel while the verses scroll under it, the Raw USFM toggle (it was an
   *  overflow-menu entry), and the panel's remaining tools in the slot. */
  import { rawView } from "../editorPrefs";

  export let chapter = "";
  /** How many chapters the book has; "?" until a project is open. */
  export let total: number | string = "?";
</script>

<div class="editor-header">
  <button type="button" class="raw-toggle" aria-pressed={$rawView}
    title={$rawView ? "Showing the verse text as stored, USFM markers and all; click for the clean text"
      : "Show the verse text as stored, USFM markers and all"}
    on:click={() => rawView.update((on) => !on)}>Raw USFM</button>
  <h2>Chapter {chapter} of {total}</h2>
  <span class="tools"><slot /></span>
</div>

<style>
  /* The header is outside the verse list's scroller, so the list scrolls
     under it. `sticky` covers the one case where the header's own column
     scrolls: an arranged layout taller than the window (EditorWorkspace's
     .layout-scroll). */
  .editor-header { position: sticky; top: 0; z-index: 2; display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
    align-items: center; gap: 8px; min-height: 36px; flex: none; padding: 0 8px; border-bottom: 1px solid var(--border); background: var(--surface-2); }
  h2 { text-align: center; font-size: var(--fs-xs); font-weight: 600; margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tools { justify-self: end; display: inline-flex; align-items: center; }
  .raw-toggle { justify-self: start; height: 24px; box-sizing: border-box; padding: 0 8px; border: 1px solid var(--border-strong); border-radius: 999px;
    background: var(--surface); color: var(--text-2); font: inherit; font-size: var(--fs-2xs); font-weight: 650; line-height: 1; white-space: nowrap; cursor: pointer; }
  .raw-toggle:hover { color: var(--text); }
  .raw-toggle[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: #fff; }
  .raw-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
</style>
