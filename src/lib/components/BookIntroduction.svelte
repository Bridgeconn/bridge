<script lang="ts">
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";
  import { bridge } from "../api/bridgeClient";
  import { checkingProgress, currentChapter, project, targetDir, targetLang } from "../stores";
  import { introOpen } from "../editorPrefs";
  import { editSaving } from "../verseEditor";
  import { plainToUtf16 } from "../utils/verseDisplay";
  import { styleClasses, withStyleSpans } from "../utils/verseStyles";
  import { withNoteMarkers, type VersePiece } from "../utils/usfmNotes";
  import type { IntroEntry } from "../types/finding";

  /**
   * The book's introduction above its first chapter (#507): `\imt`, `\is`,
   * `\ip`, `\iot`, `\io1` and their kin, in the order the book has them.
   *
   * The engine reads the lines (`book.introduction`) and says what each one
   * shows, exactly as it does for a verse: plain text, the character styles
   * in it (`\bk`, `\ior`, `\k`) and any footnote lifted out. This component
   * only draws that; it never parses USFM. A line is edited as its stored
   * string, like a verse, and saved through `book.introduction.edit`, which
   * refuses when the line changed meanwhile. A line's marker is not changed
   * here and no line is added or removed.
   *
   * The introduction is not Scripture and is not part of any verse: nothing
   * in it selects a verse, is checked, or is offered for alignment.
   */
  let entries: IntroEntry[] = [];
  let loadedFor = "";
  let editingIndex: number | null = null;
  let text = "";
  let saving = false;
  let error = "";
  /** Marker problems the engine saw in the last saved line, by entry index. */
  let warnings: { index: number; items: string[] } | null = null;

  $: bookKey = $project ? `${$project.path}\n${$project.bookId}` : "";
  $: if (bookKey !== loadedFor) void load(bookKey);
  $: firstChapter = $project?.chapters?.[0] ?? "1";
  $: shown = entries.length > 0 && $currentChapter === firstChapter;
  $: busy = $checkingProgress.running || $editSaving;

  async function load(key: string): Promise<void> {
    loadedFor = key;
    entries = [];
    editingIndex = null;
    warnings = null;
    if (!key) return;
    try {
      const result = await bridge.bookIntroduction();
      // Another book was opened while the engine answered.
      if (loadedFor === key) entries = result?.entries ?? [];
    } catch {
      // A book whose introduction cannot be read simply shows none; the
      // verses below must still open.
      if (loadedFor === key) entries = [];
    }
  }

  /** The line's text as styled pieces and note callouts, from its display. */
  function piecesOf(entry: IntroEntry): VersePiece[] {
    const display = entry.display;
    const styles = display.styles.map((span) => ({
      marker: span.marker, start: plainToUtf16(display, span.start), end: plainToUtf16(display, span.end),
    }));
    const notes = display.notes.map((note) => ({ ...note, position: plainToUtf16(display, note.position) }));
    return withNoteMarkers(
      withStyleSpans([{ text: display.plain, findingIds: [], className: null, title: "", numbers: [] }], styles), notes,
    );
  }

  /** What a line is, in words, for its edit button. */
  function kindOf(tag: string): string {
    if (tag.startsWith("imt")) return "introduction title";
    if (tag.startsWith("is")) return "introduction heading";
    if (tag === "iot") return "outline title";
    if (tag.startsWith("io")) return "outline entry";
    return "introduction paragraph";
  }

  function start(entry: IntroEntry): void {
    editingIndex = entry.index;
    text = entry.text;
    error = "";
    warnings = null;
  }

  function cancel(): void {
    editingIndex = null;
    error = "";
  }

  async function save(entry: IntroEntry): Promise<void> {
    if (saving) return;
    if (text.trim() === entry.text) { cancel(); return; }
    saving = true;
    error = "";
    try {
      const result = await bridge.editIntroduction(entry.index, text, entry.text);
      entries = entries.map((item) => (item.index === entry.index ? result.entry : item));
      warnings = result.warnings?.length ? { index: entry.index, items: result.warnings } : null;
      editingIndex = null;
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      error = message.includes("REVISION_CONFLICT")
        ? "This line was changed after you started. Your text is kept here: copy it, cancel, and edit the line again."
        : message;
    } finally {
      saving = false;
    }
  }

  function onKeydown(event: KeyboardEvent, entry: IntroEntry): void {
    if (event.key === "Escape") { event.preventDefault(); cancel(); }
    else if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); void save(entry); }
  }

  function focusOnMount(node: HTMLTextAreaElement) {
    const resize = () => { node.style.height = "auto"; node.style.height = `${node.scrollHeight + 2}px`; };
    node.addEventListener("input", resize);
    resize();
    node.focus();
    return { destroy: () => node.removeEventListener("input", resize) };
  }
