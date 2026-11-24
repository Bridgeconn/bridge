<script lang="ts">
  /** Chapter navigation for a panel's header: "Chapter", the chapter picker
   *  (a button that opens a grid of the book's chapters), "of N", and the
   *  previous / next arrows. It was the left of the Verses header
   *  (EditorHeader, #489, restyled 2026-11-15) and is its own component since
   *  #519, when a reference tab's header got the same. Every use acts on the
   *  one open chapter: `onChapterChange` is the caller's chapter switch.
   *
   *  It sits in a size container (the header bar): in a narrow one the words
   *  go, and the picker and arrows keep their size. */
  import { onDestroy, tick } from "svelte";
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";
  import { project, currentChapter, bookAssignments, localUserId, assignedToMe } from "../stores";

  export let onChapterChange: (chapter: string) => void = () => {};
  /* Previous/next chapter (issue #53). "Previous" and "next" are defined by
     position in the same list the picker shows, not by numeric value, so
     stepping always agrees with what the reader can see -- and a book whose
     chapters are not a clean 1..n run still steps sensibly. Both routes call
     onChapterChange, so they follow whatever the picker already does. */
  $: chapters = $project?.chapters ?? [];
  $: chapterIndex = chapters.indexOf($currentChapter);
  $: hasPreviousChapter = chapterIndex > 0;
  $: hasNextChapter = chapterIndex >= 0 && chapterIndex < chapters.length - 1;

  function stepChapter(delta: -1 | 1): void {
    const target = chapters[chapterIndex + delta];
    if (target !== undefined) onChapterChange(target);
  }

  // The chapter picker: a grid, drawn `fixed` so the panel's scroller does
  // not clip it, but sized and placed inside the panel: it never covers the
  // group beside it. Up to 8 columns; fewer in a narrow panel.
  const MAX_COLUMNS = 8;
  let columns = MAX_COLUMNS;
  let root: HTMLElement;
  let pickerOpen = false;
  let pickerRoot: HTMLElement;
  let pickerTrigger: HTMLButtonElement;
  let pickerGrid: HTMLElement;
  let pickerPlace = "";
  let active = 0;
  $: mine = (chapter: string): boolean => assignedToMe($bookAssignments, chapter, $localUserId);

  async function openPicker(): Promise<void> {
    if (!chapters.length) return;
    const rect = pickerTrigger.getBoundingClientRect();
    // The header bar it stands in is the panel's width.
    const panel = (root.closest<HTMLElement>("[data-chapter-bounds]") ?? root.parentElement ?? root).getBoundingClientRect();
    // 34 px cells, 4 px gaps, 8 px padding and a 1 px border each side, and
    // 8 px for the scrollbar, so a long book's grid has no empty strip.
    const room = Math.max(0, panel.width - 12);
    columns = Math.max(2, Math.min(MAX_COLUMNS, chapters.length, Math.floor((room - 26 + 4) / 38)));
    const width = columns * 38 - 4 + 26;
    const left = Math.max(panel.left + 6, Math.min(rect.left, panel.right - 6 - width));
    pickerPlace = `left:${left}px;top:${rect.bottom + 4}px;width:${width}px;max-height:${Math.max(140, window.innerHeight - rect.bottom - 16)}px`;
    active = Math.max(0, chapterIndex);
    pickerOpen = true;
    await focusActive();
  }
  function closePicker(refocus: boolean): void {
    if (!pickerOpen) return;
    pickerOpen = false;
    if (refocus) pickerTrigger?.focus();
  }
  function choose(chapter: string): void {
    closePicker(true);
    if (chapter !== $currentChapter) onChapterChange(chapter);
  }
  async function focusActive(): Promise<void> {
    await tick();
    const cell = pickerGrid?.querySelector<HTMLElement>(`[data-index="${active}"]`);
    cell?.focus();
    cell?.scrollIntoView?.({ block: "nearest" });
  }
  function onGridKey(event: KeyboardEvent): void {
    const last = chapters.length - 1;
    const to = event.key === "ArrowRight" ? Math.min(last, active + 1) : event.key === "ArrowLeft" ? Math.max(0, active - 1)
      : event.key === "ArrowDown" ? Math.min(last, active + columns) : event.key === "ArrowUp" ? Math.max(0, active - columns)
      : event.key === "Home" ? 0 : event.key === "End" ? last : -1;
    if (to >= 0) { event.preventDefault(); active = to; void focusActive(); }
    else if (event.key === "Tab") closePicker(false);
  }
  function onDocumentPointer(event: Event): void {
    if (pickerOpen && pickerRoot && !pickerRoot.contains(event.target as Node)) closePicker(false);
  }
  function onDocumentKey(event: KeyboardEvent): void {
    if (pickerOpen && event.key === "Escape") { event.preventDefault(); closePicker(true); }
  }
  const onResize = () => closePicker(false);
  document.addEventListener("mousedown", onDocumentPointer);
  // The top bar is a window-drag region: the shell takes a mousedown there
  // before the page sees it, so a click on the bar is caught as a pointerdown.
  document.addEventListener("pointerdown", onDocumentPointer, true);
  document.addEventListener("keydown", onDocumentKey);
  window.addEventListener("resize", onResize);
  onDestroy(() => {
    document.removeEventListener("mousedown", onDocumentPointer);
    document.removeEventListener("pointerdown", onDocumentPointer, true);
    document.removeEventListener("keydown", onDocumentKey);
    window.removeEventListener("resize", onResize);
  });
</script>

