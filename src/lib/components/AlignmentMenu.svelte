<script lang="ts">
  /** The top bar's Alignment menu (#488, 2026-11-11): the three actions that
   *  were the only buttons on the editor's second bar. Each entry does what
   *  its button did, with the same disabled state and tooltip; the caller
   *  owns the actions and those states. Choosing an entry closes the menu. */
  import { onDestroy, tick } from "svelte";

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
  document.addEventListener("keydown", onKey);
  onDestroy(() => {
    document.removeEventListener("mousedown", onDocumentPointer);
    document.removeEventListener("keydown", onKey);
  });
</script>

<span class="alignment-menu" bind:this={root}>
  <button type="button" class="menu-btn" bind:this={trigger} aria-haspopup="menu" aria-expanded={open}
    title="Alignment Review, cross-verse alignment and automatic alignment of this chapter"
    on:click={() => (open ? close(false) : void show())}
    on:keydown={(event) => { if (event.key === "ArrowDown" && !open) { event.preventDefault(); void show(); } }}>Alignment ▾</button>
  {#if open}
    <!-- svelte-ignore a11y-no-static-element-interactions -->
    <div class="panel" role="menu" aria-label="Alignment" tabindex="-1" bind:this={list} on:keydown={onMenuKey}>
      <button type="button" role="menuitem" on:click={() => choose(onAlignmentReview)}>Alignment Review</button>
      <button type="button" role="menuitem" disabled={crossVerseDisabled}
        title={selectedCount > 1
          ? `Open the ${selectedCount} selected verses side by side`
          : "Align several verses of this chapter side by side (Ctrl-click or Shift-click verses to pick them first)"}
        on:click={() => { if (!crossVerseDisabled) choose(onCrossVerse); }}>Cross-verse alignment{#if selectedCount > 1}&nbsp;({selectedCount}){/if}</button>
      <button type="button" role="menuitem" disabled={alignChapterDisabled} title={alignChapterTitle}
        on:click={() => { if (!alignChapterDisabled) choose(onAlignChapter); }}>{alignChapterLabel}</button>
    </div>
  {/if}
</span>

<style>
  .alignment-menu { position: relative; display: inline-flex; }
  .menu-btn { height: var(--control-h); box-sizing: border-box; display: inline-flex; align-items: center; font: inherit; font-size: var(--fs-sm); font-weight: 600; line-height: 1; padding: 0 8px; border-radius: 6px; border: 1px solid transparent; background: transparent; color: var(--text-2); cursor: pointer; white-space: nowrap; }
  .menu-btn:hover, .menu-btn[aria-expanded="true"] { background: var(--surface-2); color: var(--text); border-color: var(--border); }
  .panel { position: absolute; top: calc(100% + 4px); left: 0; z-index: var(--z-dropdown); min-width: 200px; padding: 4px; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface); box-shadow: 0 8px 24px rgba(0,0,0,.14); display: flex; flex-direction: column; }
  .panel button { display: flex; align-items: center; padding: 6px 10px; border: 0; border-radius: 5px; background: transparent; color: var(--text); font: inherit; font-size: var(--fs-xs); text-align: left; cursor: pointer; white-space: nowrap; }
  .panel button:hover:not(:disabled), .panel button:focus-visible { background: var(--surface-2); outline: none; }
  .panel button:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
