<script lang="ts">
  import PanelHeader from "./PanelHeader.svelte";
  // #357: the Paratext team's Project Notes on the selected verse, read-only.
  // Threads come from every Notes_<User>.xml of the linked Paratext folder,
  // merged by thread; comments are shown in date order. Bridge never writes
  // these notes (writing back is #358, through Paratext's plugin API only).
  import { onDestroy } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import { currentChapter, project, selectedVerse } from "../stores";
  import { loadParatextNoteCounts } from "../paratextNotes";
  import type { ParatextLinkState, ParatextNoteThread, ParatextNotesIndexState } from "../types/paratext";

  const POLL_MS = 1500;

  let threads: ParatextNoteThread[] = [];
  let state: ParatextNotesIndexState | "" = "";
  let linkState: ParatextLinkState | "" = "";
  let error = "";
  let refreshing = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let request = 0;

  function stopPolling(): void {
    if (timer) clearTimeout(timer);
    timer = null;
  }
  onDestroy(stopPolling);

  async function load(chapter: string, verse: string | null): Promise<void> {
    stopPolling();
    const mine = ++request;
    error = "";
    if (!verse) {
      threads = [];
      state = "";
      return;
    }
    try {
      const result = await bridge.paratextNotesForVerse(chapter, verse);
      if (mine !== request) return;
      threads = result.threads;
      state = result.state;
      if (state === "unavailable" && !linkState) linkState = (await bridge.paratextLinkStatus()).state;
      if (state === "building" || state === "stale") timer = setTimeout(() => void load(chapter, verse), POLL_MS);
    } catch (value) {
      if (mine !== request) return;
      error = value instanceof Error ? value.message : String(value);
    }
  }

  async function refresh(): Promise<void> {
    refreshing = true;
    try {
      const status = await bridge.paratextRefresh();
      linkState = status.state;
      await load($currentChapter, $selectedVerse);
      void loadParatextNoteCounts($currentChapter);
    } catch (value) {
      error = value instanceof Error ? value.message : String(value);
    } finally {
      refreshing = false;
    }
  }

  function when(value: string): string {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  }

  const KIND_LABEL: Record<string, string> = { conflict: "Conflict", biblicalTerm: "Biblical term" };

  $: { void $project; linkState = ""; }
  $: void load($currentChapter, $selectedVerse);
</script>

<div class="pt-notes" data-testid="paratext-notes-panel">
  <!-- #379: the shared header bar (this panel had none); the body below it is
       the panel's own scroll box. -->
  <PanelHeader id="paratext" label="the Paratext notes panel"
    title={$selectedVerse ? `Paratext notes · ${$currentChapter}:${$selectedVerse}` : "Paratext notes"}>
    {#if state && state !== "unavailable"}
      <button type="button" class="refresh" on:click={refresh} disabled={refreshing} title="Read the Paratext notes files again">Refresh</button>
    {/if}
  </PanelHeader>
  <div class="pt-scroll">
  {#if error}
    <p class="pt-msg pt-error" role="alert">{error}</p>
  {:else if !$selectedVerse}
    <p class="pt-msg">Select a verse to see its Paratext notes.</p>
  {:else if state === "unavailable"}
    <p class="pt-msg">
      {#if linkState === "notParatext" || linkState === ""}
        This book was not imported from a Paratext project, so there are no Paratext notes to show.
      {:else}
        The Paratext project folder is not available ({linkState === "folderMoved" ? "it was moved" : linkState === "guidMismatch" ? "it holds a different project" : "not found"}). Relink it on Project Home.
      {/if}
    </p>
  {:else if state === "building" && !threads.length}
    <p class="pt-msg" role="status">Reading the Paratext notes…</p>
  {:else if state === "error"}
    <p class="pt-msg pt-error">The Paratext notes could not be read. Try Refresh.</p>
  {:else}
    {#if state === "stale"}<p class="pt-msg" role="status">Updating from Paratext…</p>{/if}
    {#if !threads.length}
      <p class="pt-msg">No Paratext notes on this verse.</p>
    {/if}
    {#each threads as thread (thread.id)}
      <article class="pt-thread" class:resolved={thread.resolved} data-thread-id={thread.id}>
        <header>
          {#if KIND_LABEL[thread.kind]}<span class="pt-kind">{KIND_LABEL[thread.kind]}</span>{/if}
          <span class="pt-status">{thread.resolved ? "Resolved" : "Open"}</span>
          {#if thread.verse && thread.verseRef}<span class="pt-ref">{thread.verseRef}</span>{/if}
          {#if thread.assignedUser}<span class="pt-assigned">Assigned to {thread.assignedUser}</span>{/if}
          {#each thread.tags as tag (tag.id)}<span class="pt-tag">{tag.name || `tag ${tag.id}`}</span>{/each}
        </header>
        {#if thread.selectedText}<blockquote class="pt-quote">{thread.selectedText}</blockquote>{/if}
        <ol class="pt-comments">
          {#each thread.comments as comment, i (i)}
            <li>
              <div class="pt-meta"><strong>{comment.user}</strong> · {when(comment.date)}{comment.status === "done" || comment.status === "deleted" ? " · resolved" : ""}</div>
              {#if comment.contents}<div class="pt-body">{comment.contents}</div>{/if}
            </li>
          {/each}
        </ol>
      </article>
    {/each}
  {/if}
  </div>
</div>

<style>
  /* #379 item 6: the body is --surface at --fs-xs, padded 10px 12px. */
  .pt-notes { flex: 1; min-height: 0; display: flex; flex-direction: column; background: var(--surface); font-size: var(--fs-xs); color: var(--text); }
  .pt-scroll { flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; padding: 10px 12px; }
  .refresh { border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface); color: var(--text);
    padding: 2px 8px; font: inherit; font-size: var(--fs-2xs); cursor: pointer; }
  .pt-msg { margin: 0; color: var(--text-2); font-size: var(--fs-2xs); line-height: 1.45; }
  .pt-error { color: var(--danger); }
  .pt-thread { border: 1px solid var(--border); border-radius: 7px; padding: 7px 9px; background: var(--surface); }
  .pt-thread.resolved { opacity: .7; }
  .pt-thread header { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: center; font-size: var(--fs-2xs); color: var(--text-2); }
  .pt-kind { font-weight: 700; color: var(--warning); }
  .pt-status { font-weight: 700; }
  .pt-tag { border-radius: 999px; padding: 0 6px; background: var(--accent-bg); color: var(--accent); }
  .pt-quote { margin: 6px 0; padding: 2px 8px; border-left: 3px solid var(--border-strong); color: var(--text-2); }
  .pt-comments { list-style: none; margin: 4px 0 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
  .pt-meta { font-size: var(--fs-2xs); color: var(--text-2); }
  .pt-body { white-space: pre-wrap; overflow-wrap: anywhere; font-family: var(--font-target, inherit); }
</style>
