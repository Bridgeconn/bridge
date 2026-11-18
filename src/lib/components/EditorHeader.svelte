<script lang="ts">
  /** The Verses panel's header (#489; restyled 2026-11-15). Left: "Chapter",
   *  the chapter picker (a button that opens a grid of the book's chapters),
   *  "of N", and the previous / next arrows. Then the Go to box. Right: the
   *  text size (A− A+), the USFM markers toggle and the legend of the verse
   *  list's marks (VerseLegend.svelte). Every control is an icon
   *  button in the app's common style with an instant hint. The book is in
   *  the top bar (BookPicker.svelte); the layout picker, with Reset, is
   *  there too (LayoutMenu.svelte). In a narrow panel the words go first, then Go to
   *  shrinks; the row never wraps. */
  import { onDestroy, tick } from "svelte";
  import UiIcon from "./UiIcon.svelte";
  import VerseLegend from "./VerseLegend.svelte";
  import { tooltip } from "../tooltip";
  import { TEXT_SCALES, bumpTextScale, rawView, textScale } from "../editorPrefs";
  import { project, currentChapter, bookAssignments, localUserId, assignedToMe } from "../stores";

  export let onChapterChange: (chapter: string) => void = () => {};
  /** Go to what was typed. Resolves to "" when the editor moved there, or to
   *  the sentence to show (an invalid entry, a chapter or verse not in the
   *  book). The caller validates: it knows the chapters and their verses. */
  export let onGoTo: (typed: string) => Promise<string> | string = () => "";
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
  let header: HTMLElement;
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
    const panel = header.getBoundingClientRect();
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

  $: smallest = $textScale === TEXT_SCALES[0];
  $: largest = $textScale === TEXT_SCALES[TEXT_SCALES.length - 1];
  $: percent = `${Math.round($textScale * 100)}%`;
</script>

