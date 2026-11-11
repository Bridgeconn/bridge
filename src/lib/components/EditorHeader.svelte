<script lang="ts">
  /** The editor panel's header (#489). Left to right: the book (the book
   *  switcher in a collection), the chapter picker with its ‹ › steppers and
   *  "of N", the Go to box, then the Raw USFM toggle (an icon) and the
   *  panel's remaining tools (the overflow menu) in the slot. The chapter
   *  picker and Go to were in the top bar until 2026-11-11; the breadcrumb
   *  that was here that morning is gone (the project name is in the top bar,
   *  Close editor and Close project in its File menu). */
  import UiIcon from "./UiIcon.svelte";
  import { rawView } from "../editorPrefs";
  import { project, currentChapter, bookAssignments, localUserId, assignedToMe } from "../stores";

  export let onBookChange: (path: string) => void = () => {};
  export let onChapterChange: (chapter: string) => void = () => {};
  /** Go to what was typed. Resolves to "" when the editor moved there, or to
   *  the sentence to show (an invalid entry, a chapter or verse not in the
   *  book). The caller validates: it knows the chapters and their verses. */
  export let onGoTo: (typed: string) => Promise<string> | string = () => "";
  /** A book is being opened: the book switcher would start another wait. */
  export let bookSwitching = false;

  $: books = $project?.importedProjects ?? [];

  /* Previous/next chapter (issue #53). "Previous" and "next" are defined by
     position in the same list the dropdown renders, not by numeric value, so
     stepping always agrees with what the reader can see -- and a book whose
     chapters are not a clean 1..n run still steps sensibly. Both routes call
     onChapterChange, so they follow whatever the dropdown already does. */
  $: chapters = $project?.chapters ?? [];
  $: chapterIndex = chapters.indexOf($currentChapter);
  $: hasPreviousChapter = chapterIndex > 0;
  $: hasNextChapter = chapterIndex >= 0 && chapterIndex < chapters.length - 1;

  function stepChapter(delta: -1 | 1): void {
    const target = chapters[chapterIndex + delta];
    if (target !== undefined) onChapterChange(target);
  }

  let gotoValue = "";
  let gotoError = "";
  let gotoTicket = 0;
  async function jump(): Promise<void> {
    if (!gotoValue.trim()) { gotoError = ""; return; }
    const ticket = ++gotoTicket;
    const typed = gotoValue;
    const error = await onGoTo(typed);
    if (ticket !== gotoTicket) return;
    gotoError = error;
    if (!error) gotoValue = "";
  }
  function clearGoToError(): void {
    gotoTicket += 1;
    gotoError = "";
  }
</script>

