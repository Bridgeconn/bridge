<script lang="ts">
  /** The editor's Checks menu (#251, #252): which checks a run includes, and
   *  Run Greek Room for the verse, the chapter or the book. The selection is
   *  saved per installation and used by every run the editor starts: on
   *  chapter entry, after an edit, Run chapter and Run whole book. Greek Room
   *  is off by default and always runs last. */
  import { onDestroy } from "svelte";
  import { editorChecks } from "../editorPrefs";
  import { CHECK_BOXES, selectedEditorChecks, toggleCheck, type CheckBoxId } from "../checkSelection";

  export let disabled = false;
  /** "1:3" when a verse is selected, else "". */
  export let verse = "";
  export let chapter = "";
  export let onRunChapter: () => void | Promise<void>;
  export let onRunBook: () => void | Promise<void>;
  export let onRunGreekRoom: (scope: "verse" | "chapter" | "book") => void | Promise<void>;

  let open = false;
  let root: HTMLElement;

  function onDocumentPointer(event: MouseEvent): void {
    if (open && root && !root.contains(event.target as Node)) open = false;
  }
  function onKey(event: KeyboardEvent): void {
    if (open && event.key === "Escape") open = false;
  }
  document.addEventListener("mousedown", onDocumentPointer);
  document.addEventListener("keydown", onKey);
  onDestroy(() => {
    document.removeEventListener("mousedown", onDocumentPointer);
    document.removeEventListener("keydown", onKey);
  });

  $: selected = new Set<CheckBoxId>($selectedEditorChecks);
  $: onlyOne = $selectedEditorChecks.length === 1;

  function run(action: () => void | Promise<void>): void {
    open = false;
    void action();
  }
</script>

<span class="check-menu" bind:this={root}>
  <button type="button" class="menu-btn" aria-haspopup="true" aria-expanded={open}
    title="Choose the checks a run includes; run Greek Room" on:click={() => (open = !open)}>Checks ▾</button>
  {#if open}
    <div class="panel" role="group" aria-label="Checks">
      <p class="heading">Checks to run</p>
      {#each CHECK_BOXES as box}
        <label class="box" title={box.title}>
          <input type="checkbox" checked={selected.has(box.id)}
            disabled={onlyOne && selected.has(box.id)}
            on:change={(event) => toggleCheck(editorChecks, box.id, event.currentTarget.checked)} />
          {box.label}
        </label>
      {/each}
      <p class="hint">Used when a chapter opens, after an edit, and by the runs below.</p>
      <div class="actions">
        <button type="button" {disabled} on:click={() => run(onRunChapter)}>Run chapter {chapter}</button>
        <button type="button" {disabled} on:click={() => run(onRunBook)}>Run whole book</button>
      </div>
      <p class="heading">Greek Room, on demand</p>
      <div class="actions">
        <button type="button" disabled={disabled || !verse} on:click={() => run(() => onRunGreekRoom("verse"))}>
          Verse {verse || "—"}
        </button>
        <button type="button" {disabled} on:click={() => run(() => onRunGreekRoom("chapter"))}>Chapter {chapter}</button>
        <button type="button" {disabled} on:click={() => run(() => onRunGreekRoom("book"))}>Whole book</button>
      </div>
    </div>
  {/if}
</span>

<style>
  .check-menu { position: relative; display: inline-flex; }
  .menu-btn { font-size: var(--fs-xs); font-weight: 600; padding: 4px 10px; border-radius: 6px; border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); cursor: pointer; }
  .panel { position: absolute; top: calc(100% + 4px); left: 0; z-index: var(--z-dropdown); min-width: 250px; padding: 10px 12px; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface); box-shadow: 0 8px 24px rgba(0,0,0,.14); display: flex; flex-direction: column; gap: 4px; }
  .heading { margin: 4px 0 2px; font-size: var(--fs-2xs); font-weight: 700; text-transform: uppercase; letter-spacing: .04em; color: var(--text-2); }
  .box { display: flex; align-items: center; gap: 8px; font-size: var(--fs-xs); color: var(--text); cursor: pointer; }
  .hint { margin: 2px 0 4px; font-size: var(--fs-2xs); color: var(--text-2); }
  .actions { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 4px; }
  .actions button { font-size: var(--fs-xs); font-weight: 600; padding: 3px 9px; border-radius: 6px; border: 1px solid var(--border-strong); background: var(--surface-2); color: var(--text); cursor: pointer; }
  .actions button:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