</script>

{#if shown}
  <section class="book-intro" aria-label="Book introduction">
    <button type="button" class="intro-toggle" aria-expanded={$introOpen}
      on:click={() => introOpen.update((open) => !open)}>
      <span class="chevron" aria-hidden="true">{$introOpen ? "▾" : "▸"}</span>
      Introduction
      <span class="count">{entries.length} {entries.length === 1 ? "line" : "lines"}</span>
    </button>
    {#if $introOpen}
      <div class="intro-body" dir={$targetDir} lang={$targetLang}>
        {#each entries as entry (entry.index)}
          {#if editingIndex === entry.index}
            <div class="intro-edit">
              <span class="intro-marker" aria-hidden="true">{"\\" + entry.tag}</span>
              <textarea bind:value={text} use:focusOnMount on:keydown={(event) => onKeydown(event, entry)}
                disabled={saving} dir={$targetDir} lang={$targetLang} rows="1"
                aria-label={`Text of the ${kindOf(entry.tag)}`} />
              <div class="intro-edit-actions">
                <button type="button" class="tool save" on:click={() => void save(entry)}
                  disabled={saving || text.trim() === ""}
                  use:tooltip={saving ? "Saving…" : "Save (Ctrl+Enter)"} aria-label={`Save the ${kindOf(entry.tag)}`}>✓</button>
                <button type="button" class="tool cancel" on:click={cancel} disabled={saving}
                  use:tooltip={"Cancel (Esc)"} aria-label={`Cancel editing the ${kindOf(entry.tag)}`}>✕</button>
              </div>
              {#if error}<p class="intro-note error" role="alert">{error}</p>{/if}
            </div>
          {:else}
            <div class="intro-line il-{entry.tag}" data-intro-tag={entry.tag}>
              <span class="intro-text">{#each piecesOf(entry) as piece}{#if piece.kind === "note"}<button
                    type="button" class="intro-callout"
                    use:tooltip={piece.note.text}
                    aria-label={`${piece.note.kind === "xref" ? "Cross reference" : "Footnote"}: ${piece.note.text}`}
                  >{piece.note.kind === "xref" ? "x" : "f"}</button>{:else if piece.kind === "text"}{#if piece.seg.styles?.length}<span class={styleClasses(piece.seg.styles)}>{piece.seg.text}</span>{:else}{piece.seg.text}{/if}{/if}{/each}</span><button
                type="button" class="ui-icon-btn intro-edit-btn" disabled={busy}
                use:tooltip={busy ? "Wait for background checking to finish before editing" : `Edit this ${kindOf(entry.tag)}`}
                aria-label={`Edit the ${kindOf(entry.tag)}: ${entry.display.plain}`}
                on:click={() => start(entry)}
              ><UiIcon name="rename" /></button>
            </div>
            {#if warnings?.index === entry.index}
              <p class="intro-note" role="status">Saved, but check the markers: {warnings.items.join("; ")}</p>
            {/if}
          {/if}
        {/each}
      </div>
    {/if}
  </section>
{/if}

<style>
  /* Set apart from the verses by a rule and a quieter colour: it is the
     team's text, but it is not Scripture and nothing in it is checked. */
  .book-intro { margin: 8px 0 14px; padding: 0 8px 10px; border-bottom: 1px solid var(--border); }
  .intro-toggle {
    display: inline-flex; align-items: center; gap: 6px; padding: 4px 6px; margin-inline-start: -6px;
    border: 0; border-radius: 6px; background: transparent; cursor: pointer;
    font-family: var(--font-ui); font-size: var(--fs-xs); font-weight: 700; color: var(--text-2);
  }
  .intro-toggle:hover, .intro-toggle:focus-visible { background: var(--accent-bg); color: var(--accent); outline: none; }
  .chevron { font-size: var(--fs-2xs); width: 1em; }
  .count { font-weight: 500; color: var(--text-3); }

  .intro-body {
    font-family: var(--font-target); font-size: calc(var(--fs-lg) * var(--verse-scale, 1));
    line-height: 1.75; color: var(--text-2);
  }
  .intro-line { margin: 2px 0; }
  /* Titles and headings of the introduction. */
  .il-imt, .il-imt1 { font-size: 1.2em; font-weight: 700; text-align: center; margin: 6px 0; color: var(--text); }
  .il-imt2, .il-imt3, .il-imt4, .il-imte, .il-imte1, .il-imte2 { font-weight: 700; text-align: center; margin: 4px 0; }
  .il-is, .il-is1 { font-weight: 700; margin-top: 10px; color: var(--text); }
  .il-is2 { font-weight: 700; font-style: italic; margin-top: 8px; }
  /* Paragraphs: \ip opens with an indent, \im does not, \ipi and \imi are set in. */
  .il-ip { text-indent: 1.2em; }
  .il-ipi { text-indent: 1.2em; padding-inline-start: 1.5em; }
  .il-imi, .il-ipq, .il-imq { padding-inline-start: 1.5em; }
  .il-ipq, .il-imq { font-style: italic; }
  .il-ipr { text-align: end; }
  .il-iq, .il-iq1 { padding-inline-start: 2.5em; text-indent: -1.5em; }
  .il-iq2 { padding-inline-start: 4em; text-indent: -1.5em; }
  .il-iq3 { padding-inline-start: 5.5em; text-indent: -1.5em; }
  .il-ili, .il-ili1 { padding-inline-start: 2.5em; text-indent: -1em; }
  .il-ili2 { padding-inline-start: 4em; text-indent: -1em; }
  .il-iex { font-style: italic; }
  /* The outline: its title, then entries set in one step a level. */
  .il-iot { font-weight: 700; margin-top: 10px; color: var(--text); }
  .il-io, .il-io1 { padding-inline-start: 1.5em; }
  .il-io2 { padding-inline-start: 3em; }
  .il-io3 { padding-inline-start: 4.5em; }
  .il-io4 { padding-inline-start: 6em; }

  /* Character styles inside a line, as the verse list draws them. */
  .intro-text :global(.st-it), .intro-text :global(.st-em), .intro-text :global(.st-bk),
  .intro-text :global(.st-tl), .intro-text :global(.st-bdit) { font-style: italic; }
  .intro-text :global(.st-bd), .intro-text :global(.st-k), .intro-text :global(.st-bdit) { font-weight: 700; }
  .intro-text :global(.st-nd), .intro-text :global(.st-sc) { font-variant-caps: small-caps; }
  .intro-text :global(.st-ior) { white-space: nowrap; }
  .intro-callout {
    font-family: var(--font-ui); font-size: var(--fs-2xs); font-weight: 800; font-style: italic; line-height: 1;
    vertical-align: super; margin: 0 1px; padding: 1px 3px; cursor: help; text-indent: 0;
    border: 1px solid var(--border-strong); border-radius: 3px; background: var(--surface-2); color: var(--text-2);
  }

  /* Faint at rest so the text leads; clear on the line that is pointed at. */
  .intro-edit-btn {
    display: inline-grid; width: 24px; height: 24px; min-height: 24px; margin-inline-start: 6px;
    vertical-align: middle; opacity: .25; text-indent: 0;
  }
  .intro-line:hover .intro-edit-btn, .intro-edit-btn:focus-visible { opacity: 1; }
  .intro-edit-btn:disabled { opacity: .2; cursor: not-allowed; }

  .intro-edit { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 6px; margin: 4px 0; }
  .intro-marker { padding-top: 8px; font-family: var(--font-mono, ui-monospace, monospace); font-size: var(--fs-2xs); color: var(--text-3); }
  .intro-edit textarea {
    flex: 1; min-width: 0; box-sizing: border-box; padding: 6px 10px; resize: none; overflow-y: hidden;
    font: inherit; color: var(--text); border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface);
  }
  .intro-edit textarea:focus { outline: none; border-color: var(--text-3); }
  .intro-edit textarea:disabled { opacity: .6; }
  .intro-edit-actions { display: flex; flex-direction: column; gap: 6px; flex-shrink: 0; }
  .tool {
    width: 30px; height: 30px; padding: 0; font-size: var(--fs-lg); font-weight: 800;
    border-radius: 7px; border: none; cursor: pointer; display: grid; place-items: center;
  }
  .tool.save { background: var(--accent); color: #fff; }
  .tool.cancel { background: var(--surface-2); color: var(--text-2); border: 1px solid var(--border-strong); }
  .tool:disabled { opacity: .55; cursor: not-allowed; }
  .intro-note { flex-basis: 100%; margin: 2px 0 0; font-family: var(--font-ui); font-size: var(--fs-2xs); line-height: 1.4; color: var(--warning); }
  .intro-note.error { color: var(--danger); font-size: var(--fs-xs); }
</style>
