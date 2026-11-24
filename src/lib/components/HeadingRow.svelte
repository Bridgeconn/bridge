<script lang="ts">
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";
  import { bridge } from "../api/bridgeClient";
  import { nudgeLanguageQa } from "../languageQaInline";
  import { checkingProgress, headingsByVerse, targetDir, targetLang, verseKey } from "../stores";
  import { editSaving } from "../verseEditor";
  import type { VerseHeading } from "../types/finding";

  /**
   * One heading above the verse it introduces (#180), and since #507 the way
   * to change its text: a section heading (`\s`), a major one (`\ms`), a
   * reference line under a heading (`\r`), or a psalm's title that stands
   * before verse 1 (`\d`).
   *
   * Reading: an `<h3>` that is a direct child of the verse list, because a
   * heading sticks to the top of that list while its section is read.
   * Editing: a one-line box with the stored text, saved through
   * `heading.edit`, which refuses when the heading changed meanwhile. The
   * marker is never changed here. The heading is not part of any verse row,
   * so nothing in it selects a verse.
   */
  export let chapter: string;
  export let verse: string;
  /** This heading's place among the headings of `verse`. */
  export let index: number;
  export let heading: VerseHeading;

  let editing = false;
  let text = "";
  let saving = false;
  let error = "";
  let warnings: string[] = [];

  $: tag = heading.tag.toLowerCase();
  $: major = tag.startsWith("ms");
  // \r, \mr, \sr: a parallel-passage or range reference under a heading.
  $: reference = tag === "r" || tag === "mr" || tag === "sr";
  // \d: a psalm's title. The translation's own text, not an editorial heading.
  $: title = tag === "d";
  $: kind = title ? "psalm title" : reference ? "reference line" : major ? "major heading" : "heading";
  $: textId = `heading-${chapter}-${verse}-${index}`;
  $: busy = $checkingProgress.running || $editSaving;

  function start(): void {
    text = heading.text;
    error = "";
    warnings = [];
    editing = true;
  }

  function cancel(): void {
    editing = false;
    error = "";
  }

  async function save(): Promise<void> {
    if (saving) return;
    if (text.trim() === heading.text) { cancel(); return; }
    saving = true;
    error = "";
    try {
      const result = await bridge.editHeading(chapter, verse, index, text, heading.text);
      headingsByVerse.update((all) => ({ ...all, [verseKey(chapter, verse)]: result.headings }));
      warnings = result.warnings ?? [];
      editing = false;
      // Language QA reads headings too: its marks for this chapter are stale.
      nudgeLanguageQa();
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      error = message.includes("REVISION_CONFLICT")
        ? "This heading was changed after you started. Your text is kept here: copy it, cancel, and edit the heading again."
        : message;
    } finally {
      saving = false;
    }
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === "Enter") { event.preventDefault(); void save(); }
    else if (event.key === "Escape") { event.preventDefault(); cancel(); }
  }

  function focusOnMount(node: HTMLInputElement) {
    node.focus();
    node.select();
  }
</script>

