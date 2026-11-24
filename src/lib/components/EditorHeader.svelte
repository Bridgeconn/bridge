<script lang="ts">
  /** The Verses panel's header (#489; restyled 2026-11-15). Left: "Chapter",
   *  the chapter picker (a button that opens a grid of the book's chapters),
   *  "of N", and the previous / next arrows (ChapterNav.svelte, which a
   *  reference tab's header shares since #519). Then the Go to box. Right: the
   *  text size (A− A+, TextSizeButtons.svelte), the USFM markers toggle and
   *  the legend of the verse list's marks (VerseLegend.svelte). Every control
   *  is an icon button in the app's common style with an instant hint. The
   *  book is in the top bar (BookPicker.svelte); the layout picker, with
   *  Reset, is there too (LayoutMenu.svelte). In a narrow panel the words go
   *  first, then Go to shrinks; the row never wraps. */
  import UiIcon from "./UiIcon.svelte";
  import ChapterNav from "./ChapterNav.svelte";
  import TextSizeButtons from "./TextSizeButtons.svelte";
  import VerseLegend from "./VerseLegend.svelte";
  import { tooltip } from "../tooltip";
  import { rawView, textScale } from "../editorPrefs";

  export let onChapterChange: (chapter: string) => void = () => {};
  /** Go to what was typed. Resolves to "" when the editor moved there, or to
   *  the sentence to show (an invalid entry, a chapter or verse not in the
   *  book). The caller validates: it knows the chapters and their verses. */
  export let onGoTo: (typed: string) => Promise<string> | string = () => "";

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

<!-- `data-chapter-bounds`: the chapter picker's grid is placed inside this bar's width. -->
<div class="editor-header" data-chapter-bounds>
  <ChapterNav {onChapterChange} />
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
    <span class="size-slot"><TextSizeButtons scale={textScale} /></span>
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
     ("Chapter", "of N") go first (ChapterNav), then the Go to box shrinks;
     the picker, the arrows and the tools keep their size. 36 px, the height
     of every side panel's bar (PanelHeader), so the line under it meets the
     neighbour's in a split. */
  .editor-header { position: sticky; top: 0; z-index: 2; container-type: inline-size; display: flex; align-items: center; gap: 8px; height: 36px; min-height: 36px; flex: none;
    box-sizing: border-box; padding: 0 10px; border-bottom: 1px solid var(--border); background: var(--surface); }
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
  .size-slot { display: inline-flex; }
  /* A switch, styled as the left rail's icons are: grey when off, the accent
     colour when on, and a grey (not blue) hover, so the hover never looks
     like "on". */
  .raw-toggle:hover:not(:disabled) { background: var(--bg); color: var(--text); }
  .raw-toggle[aria-pressed="true"], .raw-toggle[aria-pressed="true"]:hover:not(:disabled) { color: var(--accent); }
  @container (max-width: 520px) {
    .rule { display: none; }
  }
  @container (max-width: 400px) {
    .editor-header { gap: 4px; padding: 0 6px; }
    .goto-icon { display: none; }
    .goto input { padding-left: 8px; }
    .size-slot { display: none; }
  }
  @media (prefers-reduced-motion: reduce) { .goto { transition: none; } }
</style>
