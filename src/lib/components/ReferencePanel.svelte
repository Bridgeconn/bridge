<script lang="ts">
  import PanelHeader from "./PanelHeader.svelte";
  import { onDestroy, tick } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import { currentChapter, project, selectedVerse, targetLang } from "../stores";
  import type { ReferenceChapter } from "../types/languageQa";

  // The reference Bible (an Old Version) beside the text, on the same chapter
  // (indic-qa's reference panel). Reading only: nothing here changes the text.
  // #289: one folder per project (every book of a collection shares it),
  // chosen here with Browse, changed with Change; Settings › Language QA
  // shows the same field and can clear it.
  export let onOpenSettings: () => void = () => {};
  export let onSelectVerse: (verse: string) => void = () => {};

  let reference: ReferenceChapter | null = null;
  let error = "";
  let choosing = false;
  let chooseError = "";
  $: heading = !reference?.source ? "Reference"
    : reference.source.origin === "bundled" ? `Built in: ${reference.source.label.replace(/\s*\(bundled\)$/, "")}`
    : reference.source.label;

  /** The folder picker on this computer, then the project's choice, then a fresh read. */
  async function choose(): Promise<void> {
    if (choosing || !path) return;
    choosing = true;
    chooseError = "";
    try {
      const folder = await bridge.pickFolder();
      if (!folder) return;
      await bridge.languageQaSetReference(path, folder);
      reference = null;
      await load(path, $currentChapter);
    } catch (cause) {
      chooseError = cause instanceof Error ? cause.message : String(cause);
    } finally {
      choosing = false;
    }
  }
  let follow = true;
  let list: HTMLOListElement | null = null;
  let ticket = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  $: path = $project?.path ?? "";
  $: void load(path, $currentChapter);
  $: if (follow && $selectedVerse && reference?.ready) void scrollTo($selectedVerse);

  async function load(projectPath: string, chapter: string, attempt = 0): Promise<void> {
    if (timer) clearTimeout(timer);
    const mine = ++ticket;
    if (!projectPath || !chapter) return;
    try {
      const result = await bridge.languageQaReference(projectPath, chapter);
      if (mine !== ticket) return;
      reference = result;
      error = "";
      // The folder is read on a background thread the first time: ask again.
      if (!result.ready && result.configured && !result.error && attempt < 120) {
        timer = setTimeout(() => void load(projectPath, chapter, attempt + 1), 1000);
      }
    } catch (cause) {
      if (mine === ticket) error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  async function scrollTo(verse: string): Promise<void> {
    await tick();
    const row = list?.querySelector<HTMLElement>(`[data-ref-verse="${CSS.escape(verse)}"]`);
    if (row && typeof row.scrollIntoView === "function") row.scrollIntoView({ block: "nearest" });
  }

  onDestroy(() => {
    ticket += 1;
    if (timer) clearTimeout(timer);
  });
</script>

<!-- Its column (SidePanel "reference") sets the width and the resize handle. -->
<aside class="reference-panel" aria-label="Reference Bible">
  <!-- #379: the shared header bar; Change and the follow box are this panel's actions. -->
  <PanelHeader id="reference" title={heading} hint={reference?.source?.path ?? ""} label="the Reference panel">
    {#if reference?.configured}
      <button type="button" class="change" on:click={choose} disabled={choosing}
        title="Choose another reference Bible folder for this project">Change</button>
    {/if}
    <label class="follow"><input type="checkbox" bind:checked={follow} /> follow</label>
  </PanelHeader>
  {#if chooseError}
    <p class="note error" role="alert">{chooseError}</p>
  {/if}
  {#if error}
    <p class="note error" role="alert">{error}</p>
  {:else if !reference}
    <p class="note">Loading…</p>
  {:else if !reference.configured}
    <p class="note">No reference Bible is chosen for this project.</p>
    <button class="settings" on:click={choose} disabled={choosing}>Browse for a reference Bible on this computer</button>
    <button class="settings secondary" on:click={onOpenSettings}>or manage it in Settings › Language QA</button>
  {:else if reference.error}
    <p class="note error" role="alert">The reference could not be read: {reference.error}</p>
  {:else if !reference.ready}
    <p class="note">Reading the reference Bible… (once; it is kept)</p>
  {:else if !reference.verses.length}
    <p class="note">This chapter is not in the reference Bible.</p>
  {:else}
    <ol bind:this={list}>
      {#each reference.verses as row (row.verse)}
        <li data-ref-verse={row.verse} class:current={row.verse === $selectedVerse}>
          <button type="button" on:click={() => onSelectVerse(row.verse)}
            aria-label={`Verse ${row.verse} in the reference: show it in the text`}>
            <span class="num">{row.verse}</span><span class="text" lang={$targetLang}>{row.text}</span>
          </button>
        </li>
      {/each}
    </ol>
  {/if}
</aside>

<style>
  /* #379 item 6: the body is --surface at --fs-xs, its content 12px from the
     edge and 10px under the bar (the list's 4px plus each row's 6px 8px). */
  .reference-panel { flex: 1; display: flex; flex-direction: column; min-height: 0; background: var(--surface); font-size: var(--fs-xs); }
  .follow { display: flex; align-items: center; gap: 4px; white-space: nowrap; }
  .note { margin: 10px 12px; font-size: var(--fs-xs); color: var(--text-3); }
  .error { color: var(--danger); }
  .settings { margin: 0 12px; font: inherit; font-size: var(--fs-xs); color: var(--accent); background: none;
    border: 0; padding: 0; text-decoration: underline; cursor: pointer; text-align: left; }
  .settings.secondary { margin-top: 6px; color: var(--text-3); }
  .change { font: inherit; font-size: var(--fs-2xs); padding: 2px 8px; border: 1px solid var(--border-strong);
    border-radius: 6px; background: var(--surface); color: var(--text-2); cursor: pointer; white-space: nowrap; }
  .change:hover:not(:disabled) { color: var(--accent); border-color: var(--accent); }
  ol { list-style: none; margin: 0; padding: 4px; overflow-y: auto; flex: 1; }
  li button { display: flex; gap: 8px; width: 100%; text-align: left; padding: 6px 8px; border: 0; border-radius: 6px;
    background: transparent; color: var(--text); cursor: pointer; font: inherit; }
  li button:hover { background: var(--surface-2); }
  li.current button { background: var(--accent-bg); box-shadow: inset 3px 0 0 var(--accent); }
  .num { font-size: var(--fs-2xs); font-weight: 700; color: var(--text-3); min-width: 20px; padding-top: 2px; }
  .text { font-family: var(--font-target); font-size: calc(var(--fs-md) * var(--verse-scale, 1)); line-height: 1.7; }
</style>