{#if editing}
  <div class="heading-edit" class:major class:title>
    <span class="heading-marker" aria-hidden="true">{"\\" + heading.tag}</span>
    <input
      type="text" bind:value={text} use:focusOnMount on:keydown={onKeydown} disabled={saving}
      dir={$targetDir} lang={$targetLang} aria-label={`Text of the ${kind}`}
    />
    <button type="button" class="tool save" on:click={() => void save()} disabled={saving || text.trim() === ""}
      use:tooltip={saving ? "Saving…" : "Save (Enter)"} aria-label={`Save the ${kind}`}>✓</button>
    <button type="button" class="tool cancel" on:click={cancel} disabled={saving}
      use:tooltip={"Cancel (Esc)"} aria-label={`Cancel editing the ${kind}`}>✕</button>
    {#if error}<p class="heading-note error" role="alert">{error}</p>{/if}
  </div>
{:else}
  <!-- The name of the heading is its text alone (aria-labelledby), so the
       edit button inside it is not read out as part of the heading. -->
  <h3 class="section-heading" class:major class:reference class:title class:unstuck={reference || title}
    aria-labelledby={textId} lang={$targetLang} dir={$targetDir}>
    <span id={textId} class="heading-text">{heading.text}</span><button
      type="button" class="ui-icon-btn heading-edit-btn" disabled={busy}
      use:tooltip={busy ? "Wait for background checking to finish before editing" : `Edit this ${kind}`}
      aria-label={`Edit the ${kind}: ${heading.text}`}
      on:click|stopPropagation={start}
    ><UiIcon name="rename" /></button>
  </h3>
  {#if warnings.length}
    <p class="heading-note" role="status">Saved, but check the markers: {warnings.join("; ")}</p>
  {/if}
{/if}

<style>
  /* A heading is the team's text, so it uses --font-target like the verses, but
     it is editorial rather than Scripture: no hover, no selection, no findings.
     The extra top margin is what separates one section from the last verse of
     the previous one. */
  .section-heading {
    font-family: var(--font-target);
    font-size: var(--fs-lg);
    font-weight: 700;
    color: var(--text-2, var(--text-3));
    margin: 12px 0 4px;
    padding: 2px 8px;
    line-height: 1.6;
    /* 2026-11-15 (Joel): the heading of the section being read stays at the
       top of the list. Every heading sticks at the same place and a later one
       is drawn over an earlier one, so the next heading replaces it scrolling
       down and the previous one returns scrolling up. */
    position: sticky; top: 0; z-index: 1;
    background: var(--surface);
    box-shadow: 0 1px 0 color-mix(in srgb, var(--border) 55%, transparent);
  }
  .section-heading.major { font-size: var(--fs-xl); text-align: center; }
  /* \r, \mr, \sr (#507): the parallel passage or range under a heading, e.g.
     "(Mark 1:1-8)". Lighter and italic so it reads as a reference, not a
     second heading; and it does not stick, so the heading above it is the one
     that stays at the top of the list instead of being covered by this. */
  .section-heading.reference {
    position: static; margin-top: 0; box-shadow: none;
    font-size: var(--fs-sm); font-weight: 400; font-style: italic;
  }
  /* \d (#507): a psalm's title, before verse 1. It is the translation's own
     text, so it takes the verse's colour and size and is set apart by italic
     alone. It does not stick: it is read once, above the psalm. */
  .section-heading.title {
    position: static; margin-top: 4px; box-shadow: none;
    font-size: calc(var(--fs-xl) * var(--verse-scale, 1)); font-weight: 400; font-style: italic; color: var(--text);
  }
  /* The edit button: faint at rest so the heading leads, clear when the
     heading is pointed at or the button has focus. */
  .heading-edit-btn {
    display: inline-grid; width: 26px; height: 26px; min-height: 26px; margin-inline-start: 6px;
    vertical-align: middle; opacity: .3; font-style: normal;
  }
  .section-heading:hover .heading-edit-btn, .heading-edit-btn:focus-visible { opacity: 1; }
  .heading-edit-btn:disabled { opacity: .2; cursor: not-allowed; }

  .heading-edit {
    display: flex; flex-wrap: wrap; align-items: center; gap: 6px;
    margin: 12px 0 4px; padding: 2px 8px;
  }
  .heading-marker { font-family: var(--font-mono, ui-monospace, monospace); font-size: var(--fs-2xs); color: var(--text-3); }
  .heading-edit input {
    flex: 1; min-width: 0; box-sizing: border-box; padding: 5px 10px;
    font-family: var(--font-target); font-size: var(--fs-lg); font-weight: 700; color: var(--text);
    border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface);
  }
  .heading-edit.major input { font-size: var(--fs-xl); text-align: center; }
  .heading-edit.title input { font-weight: 400; font-style: italic; }
  .heading-edit input:focus { outline: none; border-color: var(--text-3); }
  .heading-edit input:disabled { opacity: .6; }
  .tool {
    width: 30px; height: 30px; padding: 0; flex-shrink: 0; font-size: var(--fs-lg); font-weight: 800;
    border-radius: 7px; border: none; cursor: pointer; display: grid; place-items: center;
  }
  .tool.save { background: var(--accent); color: #fff; }
  .tool.cancel { background: var(--surface-2); color: var(--text-2); border: 1px solid var(--border-strong); }
  .tool:disabled { opacity: .55; cursor: not-allowed; }
  .heading-note { flex-basis: 100%; margin: 2px 8px 0; font-family: var(--font-ui); font-size: var(--fs-2xs); line-height: 1.4; color: var(--warning); }
  .heading-note.error { margin-inline: 0; color: var(--danger); font-size: var(--fs-xs); }
</style>