<div class="chapter-nav" role="group" aria-label="Chapter navigation" bind:this={root}>
  <span class="word">Chapter</span>
  <span class="picker" bind:this={pickerRoot}>
    <button type="button" class="chapter-trigger" class:open={pickerOpen} bind:this={pickerTrigger}
      aria-label={`Chapter ${$currentChapter}: choose a chapter`} aria-haspopup="listbox" aria-expanded={pickerOpen}
      use:tooltip={pickerOpen ? "" : "Choose a chapter"}
      on:click={() => (pickerOpen ? closePicker(false) : void openPicker())}
      on:keydown={(event) => { if (event.key === "ArrowDown" && !pickerOpen) { event.preventDefault(); void openPicker(); } }}>
      <span class="chapter-number">{$currentChapter || "–"}</span><UiIcon name="chevronDown" />
    </button>
    {#if pickerOpen}
      <!-- svelte-ignore a11y-no-static-element-interactions -->
      <div class="chapter-panel" style={pickerPlace} role="listbox" aria-label="Chapters" tabindex="-1"
        bind:this={pickerGrid} on:keydown={onGridKey}>
        {#each chapters as ch, index (ch)}
          <button type="button" class="chapter-cell" class:current={ch === $currentChapter} class:mine={mine(ch)}
            role="option" aria-selected={ch === $currentChapter} data-index={index} tabindex={index === active ? 0 : -1}
            title={mine(ch) ? `Chapter ${ch}: assigned to you` : `Chapter ${ch}`}
            on:focus={() => (active = index)} on:click={() => choose(ch)}>{ch}</button>
        {/each}
      </div>
    {/if}
  </span>
  <span class="word of">of {$project ? chapters.length : "?"}</span>
  <span class="steps">
    <button type="button" class="ui-icon-btn hdr-btn" disabled={!hasPreviousChapter} aria-label="Previous chapter"
      use:tooltip={hasPreviousChapter ? "Previous chapter" : "Already at the first chapter"}
      on:click={() => stepChapter(-1)}><UiIcon name="chevronLeft" /></button>
    <button type="button" class="ui-icon-btn hdr-btn" disabled={!hasNextChapter} aria-label="Next chapter"
      use:tooltip={hasNextChapter ? "Next chapter" : "Already at the last chapter"}
      on:click={() => stepChapter(1)}><UiIcon name="chevronRight" /></button>
  </span>
</div>

<style>
  .chapter-nav { display: flex; align-items: center; gap: 6px; flex: none; }
  .word { font-size: var(--fs-2xs); font-weight: 600; color: var(--text-2); white-space: nowrap; }
  .word:not(.of) { font-size: var(--fs-xs); font-weight: 700; color: var(--text); }
  .picker { display: inline-flex; }
  .chapter-trigger { display: inline-flex; align-items: center; gap: 2px; height: 24px; min-width: 44px; box-sizing: border-box; padding: 0 4px 0 8px;
    border: 1px solid var(--border); border-radius: 7px; background: var(--surface); color: var(--text); font: inherit; font-size: var(--fs-2xs); font-weight: 700;
    line-height: 1; cursor: pointer; transition: color .15s, background .15s, border-color .15s; }
  .chapter-number { flex: 1; text-align: left; }
  .chapter-trigger :global(svg) { width: 14px; height: 14px; flex: none; color: var(--text-3); transition: transform .15s; }
  .chapter-trigger:hover, .chapter-trigger.open { border-color: transparent; background: var(--accent-bg); color: var(--accent); }
  .chapter-trigger:hover :global(svg), .chapter-trigger.open :global(svg) { color: var(--accent); }
  .chapter-trigger.open :global(svg) { transform: rotate(180deg); }
  .chapter-trigger:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
  .chapter-panel { position: fixed; z-index: var(--z-dropdown); box-sizing: border-box; display: grid; grid-template-columns: repeat(auto-fill, 34px); gap: 4px; align-content: start; justify-content: center;
    padding: 8px 4px 8px 8px; overflow-x: hidden; overflow-y: auto; scrollbar-gutter: stable; border: 1px solid var(--border-strong); border-radius: 10px; background: var(--surface); box-shadow: 0 12px 32px rgba(0,0,0,.16); }
  .chapter-cell { position: relative; display: grid; place-items: center; width: 34px; height: 30px; padding: 0; border: 0; border-radius: 6px; background: transparent;
    color: var(--text); font: inherit; font-size: var(--fs-2xs); font-weight: 600; cursor: pointer; }
  .chapter-cell:hover, .chapter-cell:focus-visible { background: var(--accent-bg); color: var(--accent); outline: none; }
  .chapter-cell.current { background: var(--accent); color: #fff; }
  /* Assigned to you: a dot in the cell's corner. */
  .chapter-cell.mine::after { content: ""; position: absolute; top: 3px; right: 3px; width: 5px; height: 5px; border-radius: 50%; background: var(--term); }
  .chapter-cell.current.mine::after { background: #fff; }
  .steps { display: inline-flex; align-items: center; gap: 2px; }
  /* The app's icon button (index.css .ui-icon-btn), at the header's size. */
  .hdr-btn { width: 28px; height: 28px; min-height: 28px; border-radius: 7px; }
  .hdr-btn :global(svg) { width: 16px; height: 16px; }
  /* The header bar is the size container: narrow, the words go first. */
  @container (max-width: 520px) { .word { display: none; } }
  @media (prefers-reduced-motion: reduce) { .chapter-trigger, .chapter-trigger :global(svg) { transition: none; } }
</style>