<div class="editor-header">
  <div class="where">
    {#if $project && books.length > 1}
      <select class="book-select" aria-label="Book" title={$project.bookName} value={$project.path} disabled={bookSwitching}
        on:change={(event) => onBookChange(event.currentTarget.value)}>
        {#each books as book}
          <option value={book.path}>{book.bookName}</option>
        {/each}
      </select>
    {:else}
      <span class="book-name" title={$project?.bookName ?? ""}>{$project?.bookName ?? ""}</span>
    {/if}
    <div class="chapter-nav" role="group" aria-label="Chapter navigation">
      <button type="button" class="chapter-step" disabled={!hasPreviousChapter}
        title={hasPreviousChapter ? "Previous chapter" : "Already at the first chapter"}
        aria-label="Previous chapter" on:click={() => stepChapter(-1)}>‹</button>
      <!-- Sized by its widest option, never a fixed width (#209). -->
      <select class="chapter-select" aria-label="Chapter" value={$currentChapter}
        on:change={(event) => onChapterChange(event.currentTarget.value)}>
        {#each chapters as ch}
          <option value={ch}>{ch}{assignedToMe($bookAssignments, ch, $localUserId) ? " ●" : ""}</option>
        {/each}
      </select>
      <button type="button" class="chapter-step" disabled={!hasNextChapter}
        title={hasNextChapter ? "Next chapter" : "Already at the last chapter"}
        aria-label="Next chapter" on:click={() => stepChapter(1)}>›</button>
      <span class="of">of {$project ? chapters.length : "?"}</span>
    </div>
  </div>
  <form class="goto" class:invalid={Boolean(gotoError)} on:submit|preventDefault={() => void jump()}>
    <input bind:value={gotoValue} aria-label="Go to" placeholder="Go to 1:4" autocomplete="off" spellcheck="false"
      title="Go to a verse of this chapter (4) or a chapter and verse (1:4); press Enter"
      aria-invalid={gotoError ? "true" : undefined} aria-describedby={gotoError ? "editor-goto-error" : undefined}
      on:input={clearGoToError}
      on:keydown={(event) => { if (event.key === "Escape" && (gotoError || gotoValue)) { gotoValue = ""; clearGoToError(); } }} />
    {#if gotoError}<p id="editor-goto-error" class="goto-error" role="alert">{gotoError}</p>{/if}
  </form>
  <span class="tools">
    <button type="button" class="raw-toggle" aria-pressed={$rawView} aria-label="Raw USFM"
      title={$rawView ? "Raw USFM (on): the verse text as stored, USFM markers and all. Click for the clean text"
        : "Raw USFM: show the verse text as stored, USFM markers and all"}
      on:click={() => rawView.update((on) => !on)}><UiIcon name="code" /></button>
    <slot />
  </span>
</div>

<style>
  /* The header is outside the verse list's scroller, so the list scrolls
     under it. `sticky` covers the one case where the header's own column
     scrolls: an arranged layout taller than the window (EditorWorkspace's
     .layout-scroll). One row that never wraps: at the editor column's
     narrowest the book gives way first (cut with an ellipsis), then the Go
     to box; the chapter picker and the tools keep their size. */
  .editor-header { position: sticky; top: 0; z-index: 2; display: flex; align-items: center; gap: 6px; min-height: 36px; flex: none;
    padding: 0 8px; border-bottom: 1px solid var(--border); background: var(--surface-2); }
  .where { display: flex; align-items: center; gap: 6px; min-width: 0; flex: 0 1 auto; }
  .book-select, .chapter-select { height: 24px; box-sizing: border-box; border: 1px solid var(--border); border-radius: 6px; font: inherit;
    font-size: var(--fs-xs); font-weight: 600; line-height: 1; padding: 0 2px; background: var(--surface); color: var(--text); }
  .book-select { flex: 0 1 auto; min-width: 3.5em; max-width: 150px; text-overflow: ellipsis; }
  .book-name { flex: 0 1 auto; min-width: 2.5em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--fs-xs); font-weight: 600; color: var(--text); }
  .chapter-nav { display: flex; align-items: center; gap: 2px; flex: none; }
  .chapter-select { flex: none; width: auto; min-width: 40px; }
  .chapter-step { height: 24px; width: 20px; flex: none; box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center;
    font: inherit; font-size: var(--fs-sm); line-height: 1; padding: 0; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text); cursor: pointer; }
  .chapter-step:hover:not(:disabled), .chapter-step:focus-visible { border-color: var(--border-strong); background: var(--surface-2); }
  .chapter-step:disabled { opacity: .4; cursor: not-allowed; }
  .of { margin-left: 3px; font-size: var(--fs-xs); font-weight: 600; color: var(--text-2); white-space: nowrap; }
  .goto { position: relative; flex: 1 1 64px; min-width: 56px; max-width: 120px; margin: 0; }
  .goto input { width: 100%; height: 24px; box-sizing: border-box; padding: 0 6px; border: 1px solid var(--border); border-radius: 6px;
    background: var(--surface); color: var(--text); font: inherit; font-size: var(--fs-xs); line-height: 1; }
  .goto input:focus-visible { outline: 2px solid var(--accent); outline-offset: -1px; }
  .goto.invalid input { border-color: var(--danger); }
  /* Under the box, over the verses: the header keeps its height. */
  .goto-error { position: absolute; top: calc(100% + 4px); left: 0; z-index: 3; width: max-content; max-width: 240px; margin: 0; padding: 5px 8px;
    border: 1px solid var(--danger); border-radius: 6px; background: var(--danger-bg); color: var(--danger); font-size: var(--fs-2xs); font-weight: 600; line-height: 1.35; box-shadow: 0 4px 12px rgba(0,0,0,.12); }
  .tools { margin-left: auto; display: inline-flex; align-items: center; gap: 4px; flex: none; }
  .book-select:focus-visible, .chapter-select:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .raw-toggle { display: grid; place-items: center; width: 26px; height: 24px; box-sizing: border-box; padding: 0; border: 1px solid transparent; border-radius: 6px;
    background: transparent; color: var(--text-2); cursor: pointer; }
  .raw-toggle :global(svg) { width: 16px; height: 16px; }
  .raw-toggle:hover { color: var(--text); background: var(--surface); border-color: var(--border); }
  .raw-toggle[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: #fff; }
  .raw-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
</style>
