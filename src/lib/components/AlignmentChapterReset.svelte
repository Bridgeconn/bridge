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
  async function cancel() {
    cancelled = true;
    if (job?.id) { try { job = await bridge.cancelChapterReset(job.id); } catch (cause) { error = String(cause); } }
  }
</script>
<div class="chapter-reset">
  <button type="button" disabled={busy || working} on:click={run}>{job?.state === "running" || job?.state === "cancelled" || job?.state === "failed" ? "Resume chapter reset" : "Reset chapter alignment"}</button>
  {#if working || job?.state === "running"}<button type="button" on:click={cancel}>Cancel chapter reset</button>{/if}
  {#if job && job.state !== "idle"}<span role="status">Chapter {job.chapter}: {job.completed}/{job.total} verses · {job.state}</span>{/if}
  {#if error || job?.error}<span role="alert">{error || job?.error}</span>{/if}
</div>
<style>
  .chapter-reset { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: var(--fs-xs); padding: 5px 0; }
  button { font: inherit; padding: 5px 9px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text); }
  [role="alert"] { color: var(--danger); }
</style>
