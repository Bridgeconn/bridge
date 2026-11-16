<script lang="ts">
  import { onMount } from "svelte";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { project } from "../stores";
  import { confirmRequest, answerConfirmation } from "../confirmAction";
  import {
    hideReviewWindow, onReviewContext, onReviewError, sendReviewMessage, type ReviewContext,
  } from "../reviewWindow";
  import ParatextReviewQueue from "./ParatextReviewQueue.svelte";
  import ConfirmDialog from "./ConfirmDialog.svelte";
  import WindowBar from "./WindowBar.svelte";

  let context: ReviewContext | null = null;
  let panel: ParatextReviewQueue | undefined;
  let error = "";

  onMount(() => {
    let disposed = false;
    const stops: (() => void)[] = [];
    const keep = (stop: () => void) => { if (disposed) stop(); else stops.push(stop); };
    void (async () => {
      keep(await onReviewContext((value) => {
        if (context?.project?.path !== value.project?.path || !value.open) answerConfirmation(false);
        project.set(value.project);
        context = value;
      }));
      keep(await onReviewError((message) => { error = message; }));
      keep(await getCurrentWindow().onCloseRequested((event) => {
        event.preventDefault();
        if (panel) void panel.dismiss(); else void hideReviewWindow();
      }));
      if (!disposed) await sendReviewMessage({ kind: "ready" });
    })().catch((cause) => { error = String(cause); });
    return () => { disposed = true; stops.forEach((stop) => stop()); answerConfirmation(false); };
  });
</script>

{#if error}<div role="alert" class="window-error">{error}<button type="button" on:click={() => (error = "")}>Dismiss</button></div>{/if}
<!-- 2026-11-14 (Joel): the app's own title bar, the one Close this window has. -->
<main class="review-window">
  <WindowBar title="Review notes" onClose={() => { if (panel) void panel.dismiss(); else void hideReviewWindow(); }} />
  <div class="stage">
    {#if context?.open && context.project}
      {@const path = context.project.path}
      {#key path}
        <ParatextReviewQueue bind:this={panel} standalone revision={context.revision}
          onClose={() => { void sendReviewMessage({ kind: "close", path }); }}
          onDetach={async () => { await sendReviewMessage({ kind: "dock", path }); }}
          onNavigate={async (book, chapter, verse) => { await sendReviewMessage({ kind: "navigate", path, book, chapter, verse }); }}
          onRefresh={async (expectedPath, decision) => { await sendReviewMessage({ kind: "saved", path: expectedPath, decision }); }} />
      {/key}
    {:else}
      <p class="waiting" role="status">Open the review queue from the Scripture editor.</p>
    {/if}
  </div>
</main>
{#if $confirmRequest}<ConfirmDialog />{/if}

<style>
  .review-window { height: 100vh; display: flex; flex-direction: column; overflow: hidden; min-width: 0; background: var(--surface); }
  .stage { position: relative; flex: 1; min-height: 0; min-width: 0; }
  .waiting { padding: 24px; color: var(--text-2); }
  .window-error { position: fixed; top: 8px; left: 8px; right: 8px; z-index: 70; padding: 12px; border: 1px solid var(--danger); background: var(--surface); color: var(--danger); }
  .window-error button { margin-left: 12px; }
</style>
