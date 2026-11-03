<script lang="ts">
  import { onMount } from "svelte";
  import { project, verseTexts } from "../stores";
  import { paratextReviewQueueOpen } from "../paratextNotes";
  import { refreshParatextReviewEditor } from "../paratextReviewRefresh";
  import {
    desktopReviewAvailable, hideReviewWindow, onReviewMessage, openReviewWindow,
    reviewWindowError, sendReviewContext, type ReviewContext, type ReviewMessage,
  } from "../reviewWindow";
  import ParatextReviewQueue from "./ParatextReviewQueue.svelte";

  export let onNavigate: (book: string, chapter: string, verse: string) => Promise<void>;
  let detached = false;
  try { detached = localStorage.getItem("bridge.reviewQueue.detached") === "true" && desktopReviewAvailable(); } catch { /* session only */ }
  let started = false;
  let error = "";
  let revision = 0;
  let wasOpen = false;
  let syncTask = Promise.resolve();
  $: { $verseTexts; revision += 1; }
  $: context = { project: $project, open: $paratextReviewQueueOpen && detached, revision } satisfies ReviewContext;
  $: if (started) schedule(context);

  function schedule(value: ReviewContext): void {
    syncTask = syncTask.then(async () => { if (value === context) await synchronize(value); });
  }

  async function synchronize(value: ReviewContext): Promise<void> {
    try {
      if (value.open && !wasOpen) {
        wasOpen = true;
        await openReviewWindow();
      } else if (!value.open) wasOpen = false;
      if (value !== context) return;
      await sendReviewContext(value);
      if (value === context && !value.open) await hideReviewWindow();
    } catch (cause) {
      error = `Could not open the separate review window: ${String(cause)}`;
      detached = false;
      wasOpen = false;
    }
  }

  function remember(value: boolean): void {
    detached = value;
    try { localStorage.setItem("bridge.reviewQueue.detached", String(value)); } catch { /* session only */ }
  }

  async function receive(message: ReviewMessage): Promise<void> {
    if (message.kind === "ready") { await sendReviewContext(context); return; }
    if (message.path !== $project?.path || !detached || !$paratextReviewQueueOpen) return;
    try {
      if (message.kind === "saved") await refreshParatextReviewEditor(message.path, message.decision);
      else if (message.kind === "navigate") await onNavigate(message.book, message.chapter, message.verse);
      else if (message.kind === "dock") remember(false);
      else if (message.kind === "close") paratextReviewQueueOpen.set(false);
    } catch (cause) {
      await reviewWindowError(`The review action finished, but the editor could not refresh or navigate: ${String(cause)}`);
    }
  }

  onMount(() => {
    if (!desktopReviewAvailable()) return;
    let disposed = false;
    let unlisten = () => {};
    void onReviewMessage((message) => { void receive(message).catch((cause) => { error = String(cause); }); }).then((stop) => {
      if (disposed) stop(); else { unlisten = stop; started = true; }
    }).catch((cause) => { error = `Separate window controls are unavailable: ${String(cause)}`; detached = false; });
    return () => { disposed = true; unlisten(); };
  });
</script>

{#if error}<p role="alert" class="window-error">{error}</p>{/if}
{#if $paratextReviewQueueOpen && $project && !detached}
  {#key $project.path}
    <ParatextReviewQueue onClose={() => paratextReviewQueueOpen.set(false)} {onNavigate}
      onDetach={desktopReviewAvailable() && started ? async () => { error = ""; remember(true); } : null} />
  {/key}
{/if}

<style>
  .window-error { position: fixed; bottom: 12px; left: 12px; z-index: 80; max-width: 520px; padding: 12px; background: var(--surface); color: var(--danger); border: 1px solid var(--danger); }
</style>
