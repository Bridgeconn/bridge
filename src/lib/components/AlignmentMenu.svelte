<script lang="ts">
  /** The Alignment menu (#488, 2026-11-11): the three actions that were the
   *  only buttons on the editor's second bar, and since 2026-11-16 (Joel)
   *  Word alignment too, which could only be opened from a verse's own icon.
   *  In order: Word alignment, Cross-verse alignment, Alignment Review, Align
   *  chapter with AI, each with its icon. The two tabs say when they are
   *  already open; choosing one then shows it. The caller owns the actions
   *  and the disabled states. Choosing an entry closes the menu. */
  import { onDestroy, tick } from "svelte";
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";

  /** On the editor's left rail: an icon button, the menu opening to its right. */
  export let rail = false;

  /** Open (or show) the Word alignment tab on the selected verse. */
  export let onWordAlignment: () => void = () => {};
  /** No verse is selected. */
  export let wordDisabled = false;
  /** The tabs are open already: their entries say so. */
  export let wordOpen = false;
  export let crossOpen = false;
  export let onAlignmentReview: () => void = () => {};
  export let onCrossVerse: () => void = () => {};
  /** No verse is selected. */
  export let crossVerseDisabled = false;
  /** How many verses are picked (Ctrl-click or Shift-click); shown from two up. */
  export let selectedCount = 0;
  export let onAlignChapter: () => void = () => {};
  export let alignChapterDisabled = false;
  export let alignChapterTitle = "";
  /** "Working out the cost…" while the estimate is read. */
  export let alignChapterLabel = "Align chapter with AI";

  let open = false;
  let root: HTMLElement;
  let trigger: HTMLButtonElement;
  let list: HTMLElement;

  const items = (): HTMLButtonElement[] =>
    Array.from(list?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? []);

  async function show(): Promise<void> {
    open = true;
    await tick();
    items()[0]?.focus();
  }
  function close(refocus: boolean): void {
    if (!open) return;
    open = false;
    if (refocus) trigger?.focus();
  }
  function choose(action: () => void): void {
    close(false);
    action();
  }

  function onMenuKey(event: KeyboardEvent): void {
    const all = items();
    const at = all.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "ArrowDown") { event.preventDefault(); all[(at + 1) % all.length]?.focus(); }
    else if (event.key === "ArrowUp") { event.preventDefault(); all[(at - 1 + all.length) % all.length]?.focus(); }
    else if (event.key === "Home") { event.preventDefault(); all[0]?.focus(); }
    else if (event.key === "End") { event.preventDefault(); all[all.length - 1]?.focus(); }
    else if (event.key === "Tab") close(false);
  }

  function onDocumentPointer(event: MouseEvent): void {
    if (open && root && !root.contains(event.target as Node)) close(false);
  }
  function onKey(event: KeyboardEvent): void {
    if (open && event.key === "Escape") { event.preventDefault(); close(true); }
  }
  document.addEventListener("mousedown", onDocumentPointer);
  // The top bar is a window-drag region: the shell takes a mousedown there
  // before the page sees it, so a click on the bar is caught as a pointerdown.
  document.addEventListener("pointerdown", onDocumentPointer, true);
  document.addEventListener("keydown", onKey);
  onDestroy(() => {
    document.removeEventListener("mousedown", onDocumentPointer);
    document.removeEventListener("pointerdown", onDocumentPointer, true);
    document.removeEventListener("keydown", onKey);
  });
</script>

