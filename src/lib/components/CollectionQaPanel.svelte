<script lang="ts">
  // Collection QA (layered-rules Phase 4.4): run every check over every book
  // of the collection, one book after another. Starting a run is always the
  // user's choice (never automatic after an import): a whole Bible is 66
  // sequential book jobs on one worker thread, an operation meant to run
  // unattended. While it runs the app is read-only.
  //
  // Since the dashboard restyle (2026-10-28) this is one control bar in the
  // dashboard header: the summary, the checks menu and the Run button idle;
  // the progress bar with Pause and Cancel while a run is active. Each
  // book's own result (state, verses checked, findings, last run) is drawn
  // on its row in the book list by ProjectDashboard from the same store, so
  // the table this panel used to carry is gone. The whole-collection stage
  // stays here, folded under the bar.
  import { onMount } from "svelte";
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";
  import {
    cancelCollectionQa, collectionQa, formatDuration as duration, pauseCollectionQa, refreshCollectionQa,
    startCollectionQa,
  } from "../collectionQa";
  import type { CollectionQaBook } from "../types/collectionQa";
  import { collectionChecks } from "../editorPrefs";
  import { CHECK_BOXES, checkListLabel, selectedCollectionChecks, toggleCheck } from "../checkSelection";

  export let bookCount = 0;

  let error = "";
  let busy = false;
  let checksOpen = false;

  onMount(() => {
    void refreshCollectionQa().catch((e) => { error = e instanceof Error ? e.message : String(e); });
  });

  $: snapshot = $collectionQa;
  $: active = snapshot ? ["queued", "running", "cancelling"].includes(snapshot.state) : false;
  $: lastRun = snapshot?.books.some((b) => b.completedAt) ?? false;
  $: summary = snapshot ? idleSummary(snapshot.books) : "";
  $: runningBook = snapshot?.books.find((b) => b.state === "running") ?? null;

  /** One line while idle: how the books last ended and when the latest finished. */
  function idleSummary(books: CollectionQaBook[]): string {
    const count = (state: string) => books.filter((b) => b.state === state).length;
    const parts: string[] = [];
    for (const [state, label] of [["done", "done"], ["skipped", "unchanged"], ["failed", "failed"]] as const) {
      if (count(state)) parts.push(`${count(state)} ${label}`);
    }
    const latest = books.map((b) => b.completedAt).filter((at): at is string => Boolean(at)).sort().pop();
    parts.push(latest ? `last run ${new Date(latest).toLocaleString()}` : "never run");
    return parts.join(" · ");
  }

  async function act(fn: () => Promise<void>): Promise<void> {
    if (busy) return;
    busy = true;
    error = "";
    checksOpen = false;
    try {
      await fn();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      busy = false;
    }
  }

  function closeChecks(event: FocusEvent) {
    const container = event.currentTarget as HTMLElement;
    if (!(event.relatedTarget instanceof Node) || !container.contains(event.relatedTarget)) checksOpen = false;
  }
</script>

