<script lang="ts">
  // Proofreading (#505): a publishing-level read of chosen books against a
  // reference Bible, by Bridge's AI through the bundled toolkit. One control
  // bar in the dashboard header, directly under Collection QA and built the
  // same way: the summary and one Proofread button idle (it opens
  // ProofreadingStartDialog, where the reference, the books and the estimate
  // are shown and Start begins the run); the progress bar with Pause and
  // Cancel while a run is active. Once any book has been read, a report
  // button opens ProofreadingReportDialog.
  //
  // Starting a run is always the reviewer's choice. While it runs the app is
  // read-only, as during Collection QA (collectionStrip binds the top strip).
  import { onMount } from "svelte";
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";
  import { formatDuration as duration } from "../collectionQa";
  import {
    cancelProofreading, pauseProofreading, proofreading, refreshProofreading, startProofreading,
  } from "../proofreading";
  import type { ProofreadingBook, ProofreadingSnapshot } from "../types/proofreading";
  import ProofreadingStartDialog from "./ProofreadingStartDialog.svelte";
  import ProofreadingReportDialog from "./ProofreadingReportDialog.svelte";

  export let projectName = "";
  export let bookCount = 0;
  /** Another check is running on the dashboard (Collection QA, a single
   *  book's job, a book being opened): the dialog still opens, but Start is
   *  disabled. */
  export let checkRunning = false;

  let error = "";
  let busy = false;
  let startOpen = false;
  let reportOpen = false;

  onMount(() => {
    void refreshProofreading().catch((e) => { error = e instanceof Error ? e.message : String(e); });
  });

  $: snapshot = $proofreading;
  $: active = snapshot ? ["queued", "running", "cancelling"].includes(snapshot.state) : false;
  $: read = snapshot ? snapshot.books.filter((b) => b.state === "done" || b.state === "skipped") : [];
  $: summary = snapshot ? idleSummary(snapshot.books, bookCount) : "";
  $: runningBook = snapshot?.books.find((b) => b.state === "running") ?? null;

  /** One line while idle: how many books have been read, what was found, how
   *  many could not be read, and when the latest finished. */
  function idleSummary(books: ProofreadingBook[], total: number): string {
    const done = books.filter((b) => b.state === "done" || b.state === "skipped");
    const failed = books.filter((b) => b.state === "failed").length;
    const latest = books.map((b) => b.completedAt).filter((at): at is string => Boolean(at)).sort().pop();
    if (!latest && done.length === 0 && failed === 0) return "never run";
    const findings = done.reduce((sum, b) => sum + (b.findings || 0), 0);
    const parts = [`${done.length} of ${total || books.length} books proofread`,
      `${findings.toLocaleString()} ${findings === 1 ? "finding" : "findings"}`];
    if (failed) parts.push(`${failed} not read`);
    if (latest) parts.push(`last run ${new Date(latest).toLocaleString()}`);
    return parts.join(" · ");
  }

  $: line = snapshot && active ? activeLine(snapshot, runningBook) : "";

  /** One line while a run is active: the book and what is being done to it,
   *  books done, findings so far, time. */
  function activeLine(snapshot: ProofreadingSnapshot, runningBook: ProofreadingBook | null): string {
    const lead = snapshot.state === "cancelling" ? "Cancelling"
      : snapshot.paused ? "Pausing after this book"
      : runningBook ? `${runningBook.bookName || runningBook.bookId.toUpperCase()}: ${snapshot.stage}`
      : snapshot.stage || "Starting";
    const parts = [lead, `${snapshot.completedBooks}/${snapshot.totalBooks} books`];
    if (snapshot.findings) parts.push(`${snapshot.findings.toLocaleString()} findings so far`);
    parts.push(`${duration(snapshot.elapsedSeconds)} elapsed`);
    if (snapshot.estimatedRemainingSeconds !== null) parts.push(`about ${duration(snapshot.estimatedRemainingSeconds)} left`);
    return parts.join(" · ");
  }

  async function act(fn: () => Promise<void>): Promise<void> {
    if (busy) return;
    busy = true;
    error = "";
    startOpen = false;
    try {
      await fn();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      busy = false;
    }
  }

  function start(books: string[] | null, force: boolean): void {
    void act(() => startProofreading(books, force));
  }
