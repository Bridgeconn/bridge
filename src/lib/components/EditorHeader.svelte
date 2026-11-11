<script lang="ts">
  /** The editor panel's header (#489). Left to right: the project breadcrumb
   *  (Projects › project › book; it was in the top bar until 2026-11-11), the
   *  chapter in the middle, which stays at the top of the panel while the
   *  verses scroll under it, then the Raw USFM toggle and the panel's
   *  remaining tools (the overflow menu) in the slot. */
  import { rawView } from "../editorPrefs";
  import { project } from "../stores";

  export let chapter = "";
  /** How many chapters the book has; "?" until a project is open. */
  export let total: number | string = "?";
  /** The collection's (or the single book's) name: the dashboard crumb. */
  export let projectName = "";
  export let onGoHome: () => void = () => {};
  export let onGoToDashboard: () => void = () => {};
  export let onBookChange: (path: string) => void = () => {};
  /** A book is being opened: the crumbs that would start another wait. */
  export let bookSwitching = false;

  $: books = $project?.importedProjects ?? [];
</script>

<div class="editor-header">
  <nav class="breadcrumb" aria-label="Navigation">
    <button type="button" class="crumb home" on:click={onGoHome}>Projects</button>
    <span class="crumb-sep" aria-hidden="true">›</span>
    <!-- The one crumb of no fixed length: it gives way first, cut with an
         ellipsis, its full name in the tooltip. -->
    <button type="button" class="crumb project" title={projectName} on:click={onGoToDashboard} disabled={bookSwitching}>{projectName}</button>
    <span class="crumb-sep" aria-hidden="true">›</span>
    {#if $project && books.length > 1}
      <select class="crumb-select" aria-label="Book" value={$project.path} disabled={bookSwitching}
        on:change={(event) => onBookChange(event.currentTarget.value)}>
        {#each books as book}
          <option value={book.path}>{book.bookName}</option>
        {/each}
      </select>
    {:else}
      <span class="crumb current" title={$project?.bookName ?? ""}>{$project?.bookName ?? ""}</span>
    {/if}
  </nav>
  <h2>Chapter {chapter} of {total}</h2>
  <span class="tools">
    <button type="button" class="raw-toggle" aria-pressed={$rawView}
      title={$rawView ? "Showing the verse text as stored, USFM markers and all; click for the clean text"
        : "Show the verse text as stored, USFM markers and all"}
      on:click={() => rawView.update((on) => !on)}>Raw USFM</button>
    <slot />
  </span>
</div>

<style>
  /* The header is outside the verse list's scroller, so the list scrolls
     under it. `sticky` covers the one case where the header's own column
     scrolls: an arranged layout taller than the window (EditorWorkspace's
     .layout-scroll). The two side tracks are equal, so the chapter stays in
     the middle whatever the breadcrumb's length. */
  .editor-header { position: sticky; top: 0; z-index: 2; display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
    align-items: center; gap: 8px; min-height: 36px; flex: none; padding: 0 8px; border-bottom: 1px solid var(--border); background: var(--surface-2); }
  h2 { text-align: center; font-size: var(--fs-xs); font-weight: 600; margin: 0; white-space: nowrap; }
  .tools { justify-self: end; display: inline-flex; align-items: center; gap: 4px; }
  /* A long project name truncates; it never pushes the chapter or the tools
     out: the track is minmax(0, 1fr), the row clips, and only .project shrinks. */
  .breadcrumb { justify-self: start; display: flex; align-items: center; gap: 2px; min-width: 0; max-width: 100%; overflow: hidden; }
  .crumb { border: 0; background: transparent; color: var(--text-2); font: inherit; font-size: var(--fs-xs); font-weight: 600; padding: 3px 5px; border-radius: 6px; cursor: pointer; white-space: nowrap; flex: 0 0 auto; }
  .crumb.project { flex: 0 1 auto; min-width: 2.5em; overflow: hidden; text-overflow: ellipsis; }
  .crumb:hover:not(:disabled) { background: var(--surface); color: var(--text); }
  .crumb:disabled { cursor: not-allowed; opacity: 0.6; }
  .crumb.current { color: var(--text); cursor: default; flex: 0 1 auto; min-width: 2.5em; overflow: hidden; text-overflow: ellipsis; }
  .crumb.current:hover { background: transparent; }
  .crumb-sep { color: var(--text-3); font-size: var(--fs-xs); flex: none; }
  .crumb-select { height: 24px; flex: 0 1 auto; min-width: 3.5em; max-width: 160px; border: 1px solid transparent; border-radius: 6px; font: inherit; font-size: var(--fs-xs); font-weight: 600; padding: 0 2px; background: transparent; color: var(--text); }
  .crumb-select:hover { background: var(--surface); }
  .crumb:focus-visible, .crumb-select:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .raw-toggle { height: 24px; box-sizing: border-box; padding: 0 8px; border: 1px solid var(--border-strong); border-radius: 999px;
    background: var(--surface); color: var(--text-2); font: inherit; font-size: var(--fs-2xs); font-weight: 650; line-height: 1; white-space: nowrap; cursor: pointer; }
  .raw-toggle:hover { color: var(--text); }
  .raw-toggle[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: #fff; }
  .raw-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
</style>