<span class="alignment-menu" class:rail bind:this={root}>
  {#if rail}
    <button type="button" class="rail-btn" bind:this={trigger} aria-label="Alignment" aria-haspopup="menu" aria-expanded={open}
      use:tooltip={{ text: open ? "" : "Alignment: word alignment, cross-verse alignment, Alignment Review, align this chapter with AI", side: "right" }}
      on:click={() => (open ? close(false) : void show())}
      on:keydown={(event) => { if (event.key === "ArrowDown" && !open) { event.preventDefault(); void show(); } }}><UiIcon name="alignMenu" /></button>
  {:else}
  <button type="button" class="menu-btn" bind:this={trigger} aria-haspopup="menu" aria-expanded={open}
    title="Alignment Review, cross-verse alignment and automatic alignment of this chapter"
    on:click={() => (open ? close(false) : void show())}
    on:keydown={(event) => { if (event.key === "ArrowDown" && !open) { event.preventDefault(); void show(); } }}>Alignment ▾</button>
  {/if}
  {#if open}
    <!-- svelte-ignore a11y-no-static-element-interactions -->
    <div class="panel" role="menu" aria-label="Alignment" tabindex="-1" bind:this={list} on:keydown={onMenuKey}>
      <button type="button" role="menuitem" disabled={wordDisabled}
        use:tooltip={{ side: "right", text: wordOpen ? "Word alignment is already open. Click to show it"
          : wordDisabled ? "Select a verse first" : "Align the words of the selected verse to the source" }}
        on:click={() => { if (!wordDisabled) choose(onWordAlignment); }}><UiIcon name="align" /><span class="entry">Word alignment</span>{#if wordOpen}<span class="is-open">open</span>{/if}</button>
      <button type="button" role="menuitem" disabled={crossVerseDisabled}
        use:tooltip={{ side: "right", text: selectedCount > 1
          ? `Open the ${selectedCount} selected verses side by side`
          : crossOpen ? "Cross-verse alignment is already open. Click to show it"
          : "Align several verses of this chapter side by side (Ctrl-click or Shift-click verses to pick them first)" }}
        on:click={() => { if (!crossVerseDisabled) choose(onCrossVerse); }}><UiIcon name="link" /><span class="entry">Cross-verse alignment{#if selectedCount > 1}&nbsp;({selectedCount}){/if}</span>{#if crossOpen}<span class="is-open">open</span>{/if}</button>
      <button type="button" role="menuitem" use:tooltip={{ side: "right", text: "Review the alignment of the whole book, verse by verse" }}
        on:click={() => choose(onAlignmentReview)}><UiIcon name="review" /><span class="entry">Alignment Review</span></button>
      <button type="button" role="menuitem" disabled={alignChapterDisabled} use:tooltip={{ side: "right", text: alignChapterTitle }}
        on:click={() => { if (!alignChapterDisabled) choose(onAlignChapter); }}><UiIcon name="sparkle" /><span class="entry">{alignChapterLabel}</span></button>
    </div>
  {/if}
</span>

<style>
  .alignment-menu { position: relative; display: inline-flex; }
  .rail .panel { top: 0; left: calc(100% + 10px); }
  .menu-btn { height: var(--control-h); box-sizing: border-box; display: inline-flex; align-items: center; font: inherit; font-size: var(--fs-sm); font-weight: 600; line-height: 1; padding: 0 8px; border-radius: 6px; border: 1px solid transparent; background: transparent; color: var(--text-2); cursor: pointer; white-space: nowrap; }
  .menu-btn:hover, .menu-btn[aria-expanded="true"] { background: var(--surface-2); color: var(--text); border-color: var(--border); }
  .panel { position: absolute; top: calc(100% + 4px); left: 0; z-index: var(--z-dropdown); min-width: 200px; padding: 4px; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface); box-shadow: 0 8px 24px rgba(0,0,0,.14); display: flex; flex-direction: column; }
  .panel button { display: flex; align-items: center; gap: 8px; padding: 6px 10px; border: 0; border-radius: 5px; background: transparent; color: var(--text); font: inherit; font-size: var(--fs-xs); text-align: left; cursor: pointer; white-space: nowrap; }
  .panel button:hover:not(:disabled), .panel button:focus-visible { background: var(--surface-2); outline: none; }
  .panel button:disabled { opacity: 0.6; cursor: not-allowed; }
  .panel button :global(svg) { width: 15px; height: 15px; flex: none; color: var(--text-3); }
  .entry { flex: 1; }
  /* A tab that is open already: said on the entry, quietly. */
  .is-open { flex: none; padding: 0 6px; border-radius: 999px; background: var(--accent-bg); color: var(--accent); font-size: var(--fs-3xs); font-weight: 700; }
</style>