</script>

<section class="proofreading" class:active aria-label="Proofreading">
  <div class="head">
    <div class="title">
      <h3>Proofreading</h3>
      {#if snapshot && active}
        <span class="status" aria-live="polite">{line}</span>
      {:else if summary}
        <span class="status">{summary}</span>
      {/if}
    </div>
    <div class="actions">
      {#if active}
        <button class="ui-btn" on:click={() => act(() => pauseProofreading(!snapshot?.paused))} disabled={busy || snapshot?.state === "cancelling"}>
          <UiIcon name={snapshot?.paused ? "play" : "pause"} />{snapshot?.paused ? "Resume" : "Pause after this book"}</button>
        <button class="ui-btn danger" on:click={() => act(cancelProofreading)} disabled={busy || snapshot?.state === "cancelling"}><UiIcon name="close" />Cancel</button>
      {:else}
        {#if read.length}
          <button class="ui-btn quiet view-report" aria-haspopup="dialog"
            use:tooltip={"See what the proofreading run found, book by book"}
            on:click={() => (reportOpen = true)}>
            <UiIcon name="proofreadReport" />Proofreading report</button>
        {/if}
        <button class="ui-btn quiet proofread-all" aria-haspopup="dialog" disabled={busy}
          use:tooltip={"Choose the reference Bible and the books, see the estimate, and start a proofreading run"}
          on:click={() => (startOpen = true)}>
          <UiIcon name="proofread" />Proofread</button>
      {/if}
    </div>
  </div>
  {#if snapshot && active}
    <div class="track" aria-hidden="true"><div class="fill" style="width:{snapshot.percent}%"></div></div>
  {/if}
  {#if startOpen && !active}
    <ProofreadingStartDialog {checkRunning} onStart={start} onClose={() => (startOpen = false)} />
  {/if}
  {#if reportOpen}
    <ProofreadingReportDialog {projectName} onClose={() => (reportOpen = false)} />
  {/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if snapshot?.error && !active}
    <p class="error" class:notice={snapshot.halted}>{snapshot.error}{#if snapshot.halted}{" The books already read are kept; start again later to continue."}{/if}</p>
  {/if}
</section>

<style>
  .proofreading { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
  .head { display: flex; align-items: center; justify-content: space-between; gap: 12px 16px; flex-wrap: wrap; }
  .title { display: flex; align-items: baseline; gap: 10px; min-width: 0; flex: 1 1 260px; }
  h3 { margin: 0; font-size: var(--fs-sm); font-weight: 650; color: var(--text); white-space: nowrap; }
  .status { min-width: 0; color: var(--text-2); font-size: var(--fs-3xs); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .active .status { color: var(--accent); font-weight: 600; }
  .actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; flex-shrink: 0; }
  /* The book-list icon style (no border, the icon's colour) with its label:
     green to start, as Collection QA's Check; blue for the report, as the
     header's Project report. */
  .ui-btn.quiet.proofread-all { color: var(--success); }
  .ui-btn.quiet.proofread-all:hover:not(:disabled) { border-color: transparent; background: var(--success-bg); color: var(--success); }
  .ui-btn.quiet.view-report { color: var(--accent); }
  .ui-btn.quiet.view-report:hover:not(:disabled) { border-color: transparent; }
  .track { height: 6px; border-radius: 3px; background: var(--border); overflow: hidden; }
  .fill { height: 100%; background: var(--accent); transition: width .3s linear; }
  .error { margin: 0; color: var(--danger); font-size: var(--fs-3xs); }
  .error.notice { color: var(--warning); }
  @media (prefers-reduced-motion: reduce) { .fill { transition: none; } }
</style>