<div class="editor-header" bind:this={header}>
  <div class="chapter-nav" role="group" aria-label="Chapter navigation">
    <span class="word" id="editor-chapter-label">Chapter</span>
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
  <span class="rule" aria-hidden="true" />
  <form class="goto" class:invalid={Boolean(gotoError)} on:submit|preventDefault={() => void jump()}>
    <span class="goto-icon" aria-hidden="true"><UiIcon name="follow" /></span>
    <input bind:value={gotoValue} aria-label="Go to" placeholder="Go to verse, e.g. 1:4" autocomplete="off" spellcheck="false"
      use:tooltip={"Type a verse of this chapter (4) or a chapter and verse (1:4), then press Enter"}
      aria-invalid={gotoError ? "true" : undefined} aria-describedby={gotoError ? "editor-goto-error" : undefined}
      on:input={clearGoToError}
      on:keydown={(event) => { if (event.key === "Escape" && (gotoError || gotoValue)) { gotoValue = ""; clearGoToError(); } }} />
    {#if gotoError}<p id="editor-goto-error" class="goto-error" role="alert">{gotoError}</p>{/if}
  </form>
  <span class="tools">
    <span class="text-size" role="group" aria-label="Text size">
      <button type="button" class="ui-icon-btn hdr-btn size-btn smaller" disabled={smallest} aria-label="Smaller text"
        use:tooltip={smallest ? `Smallest text size (${percent})` : `Smaller text (now ${percent})`}
        on:click={() => bumpTextScale(-1)}>A<span aria-hidden="true">−</span></button>
      <button type="button" class="ui-icon-btn hdr-btn size-btn larger" disabled={largest} aria-label="Larger text"
        use:tooltip={largest ? `Largest text size (${percent})` : `Larger text (now ${percent})`}
        on:click={() => bumpTextScale(1)}>A<span aria-hidden="true">+</span></button>
    </span>
    <button type="button" class="ui-icon-btn hdr-btn raw-toggle" aria-pressed={$rawView} aria-label="Raw USFM"
      use:tooltip={$rawView ? "USFM markers are showing (\\v, \\f, \\w …). Click for the clean text"
        : "Show USFM markers: the verse text as stored (\\v, \\f, \\w …)"}
      on:click={() => rawView.update((on) => !on)}><UiIcon name="usfm" /></button>
    <VerseLegend />
    <slot />
  </span>
</div>

<style>
  /* The header is outside the verse list's scroller, so the list scrolls
     under it; `sticky` covers a pane whose own column scrolls. One row that
     never wraps. It is a size container: in a narrow group the words
     ("Chapter", "of N") go first, then the Go to box shrinks; the picker,
     the arrows and the tools keep their size. */
  .editor-header { position: sticky; top: 0; z-index: 2; container-type: inline-size; display: flex; align-items: center; gap: 8px; height: 36px; min-height: 36px; flex: none;
    box-sizing: border-box; padding: 0 10px; border-bottom: 1px solid var(--border); background: var(--surface); }
  .chapter-nav { display: flex; align-items: center; gap: 6px; flex: none; }
  /* 36 px, the height of every side panel's bar (PanelHeader), so the line
     under it meets the neighbour's in a split. */
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
  .rule { width: 1px; height: 18px; flex: none; background: var(--border); }
  .goto { position: static; display: flex; align-items: center; flex: 0 1 190px; min-width: 64px; height: 26px; margin: 0; box-sizing: border-box;
    border: 1px solid var(--border); border-radius: 8px; background: var(--surface-2); transition: border-color .15s, box-shadow .15s, background .15s; }
  .goto:focus-within { border-color: var(--accent); background: var(--surface); box-shadow: 0 0 0 3px var(--accent-bg); }
  .goto.invalid { border-color: var(--danger); }
  .goto-icon { display: grid; place-items: center; flex: none; width: 26px; color: var(--text-3); }
  .goto-icon :global(svg) { width: 14px; height: 14px; }
  .goto input { flex: 1; min-width: 0; height: 100%; box-sizing: border-box; padding: 0 8px 0 0; border: 0; background: transparent; color: var(--text);
    font: inherit; font-size: var(--fs-2xs); line-height: 1; outline: none; }
  /* Under the header, over the verses: the header keeps its height. It is
     placed against the header (the sticky box), not the Go to box, and wraps
     inside the editor column: the column clips what leaves it, and anchored
     to the box the sentence ran out of the column's right edge and was cut. */
  .goto-error { position: absolute; top: calc(100% + 4px); left: 8px; right: 8px; z-index: 3; margin: 0; white-space: normal; overflow-wrap: anywhere; padding: 5px 8px;
    border: 1px solid var(--danger); border-radius: 6px; background: var(--danger-bg); color: var(--danger); font-size: var(--fs-2xs); font-weight: 600; line-height: 1.35; box-shadow: 0 4px 12px rgba(0,0,0,.12); }
  .tools { margin-left: auto; display: inline-flex; align-items: center; gap: 6px; flex: none; }
  .text-size { display: inline-flex; align-items: center; gap: 2px; }
  .size-btn { display: inline-flex; align-items: baseline; justify-content: center; gap: 1px; font: inherit; font-weight: 700; line-height: 28px; }
  .size-btn.smaller { font-size: var(--fs-3xs); }
  .size-btn.larger { font-size: var(--fs-sm); }
  .size-btn span { font-size: var(--fs-3xs); font-weight: 700; }
  /* A switch, styled as the left rail's icons are: grey when off, the accent
     colour when on, and a grey (not blue) hover, so the hover never looks
     like "on". */
  .raw-toggle:hover:not(:disabled) { background: var(--bg); color: var(--text); }
  .raw-toggle[aria-pressed="true"], .raw-toggle[aria-pressed="true"]:hover:not(:disabled) { color: var(--accent); }
  @container (max-width: 520px) {
    .word { display: none; }
    .rule { display: none; }
  }
  @container (max-width: 400px) {
    .editor-header { gap: 4px; padding: 0 6px; }
    .goto-icon { display: none; }
    .goto input { padding-left: 8px; }
    .text-size { display: none; }
  }
  @media (prefers-reduced-motion: reduce) { .chapter-trigger, .chapter-trigger :global(svg), .goto { transition: none; } }
</style>