<section class="collection-qa" class:active aria-label="Collection QA">
  <div class="head">
    <div class="title">
      <h3>Collection QA</h3>
      {#if snapshot && active}
        <span class="status" aria-live="polite">
          {snapshot.state === "cancelling" ? "Cancelling" : snapshot.paused ? "Pausing after this book" : runningBook ? `Checking ${runningBook.bookName || runningBook.bookId.toUpperCase()}` : "Starting"}
          · {snapshot.completedBooks}/{snapshot.totalBooks} books · {duration(snapshot.elapsedSeconds)} elapsed{#if snapshot.estimatedRemainingSeconds !== null}{` · about ${duration(snapshot.estimatedRemainingSeconds)} left`}{/if}
        </span>
      {:else if summary}
        <span class="status">{summary}</span>
      {/if}
    </div>
    <div class="actions">
      {#if active}
        <button class="ui-btn" on:click={() => act(() => pauseCollectionQa(!snapshot?.paused))} disabled={busy || snapshot?.state === "cancelling"}>
          <UiIcon name={snapshot?.paused ? "play" : "pause"} />{snapshot?.paused ? "Resume" : "Pause after this book"}</button>
        <button class="ui-btn danger" on:click={() => act(cancelCollectionQa)} disabled={busy || snapshot?.state === "cancelling"}><UiIcon name="stop" />Cancel</button>
      {:else}
        <div class="checks-control" on:focusout={closeChecks}>
          <button class="ui-btn" aria-haspopup="true" aria-expanded={checksOpen} aria-controls="collection-qa-checks"
            use:tooltip={`Which checks a run performs: ${checkListLabel($selectedCollectionChecks)}`}
            on:click={() => (checksOpen = !checksOpen)}>
            Checks <span class="count">{$selectedCollectionChecks.length}</span><UiIcon name="chevronDown" />
          </button>
          {#if checksOpen}
            <div class="checks-menu" id="collection-qa-checks" role="group" aria-label="Checks to run">
              {#each CHECK_BOXES as box}
                <label use:tooltip={box.title}>
                  <input type="checkbox" checked={$selectedCollectionChecks.includes(box.id)}
                    disabled={$selectedCollectionChecks.length === 1 && $selectedCollectionChecks.includes(box.id)}
                    on:change={(event) => toggleCheck(collectionChecks, box.id, event.currentTarget.checked)} />
                  {box.label}
                </label>
              {/each}
              <p>A run checks every book in turn and is meant to be left alone: editing, switching books and Greek Room pause until it ends. A book unchanged since its last run of these checks is skipped.</p>
            </div>
          {/if}
        </div>
        <button class="ui-btn primary" on:click={() => act(() => startCollectionQa(false))} disabled={busy}
          use:tooltip={`Checks every book in turn (${checkListLabel($selectedCollectionChecks)}); books unchanged since their last run are skipped`}>
          <UiIcon name="play" />Run QA on all {bookCount} {bookCount === 1 ? "book" : "books"}</button>
        {#if lastRun}
          <button class="ui-btn" on:click={() => act(() => startCollectionQa(true))} disabled={busy}
            use:tooltip={"Check every book again, including unchanged ones"}>Run all again</button>
        {/if}
      {/if}
    </div>
  </div>
  {#if snapshot && active}
    <div class="track" aria-hidden="true"><div class="fill" style="width:{snapshot.percent}%"></div></div>
  {/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if snapshot?.error}<p class="error">{snapshot.error}</p>{/if}
  {#if snapshot?.finalStage}
    <details class="final">
      <summary>Whole-collection checks{#if snapshot.finalStage.completedAt} · {new Date(snapshot.finalStage.completedAt).toLocaleString()}{/if}</summary>
      <ul>
        <li>Termbase coverage: {(snapshot.finalStage.termbaseCoverage ?? []).reduce((n, b) => n + b.issues.length, 0)} concept issue(s) across {(snapshot.finalStage.termbaseCoverage ?? []).length} book(s).</li>
        <li>Cross-book names: {#if snapshot.finalStage.crossBookNames?.available}{snapshot.finalStage.crossBookNames.findings?.length ?? 0} spelling pair(s){:else if snapshot.finalStage.crossBookNames?.error}unavailable ({snapshot.finalStage.crossBookNames.error}){:else}not run{/if}.</li>
        <li>House-style propagation: {snapshot.finalStage.houseStylePropagation?.reason ?? "not available"}</li>
      </ul>
    </details>
  {/if}
</section>

<style>
  .collection-qa { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
  .head { display: flex; align-items: center; justify-content: space-between; gap: 12px 16px; flex-wrap: wrap; }
  .title { display: flex; align-items: baseline; gap: 10px; min-width: 0; flex: 1 1 260px; }
  h3 { margin: 0; font-size: var(--fs-sm); font-weight: 650; color: var(--text); white-space: nowrap; }
  .status { min-width: 0; color: var(--text-2); font-size: var(--fs-3xs); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .active .status { color: var(--accent); font-weight: 600; }
  .actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; flex-shrink: 0; }
  .checks-control { position: relative; }
  .count { display: inline-grid; place-items: center; min-width: 18px; height: 18px; padding: 0 5px; border-radius: 999px; background: var(--accent-bg); color: var(--accent); font-size: var(--fs-3xs); }
  .checks-menu { position: absolute; z-index: var(--z-dropdown); right: 0; top: calc(100% + 6px); width: 300px; display: flex; flex-direction: column; gap: 8px; padding: 12px; border: 1px solid var(--border-strong); border-radius: 10px; background: var(--surface); box-shadow: 0 10px 25px rgba(25, 35, 55, .16); }
  .checks-menu label { display: flex; align-items: center; gap: 8px; font-size: var(--fs-2xs); color: var(--text); cursor: pointer; }
  .checks-menu input { width: 16px; height: 16px; margin: 0; accent-color: var(--accent); }
  .checks-menu p { margin: 4px 0 0; padding-top: 8px; border-top: 1px solid var(--border); color: var(--text-2); font-size: var(--fs-3xs); line-height: 1.5; }
  .track { height: 6px; border-radius: 3px; background: var(--border); overflow: hidden; }
  .fill { height: 100%; background: var(--accent); transition: width .3s linear; }
  .error { margin: 0; color: var(--danger); font-size: var(--fs-3xs); }
  .final { font-size: var(--fs-3xs); color: var(--text-2); }
  .final summary { cursor: pointer; width: fit-content; padding: 2px 0; }
  .final summary:hover { color: var(--accent); }
  .final ul { margin: 6px 0 0; padding-left: 18px; line-height: 1.6; }
  @media (prefers-reduced-motion: reduce) { .fill { transition: none; } }
</style>
