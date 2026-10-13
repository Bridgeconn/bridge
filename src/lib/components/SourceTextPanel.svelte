<script lang="ts">
  import { onDestroy, tick } from "svelte";
  import { alignmentStatusByVerse, currentChapter, project, selectedVerse, verseNums, verseKey } from "../stores";
  import { cachedSourceChapter, loadSourceChapter, refreshSourceVerse } from "../sourceText";
  import type { SourceChapter, SourceWord } from "../sourceText";

  // The original-language text beside the translation (#67, requirement 8
  // Option A): the chapter's Hebrew, Aramaic or Greek, verse by verse, right to
  // left where it is. Reading only. A source word aligned to target words shows
  // them; one with no counterpart yet is marked. The chapter is read once and
  // kept (sourceText.ts), so opening this column or moving verse is immediate.
  export let onSelectVerse: (verse: string) => void = () => {};

  let source: SourceChapter | null = null;
  let error = "";
  let follow = true;
  let list: HTMLOListElement | null = null;
  let ticket = 0;
  let seen: Record<string, string> = {};

  $: path = $project?.path ?? "";
  $: void show(path, $currentChapter, $verseNums);
  $: if (follow && $selectedVerse && source) void scrollTo($selectedVerse);
  $: void refreshChanged($alignmentStatusByVerse);
  $: language = source?.verses.find((row) => row.available)?.direction === "ltr" ? "Greek" : "Hebrew / Aramaic";

  async function show(projectPath: string, chapter: string, verses: string[]): Promise<void> {
    const mine = ++ticket;
    if (!projectPath || !chapter || !verses.length) return;
    const kept = cachedSourceChapter(projectPath, chapter);
    if (kept) {
      source = kept;
      error = "";
      return;
    }
    source = null;
    try {
      const loaded = await loadSourceChapter(projectPath, chapter, verses);
      if (mine === ticket) {
        source = loaded;
        error = "";
      }
    } catch (cause) {
      if (mine === ticket) error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  /** A verse's alignment or text changed (its status moved): read that verse again. */
  async function refreshChanged(statuses: Record<string, string>): Promise<void> {
    const before = seen;
    seen = { ...statuses };
    if (!path || !source) return;
    const chapter = $currentChapter;
    const changed = $verseNums.filter((verse) => {
      const key = verseKey(chapter, verse);
      return key in statuses && statuses[key] !== before[key] && key in before;
    });
    for (const verse of changed) {
      try {
        const updated = await refreshSourceVerse(path, chapter, verse);
        if (updated && chapter === $currentChapter) source = updated;
      } catch {
        // the kept words stay; the next chapter load reads them again
      }
    }
  }

  async function scrollTo(verse: string): Promise<void> {
    await tick();
    const row = list?.querySelector<HTMLElement>(`[data-source-verse="${CSS.escape(verse)}"]`);
    if (row && typeof row.scrollIntoView === "function") row.scrollIntoView({ block: "nearest" });
  }

  function title(word: SourceWord): string {
    const about = [word.lemma, word.strong].filter(Boolean).join(" · ");
    const aligned = word.targets.length ? `Aligned to: ${word.targets.join(" ")}` : "Not aligned yet";
    return about ? `${word.word} (${about})\n${aligned}` : `${word.word}\n${aligned}`;
  }

  onDestroy(() => {
    ticket += 1;
  });
</script>

<!-- Its column (SidePanel "source") sets the width and the resize handle. -->
<aside class="source-panel" aria-label="Source text">
  <div class="head">
    <span class="label">Source · {source ? language : "original language"}</span>
    <label class="follow"><input type="checkbox" bind:checked={follow} /> follow</label>
  </div>
  {#if error}
    <p class="note error" role="alert">{error}</p>
  {:else if !source}
    <p class="note">Loading…</p>
  {:else if !source.verses.some((row) => row.available)}
    <p class="note">{source.verses[0]?.message || "No source text is available for this chapter."}</p>
  {:else}
    <ol bind:this={list}>
      {#each source.verses as row (row.verse)}
        {@const unaligned = row.words.filter((word) => !word.targets.length).length}
        <li data-source-verse={row.verse} class:current={row.verse === $selectedVerse}>
          <button type="button" on:click={() => onSelectVerse(row.verse)}
            aria-label={`Verse ${row.verse} in the source: show it in the text`}>
            <span class="num">{row.verse}</span>
            {#if row.available}
              <span class="text" dir={row.direction} lang={row.direction === "rtl" ? "hbo" : "grc"}
                class:rtl={row.direction === "rtl"}>
                {#each row.words as word, at (word.id)}{#if at > 0}{" "}{/if}<span class="w"
                    class:unaligned={!word.targets.length} title={title(word)}>{word.word}</span>{/each}
              </span>
            {:else}
              <span class="missing">{row.message || "No source text for this verse."}</span>
            {/if}
          </button>
          {#if row.verse === $selectedVerse && row.available}
            <p class="tally">{row.words.length - unaligned} of {row.words.length} source words aligned</p>
          {/if}
        </li>
      {/each}
    </ol>
  {/if}
</aside>

<style>
  .source-panel { flex: 1; display: flex; flex-direction: column; min-height: 0; background: var(--surface-2); }
  .head { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-bottom: 1px solid var(--border);
    font-size: var(--fs-2xs); color: var(--text-2); }
  .label { flex: 1; font-weight: 700; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .follow { display: flex; align-items: center; gap: 4px; white-space: nowrap; }
  .note { margin: 10px; font-size: var(--fs-xs); color: var(--text-3); }
  .error { color: var(--danger); }
  ol { list-style: none; margin: 0; padding: 6px; overflow-y: auto; flex: 1; min-width: 0; }
  /* The verse number stays at the left edge whichever way the words run. */
  li button { display: flex; gap: 8px; width: 100%; min-width: 0; text-align: left; padding: 6px 8px; border: 0;
    border-radius: 6px; background: transparent; color: var(--text); cursor: pointer; font: inherit; }
  li button:hover { background: var(--surface); }
  li.current button { background: var(--accent-bg); box-shadow: inset 3px 0 0 var(--accent); }
  .num { flex-shrink: 0; font-size: var(--fs-2xs); font-weight: 700; color: var(--text-3); min-width: 20px; padding-top: 2px; }
  /* The source face and size follow the verse text's A−/A+ (--verse-scale);
     the words wrap, never overflow, at any width or Windows scaling. */
  .text { flex: 1; min-width: 0; font-family: var(--font-greek); font-size: calc(var(--fs-md) * var(--verse-scale, 1));
    line-height: 1.8; text-align: start; overflow-wrap: anywhere; unicode-bidi: isolate; }
  .text.rtl { font-family: var(--font-hebrew); font-size: calc(var(--fs-md) * 1.15 * var(--verse-scale, 1)); line-height: 2; }
  .w { border-radius: 3px; }
  .w:hover { background: var(--accent-bg); }
  .w.unaligned { color: var(--text-2); text-decoration: underline dotted var(--warning, #b45309); text-underline-offset: 0.35em; }
  .missing { font-size: var(--fs-xs); color: var(--text-3); }
  .tally { margin: 2px 8px 6px 36px; font-size: var(--fs-3xs); color: var(--text-3); }
</style>
