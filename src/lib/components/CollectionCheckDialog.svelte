<script lang="ts">
  /** The dashboard's Check dialog (#490): tick the checks a Collection QA run
   *  performs, optionally have unchanged books checked again, and Start.
   *  Pure UI: the panel that opens it starts the run. The ticks are a draft
   *  until Start, which saves them as the dashboard's selection
   *  (collectionChecks), so Cancel leaves the saved selection as it was. */
  import { onMount } from "svelte";
  import { CHECK_BOXES, selectedCollectionChecks, type CheckBoxId } from "../checkSelection";
  import { collectionChecks } from "../editorPrefs";

  export let bookCount = 0;
  /** Another check is running (a single book's job, a book being opened): no Start. */
  export let checkRunning = false;
  export let recheckUnchanged = false;
  export let onStart: (recheckUnchanged: boolean) => void;
  export let onClose: () => void;

  let draft = new Set<CheckBoxId>($selectedCollectionChecks);
  let recheck = recheckUnchanged;
  let dialog: HTMLDivElement;

  // Escape and Cancel do the same; focus goes back to the Check button.
  let openedFrom: Element | null = null;
  onMount(() => {
    openedFrom = document.activeElement;
    dialog.querySelector<HTMLInputElement>("input")?.focus();
    return () => { if (openedFrom instanceof HTMLElement && openedFrom.isConnected) openedFrom.focus(); };
  });

  function onWindowKeydown(event: KeyboardEvent): void {
    if (event.key === "Escape" && !event.defaultPrevented) { event.preventDefault(); onClose(); }
  }

  function setBox(id: CheckBoxId, on: boolean): void {
    if (on) draft.add(id); else draft.delete(id);
    draft = draft;
  }

  $: blocked = draft.size === 0 ? "Tick at least one check" : checkRunning ? "A check is already running" : "";

  function start(): void {
    if (blocked) return;
    collectionChecks.set(CHECK_BOXES.map((box) => box.id).filter((id) => draft.has(id)));
    onStart(recheck);
  }
</script>

<svelte:window on:keydown={onWindowKeydown} />

<div class="overlay">
  <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="collection-check-title" bind:this={dialog}>
    <h2 id="collection-check-title">Check {bookCount === 1 ? "this book" : `all ${bookCount} books`}</h2>
    <div class="boxes" role="group" aria-label="Checks to run">
      {#each CHECK_BOXES as box}
        <label title={box.title}>
          <input type="checkbox" checked={draft.has(box.id)} on:change={(event) => setBox(box.id, event.currentTarget.checked)} />
          {box.label}
        </label>
      {/each}
    </div>
    <label class="recheck">
      <input type="checkbox" bind:checked={recheck} />
      Also re-check books unchanged since their last run
    </label>
    <p class="note">A run checks every book in turn and is meant to be left alone: editing, switching books and Greek Room pause until it ends.</p>
    <div class="buttons">
      {#if blocked}<span class="blocked" role="status">{blocked}</span>{/if}
      <button type="button" class="ui-btn" on:click={onClose}>Cancel</button>
      <button type="button" class="ui-btn primary" disabled={Boolean(blocked)} on:click={start}>Start</button>
    </div>
  </div>
</div>

<style>
  .overlay { position: fixed; inset: 0; background: rgba(15, 20, 26, 0.45); display: flex; align-items: center; justify-content: center; z-index: var(--z-dialog); }
  .dialog { width: min(420px, calc(100% - 32px)); max-height: 85vh; overflow: auto; display: flex; flex-direction: column; gap: 12px; padding: 20px 24px; border-radius: 14px; background: var(--surface); box-shadow: 0 16px 40px rgba(25, 35, 55, .25); }
  h2 { margin: 0; font-size: var(--fs-lg); color: var(--text); }
  .boxes { display: flex; flex-direction: column; gap: 8px; }
  label { display: flex; align-items: center; gap: 8px; font-size: var(--fs-xs); color: var(--text); cursor: pointer; }
  input { width: 16px; height: 16px; margin: 0; accent-color: var(--accent); }
  .recheck { padding-top: 10px; border-top: 1px solid var(--border); }
  .note { margin: 0; padding-top: 10px; border-top: 1px solid var(--border); color: var(--text-2); font-size: var(--fs-2xs); line-height: 1.5; }
  .buttons { display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
  .blocked { margin-right: auto; color: var(--text-2); font-size: var(--fs-2xs); }
</style>
