<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { get } from "svelte/store";
  import { bridge as api } from "../api/bridgeClient";
  import { bindReviewProject } from "../reviewProjectGuard";
  import { project, alignmentStatusByVerse, noteAlignmentChanged, verseKey } from "../stores";
  import { alignmentBusy } from "../alignmentWindow";
  import { askConfirmation } from "../confirmAction";
  import { recheckVerse } from "../verseChecks";
  import type { AlignmentContext, ChapterResetJob } from "../types/finding";
  export let chapter: string;
  export let busy = false;
  export let onBusy: (value: boolean) => void;
  export let onChanged: (values: AlignmentContext[]) => void;
  /** Drawn as one row of a menu (the Cross-verse bar, 2026-11-16). The menu
   *  closes on a click, so what the job is doing is told through `onState`
   *  and the page shows it; `cancelReset` is the page's Cancel. */
  export let menu = false;
  export let onState: (value: { running: boolean; resumable: boolean; text: string; error: string }) => void = () => {};
  const path = get(project)?.path || "";
  const bridge = bindReviewProject(api, path);
  let job: ChapterResetJob | null = null, working = false, cancelled = false, disposed = false, error = "";
  onMount(() => { void (async () => { try { job = await bridge.chapterResetStatus(); } catch { /* no active job */ } })(); });
  onDestroy(() => { disposed = true; });
  async function run() {
    if (working || busy) return;
    working = true; onBusy(true); alignmentBusy.set(true); cancelled = false; error = "";
    try {
      const preview = await bridge.previewChapterReset(chapter);
      if (!await askConfirmation({ title: `Reset chapter ${chapter} alignment?`,
        body: `Clear alignment in ${preview.verses.length} verses: ${preview.groups} groups, ${preview.links} cross-verse groups and ${preview.decisions} no-counterpart decisions. Links also affect their partner verses. Scripture stays unchanged. Cancellation leaves finished verses reset. Each verse retains history; Undo reset restores only the latest reset verse.`,
        confirmLabel: "Reset chapter alignment", danger: true })) return;
      job = await bridge.startChapterReset(chapter, preview.token);
      while (!disposed && !cancelled && job.state === "running") {
        const result = await bridge.stepChapterReset(job.id!);
        if (get(project)?.path !== path) return;
        job = result.job; onChanged(result.contexts);
        for (const context of result.contexts) {
          const key = verseKey(context.chapter, context.verse);
          alignmentStatusByVerse.update((values) => ({ ...values, [key]: context.status })); noteAlignmentChanged(key);
          await recheckVerse(context.chapter, context.verse, ["alignment"], { expectedPath: path });
        }
      }
    } catch (cause) { error = String(cause); }
    finally { working = false; onBusy(false); alignmentBusy.set(false); }
  }
  $: resumable = !working && (job?.state === "running" || job?.state === "cancelled" || job?.state === "failed");
  $: stateText = job && job.state !== "idle" ? `Chapter ${job.chapter}: ${job.completed}/${job.total} verses · ${job.state}` : "";
  $: stateError = error || job?.error || "";
  // Told only when it changed: a caller that re-renders on every report must not be reported to again.
  let reported = "";
  $: report(working, resumable, stateText, stateError);
  function report(running: boolean, canResume: boolean, text: string, problem: string): void {
    const key = `${running}|${canResume}|${text}|${problem}`;
    if (key === reported) return;
    reported = key;
    onState({ running, resumable: canResume, text, error: problem });
  }
  export function cancelReset(): void { void cancel(); }
  async function cancel() {
    cancelled = true;
    if (job?.id) { try { job = await bridge.cancelChapterReset(job.id); } catch (cause) { error = String(cause); } }
  }
</script>
{#if menu}
  <button type="button" role="menuitem" class="item" disabled={busy || working} on:click={run}>
    <span class="name">{job?.state === "running" || job?.state === "cancelled" || job?.state === "failed" ? "Resume chapter reset" : "Reset chapter alignment…"}</span>
    <small>Clears the alignment of every verse of this chapter. Scripture stays unchanged; it asks first.</small>
  </button>
{:else}
<div class="chapter-reset">
  <button type="button" disabled={busy || working} on:click={run}>{job?.state === "running" || job?.state === "cancelled" || job?.state === "failed" ? "Resume chapter reset" : "Reset chapter alignment"}</button>
  {#if working || job?.state === "running"}<button type="button" on:click={cancel}>Cancel chapter reset</button>{/if}
  {#if job && job.state !== "idle"}<span role="status">Chapter {job.chapter}: {job.completed}/{job.total} verses · {job.state}</span>{/if}
  {#if error || job?.error}<span role="alert">{error || job?.error}</span>{/if}
</div>
{/if}
<style>
  .chapter-reset { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: var(--fs-2xs); }
  button { font: inherit; height: 28px; padding: 0 10px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text-2); cursor: pointer; white-space: nowrap; }
  button:hover:not(:disabled) { border-color: var(--danger); color: var(--danger); }
  button:disabled { opacity: .5; cursor: not-allowed; }
  [role="alert"] { color: var(--danger); }
  .item { display: block; width: 100%; height: auto; padding: 7px 8px; border: 0; border-radius: 6px; background: none; color: var(--danger); text-align: left; white-space: normal; }
  .item:hover:not(:disabled) { background: var(--danger-bg); }
  .item .name { display: block; font-weight: 700; }
  .item small { display: block; margin-top: 2px; color: var(--text-3); font-size: var(--fs-3xs); line-height: 1.35; }
</style>
