<script lang="ts">
  /** The strip above the text for a run of "Align with AI": one line, there
   *  only while a run is under way or has a result to read. It replaces
   *  AutoAlignChapterButton's strip (#488), which also asked for the estimate
   *  and the confirmation; the dialog does that now, for any number of
   *  chapters. The run itself is `autoAlignRun`'s: this shows it, cancels it
   *  and opens the dialog, and it is still there when the dialog is closed. */
  import { project } from "../stores";
  import { autoAlignRun, cancelRun, dismissRun, firstToReview, runTotals } from "../autoAlignRun";

  /** Show the dialog with this run's chapters. */
  export let onOpen: () => void = () => {};
  /** Open the Cross-verse page on these verses of a chapter. */
  export let onOpenReview: (chapter: string, verses: string[]) => void = () => {};

  $: run = $autoAlignRun;
  $: job = run.job;
  $: totals = runTotals(run);
  $: sameProject = run.projectPath === ($project?.path ?? "");
  $: toReview = run.phase === "finished" ? firstToReview(run) : null;
  $: several = run.chapters.length > 1;
  $: where = run.chapters.length === 1 ? `Chapter ${run.chapters[0]}` : `${run.chapters.length} chapters`;

  $: progress = !job ? "" : job.state === "cancelling" ? "Cancelling…"
    : job.currentWindow
      ? `${several ? `ch. ${job.currentWindow.chapter} ` : ""}v.${job.currentWindow.verses[0]}–${job.currentWindow.verses[job.currentWindow.verses.length - 1]}`
      : "Starting…";

  const verses = (value: number): string => `${value} verse${value === 1 ? "" : "s"}`;
  $: counts = `${verses(totals.clean)} clean, ${totals.review} need${totals.review === 1 ? "s" : ""} review`;
</script>

{#if run.phase !== "idle"}
<div class="auto-strip">
  {#if run.phase === "running" && job}
    <span class="progress" role="status">
      <span class="spin" aria-hidden="true" />
      Aligning with AI · {progress} · {totals.windowsDone}/{totals.windowsTotal} windows
    </span>
    <button type="button" class="strip-btn" on:click={onOpen}>Show</button>
    <button type="button" class="strip-btn" on:click={cancelRun} disabled={job.state === "cancelling"}>Cancel</button>
  {:else if job}
    <span class="result" class:mixed={totals.review > 0 || job.state !== "succeeded" || run.lost} role="status">
      {#if run.lost}
        Align with AI: the run can no longer be followed. {counts}.
      {:else if job.state === "cancelled"}
        Cancelled after {totals.windowsDone} of {totals.windowsTotal} windows: {counts}.
      {:else if job.state === "succeeded"}
        {where} aligned: {counts}.
      {:else}
        {where}: the run stopped. {counts}.
      {/if}
    </span>
    {#if toReview && sameProject}
      <button type="button" class="strip-btn" on:click={() => toReview && onOpenReview(toReview.chapter, toReview.verses)}>Open review</button>
    {/if}
    <button type="button" class="strip-btn" on:click={onOpen}>Details</button>
    <button type="button" class="dismiss" on:click={dismissRun} aria-label="Dismiss">×</button>
  {/if}
  {#if run.error}<span class="error" role="alert">{run.error}</span>{/if}
</div>
{/if}

<style>
  /* A row of its own above the editor, only while it has content. */
  .auto-strip { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; flex-shrink: 0; min-height: 32px; padding: 4px 16px; background: var(--surface-2); border-bottom: 1px solid var(--border); }
  .strip-btn { font: inherit; font-size: var(--fs-xs); font-weight: 600; padding: 4px 10px; border-radius: 6px; border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); cursor: pointer; }
  .strip-btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
  .strip-btn:disabled { opacity: 0.6; cursor: not-allowed; }
  .progress, .result { display: inline-flex; align-items: center; gap: 6px; font-size: var(--fs-xs); color: var(--text-2); font-variant-numeric: tabular-nums; }
  .result { color: var(--success); }
  .result.mixed { color: #8A4B05; }
  .dismiss { border: 0; background: none; color: var(--text-3); font-size: var(--fs-md); cursor: pointer; padding: 0 4px; }
  .error { color: var(--danger); font-size: var(--fs-xs); overflow-wrap: anywhere; }
  .spin { width: 12px; height: 12px; border: 2px solid var(--accent-bg); border-top-color: var(--accent); border-radius: 50%; animation: spin .8s linear infinite; display: inline-block; }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
</style>
