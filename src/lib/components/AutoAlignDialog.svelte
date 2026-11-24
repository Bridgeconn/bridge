<script lang="ts">
  /** "Align with AI" (2026-11-24, Joel): choose one, several or all chapters
   *  of the open book and align them automatically. It replaces "Align chapter
   *  with AI", which could only take the chapter that was open.
   *
   *  Three views of one dialog, chosen by the run's phase (`autoAlignRun`):
   *    choose   -> the chapters as boxes, the cost of the selection worked out
   *                offline, Start. Nothing is sent before Start.
   *    running  -> the same boxes as a progress map; Start's place is taken
   *                by Cancel. The run is the engine's and goes on when this
   *                is closed with the x.
   *    finished -> the result, Resume after a cancel or a failure, Open review.
   *  One main button, in the app's own colours (Joel, 2026-11-24): Start is
   *  the standard primary, Cancel the standard danger, and the x closes.
   *  What is written is the job's business and unchanged: three verses at a
   *  time, asked twice, only what both answers agree on. */
  import { onDestroy } from "svelte";
  import UiIcon from "./UiIcon.svelte";
  import { bridge } from "../api/bridgeClient";
  import { currentChapter, project } from "../stores";
  import {
    autoAlignRun, cancelRun, chapterSummaries, clearRunError, dismissRun, firstToReview, resumeRun,
    runCost, runTotals, startRun, type ChapterRunState, type ChapterRunSummary,
  } from "../autoAlignRun";
  import type { AutoAlignEstimate } from "../types/finding";

  export let onClose: () => void;
  /** Go to a chapter of the open book. */
  export let onOpenChapter: (chapter: string) => void = () => {};
  /** Open the Cross-verse page on these verses of a chapter. */
  export let onOpenReview: (chapter: string, verses: string[]) => void = () => {};

  const message = (value: unknown): string => (value instanceof Error ? value.message : String(value));

  $: chapters = $project?.chapters ?? [];
  $: view = $autoAlignRun.phase === "idle" ? "choose" : $autoAlignRun.phase;
  $: sameProject = $autoAlignRun.projectPath === ($project?.path ?? "");

  // -- choose -----------------------------------------------------------------

  let selected = new Set<string>(
    ($project?.chapters ?? []).includes($currentChapter) ? [$currentChapter] : [],
  );
  /** Where a Shift+click range starts. */
  let anchor: number | null = null;
  /** The box that holds the Tab stop. */
  let active = Math.max(0, ($project?.chapters ?? []).indexOf($currentChapter));
  let grid: HTMLElement | undefined;
  let starting = false;

  $: wanted = chapters.filter((chapter) => selected.has(chapter));

  function toggle(index: number, event: MouseEvent | KeyboardEvent): void {
    const chapter = chapters[index];
    const next = new Set(selected);
    if (event.shiftKey && anchor !== null && anchor !== index) {
      // A range: everything from where the last click was to here, selected.
      const [from, to] = anchor < index ? [anchor, index] : [index, anchor];
      for (const each of chapters.slice(from, to + 1)) next.add(each);
    } else if (next.has(chapter)) {
      next.delete(chapter);
    } else {
      next.add(chapter);
    }
    selected = next;
    anchor = index;
    active = index;
    estimateError = "";
    clearRunError();
  }

  function selectOnly(list: string[]): void {
    selected = new Set(list);
    anchor = null;
    estimateError = "";
    clearRunError();
  }

  function columns(): number {
    const cells = Array.from(grid?.querySelectorAll<HTMLElement>(".cell") ?? []);
    if (!cells.length) return 1;
    const top = cells[0].offsetTop;
    return Math.max(1, cells.filter((cell) => cell.offsetTop === top).length);
  }

  function focusCell(index: number): void {
    active = Math.max(0, Math.min(chapters.length - 1, index));
    grid?.querySelector<HTMLElement>(`[data-index="${active}"]`)?.focus();
  }

  function onGridKey(event: KeyboardEvent): void {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
      event.preventDefault();
      selectOnly(chapters);
      return;
    }
    const step: Record<string, number> = {
      ArrowRight: 1, ArrowLeft: -1, ArrowDown: columns(), ArrowUp: -columns(),
    };
    if (event.key in step) { event.preventDefault(); focusCell(active + step[event.key]); }
    else if (event.key === "Home") { event.preventDefault(); focusCell(0); }
    else if (event.key === "End") { event.preventDefault(); focusCell(chapters.length - 1); }
  }

  // The cost, one chapter at a time, each remembered: a whole book shows a
  // running total instead of one long wait, and a chapter picked, dropped and
  // picked again is worked out once. All of it offline, in the engine.
  let estimates: Record<string, AutoAlignEstimate> = {};
  let estimateError = "";
  let estimating = false;
  let closed = false;
  onDestroy(() => { closed = true; });

  $: known = wanted.filter((chapter) => chapter in estimates);
  $: if (view === "choose" && known.length < wanted.length && !estimating && !estimateError) void estimateMissing();

  async function estimateMissing(): Promise<void> {
    estimating = true;
    try {
      for (;;) {
        const next = chapters.find((chapter) => selected.has(chapter) && !(chapter in estimates));
        if (!next || closed) break;
        const estimate = await bridge.autoAlignEstimate("chapter", [next]);
        estimates = { ...estimates, [next]: estimate };
      }
    } catch (value) {
      estimateError = message(value);
    } finally {
      estimating = false;
    }
  }

  $: total = known.reduce((sum, chapter) => {
    const estimate = estimates[chapter];
    return {
      windows: sum.windows + estimate.windows,
      calls: sum.calls + estimate.calls,
      tokens: sum.tokens + estimate.estimatedInputTokens + estimate.estimatedOutputTokens,
      usd: sum.usd + estimate.estimatedCostUSD,
      plan: sum.plan || Boolean(estimate.planUsage),
    };
  }, { windows: 0, calls: 0, tokens: 0, usd: 0, plan: false });
  $: costReady = wanted.length > 0 && known.length === wanted.length;

  const count = (value: number, one: string, many = `${one}s`): string =>
    `${value.toLocaleString()} ${value === 1 ? one : many}`;

  async function start(): Promise<void> {
    if (!costReady || starting) return;
    starting = true;
    try {
      await startRun(wanted);
    } finally {
      starting = false;
    }
  }

  // -- running and finished ---------------------------------------------------

  $: job = $autoAlignRun.job;
  $: summaries = view === "choose" ? [] : chapterSummaries($autoAlignRun);
  $: totals = runTotals($autoAlignRun);
  $: toReview = view === "finished" ? firstToReview($autoAlignRun) : null;
  $: canResume = view === "finished" && !$autoAlignRun.lost && Boolean(job) && ["failed", "cancelled"].includes(job?.state ?? "");
  let resuming = false;

  const STATE_WORD: Record<ChapterRunState, string> = {
    waiting: "waiting", running: "in progress", clean: "aligned", review: "needs review",
    failed: "had failures", partial: "not finished",
  };

  function describe(summary: ChapterRunSummary): string {
    const parts = [`Chapter ${summary.chapter}: ${STATE_WORD[summary.state]}`];
    if (summary.clean) parts.push(`${count(summary.clean, "verse")} clean`);
    if (summary.review) parts.push(`${count(summary.review, "verse")} to review`);
    if (summary.failed) parts.push(`${count(summary.failed, "window")} failed`);
    return parts.join(", ");
  }

  $: progressLine = !job ? "" : job.state === "cancelling" ? "Cancelling after the request in flight…"
    : job.currentWindow
      ? `Chapter ${job.currentWindow.chapter}, verses ${job.currentWindow.verses[0]}–${job.currentWindow.verses[job.currentWindow.verses.length - 1]}`
      : "Starting…";

  $: headline = view !== "finished" || !job ? ""
    : $autoAlignRun.lost ? "The run can no longer be followed"
    : job.state === "succeeded" ? `Aligned ${count($autoAlignRun.chapters.length, "chapter")}`
    : job.state === "cancelled" ? `Cancelled after ${totals.windowsDone} of ${totals.windowsTotal} windows`
    : totals.windowsDone >= totals.windowsTotal ? `Finished, with ${count(totals.windowsFailed, "window")} that failed`
    : "Stopped before the end";

  async function resume(): Promise<void> {
    resuming = true;
    try { await resumeRun(); } finally { resuming = false; }
  }

  function openChapter(chapter: string): void {
    onOpenChapter(chapter);
    onClose();
  }

  function openReview(): void {
    if (!toReview) return;
    onOpenReview(toReview.chapter, toReview.verses);
    onClose();
  }

  function done(): void {
    dismissRun();
    onClose();
  }

  // -- the dialog itself ------------------------------------------------------

  // The native <dialog>, as AddBooksDialog: showModal() keeps focus inside and
  // makes the rest of the page inert. Escape closes; a run keeps going.
  function modal(node: HTMLDialogElement) {
    const previousFocus = document.activeElement;
    if (typeof node.showModal === "function") node.showModal();
    else node.setAttribute("open", "");
    node.querySelector<HTMLElement>("h2")?.focus();
    const onCancel = (event: Event) => { event.preventDefault(); onClose(); };
    node.addEventListener("cancel", onCancel);
    return { destroy() {
      node.removeEventListener("cancel", onCancel);
      if (typeof node.close === "function" && node.open) node.close();
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    } };
  }
</script>

<dialog class="align-ai" aria-modal="true" aria-labelledby="align-ai-title" aria-describedby="align-ai-about" use:modal>
  <header>
    <span class="mark" aria-hidden="true"><UiIcon name="sparkle" /></span>
    <div class="heading">
      <h2 id="align-ai-title" tabindex="-1">Align with AI</h2>
      <p id="align-ai-about">
        {#if view === "choose"}
          Choose the chapters to align.
        {:else if view === "running"}
          Aligning in the background.
        {:else}
          What the run did, chapter by chapter.
        {/if}
      </p>
    </div>
    <button type="button" class="close" aria-label="Close" on:click={onClose}><UiIcon name="close" /></button>
  </header>

  {#if view === "choose"}
    <div class="tools">
      <div class="picks" role="group" aria-label="Quick selection">
        <button type="button" class="pick" on:click={() => selectOnly(chapters.includes($currentChapter) ? [$currentChapter] : [])}>This chapter</button>
        <button type="button" class="pick" on:click={() => selectOnly(chapters)}>Select all</button>
        <button type="button" class="pick" on:click={() => selectOnly([])} disabled={selected.size === 0}>Clear</button>
      </div>
      <span class="tally" role="status">{wanted.length} of {chapters.length} selected</span>
    </div>
    <div class="body">
      <!-- The keys move between the boxes, which are the buttons. -->
      <!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
      <div class="grid" role="group" aria-label="Chapters" bind:this={grid} on:keydown={onGridKey}>
        {#each chapters as chapter, index (chapter)}
          <button type="button" class="cell" class:on={selected.has(chapter)} class:here={chapter === $currentChapter}
            aria-pressed={selected.has(chapter)} aria-label={`Chapter ${chapter}${chapter === $currentChapter ? " (open now)" : ""}`}
            data-index={index} tabindex={index === active ? 0 : -1}
            on:focus={() => (active = index)} on:click={(event) => toggle(index, event)}>{chapter}</button>
        {/each}
      </div>
      <p class="hint">Shift+click selects a range.</p>
    </div>
    <footer>
      <div class="summary" role="status" aria-live="polite">
        {#if wanted.length === 0}
          <span class="muted">Select at least one chapter.</span>
        {:else if estimateError}
          <span class="problem" role="alert">The cost could not be worked out: {estimateError}</span>
          <button type="button" class="link" on:click={() => (estimateError = "")}>Try again</button>
        {:else if !costReady}
          <span class="working"><span class="spin" aria-hidden="true" /> Working out the cost… {known.length} of {wanted.length} chapters</span>
        {:else}
          <span class="figures">
            <b>{count(wanted.length, "chapter")}</b>
            <span>{count(total.calls, "request")}</span>
            <span>~{Math.round(total.tokens / 1000).toLocaleString()}k tokens</span>
          </span>
          <span class="cost" class:plan={total.plan}>{total.plan ? "uses your ChatGPT plan allowance" : runCost(total.usd)}</span>
        {/if}
      </div>
      {#if $autoAlignRun.error}<p class="problem" role="alert">{$autoAlignRun.error}</p>{/if}
      <div class="actions">
        <button type="button" class="ui-btn primary" on:click={start} disabled={!costReady || starting}>{starting ? "Starting…" : "Start"}</button>
      </div>
    </footer>
  {:else}
    <div class="body">
      {#if !sameProject}
        <p class="hint other">This run belongs to another book. It is shown here until it ends.</p>
      {/if}
      <div class="grid" role="group" aria-label="Chapters of this run">
        {#each summaries as summary (summary.chapter)}
          {#if view === "finished" && sameProject}
            <button type="button" class="cell done {summary.state}" title={`${describe(summary)}. Open this chapter`}
              aria-label={`${describe(summary)}. Open this chapter`} on:click={() => openChapter(summary.chapter)}>{summary.chapter}</button>
          {:else}
            <span class="cell done {summary.state}" role="img" title={describe(summary)} aria-label={describe(summary)}>{summary.chapter}</span>
          {/if}
        {/each}
      </div>
      <ul class="legend" aria-hidden="true">
        <li><i class="swatch waiting" /> Waiting</li>
        <li><i class="swatch running" /> In progress</li>
        <li><i class="swatch clean" /> Aligned</li>
        <li><i class="swatch review" /> Needs review</li>
        <li><i class="swatch failed" /> Had failures</li>
      </ul>
    </div>
    <footer>
      {#if view === "running" && job}
        <div class="summary" role="status" aria-live="polite">
          <span class="working"><span class="spin" aria-hidden="true" /> {progressLine}</span>
          <span class="muted">{totals.windowsDone} of {totals.windowsTotal} windows</span>
        </div>
        <progress class="bar" max={Math.max(1, totals.windowsTotal)} value={totals.windowsDone} aria-label="Progress of the run" />
        {#if $autoAlignRun.error}<p class="problem" role="alert">{$autoAlignRun.error}</p>{/if}
        <div class="actions">
          <span class="note">Finished chapters keep their alignment.</span>
          <button type="button" class="ui-btn danger" on:click={cancelRun} disabled={job.state === "cancelling"}>{job.state === "cancelling" ? "Cancelling…" : "Cancel"}</button>
        </div>
      {:else}
        <div class="summary result" class:mixed={totals.review > 0 || job?.state !== "succeeded"} role="status">
          <b>{headline}</b>
          <span class="muted">{count(totals.clean, "verse")} clean · {totals.review === 1 ? "1 needs review" : `${totals.review.toLocaleString()} need review`}{totals.windowsFailed ? ` · ${count(totals.windowsFailed, "window")} failed` : ""}</span>
        </div>
        {#if $autoAlignRun.error}<p class="problem" role="alert">{$autoAlignRun.error}</p>{/if}
        <div class="actions">
          <button type="button" class="ui-btn quiet" on:click={dismissRun}>Align more chapters</button>
          <span class="grow" />
          {#if canResume}<button type="button" class="ui-btn" on:click={resume} disabled={resuming} title="Run what is left: the chapters not reached and the windows that failed">{resuming ? "Resuming…" : "Resume"}</button>{/if}
          {#if toReview && sameProject}<button type="button" class="ui-btn" on:click={openReview}>Open review</button>{/if}
          <button type="button" class="ui-btn primary" on:click={done}>Done</button>
        </div>
      {/if}
    </footer>
  {/if}
</dialog>

<style>
  .align-ai { width: min(600px, calc(100% - 32px)); max-height: min(720px, calc(100dvh - 40px)); padding: 0; border: 1px solid var(--border); border-radius: 18px; background: var(--surface); color: var(--text); box-shadow: 0 24px 80px rgb(0 0 0 / 20%); overflow: hidden; }
  .align-ai[open] { display: flex; flex-direction: column; }
  .align-ai::backdrop { background: rgb(15 23 42 / 38%); backdrop-filter: blur(3px); }

  header { display: flex; align-items: flex-start; gap: 14px; padding: 22px 22px 14px; flex-shrink: 0; }
  /* The app's own colours throughout, as its other dialogs (AddBooksDialog). */
  .mark { display: grid; place-items: center; width: 40px; height: 40px; flex-shrink: 0; border-radius: 12px; color: var(--accent); background: var(--accent-bg); }
  .mark :global(svg) { width: 20px; height: 20px; }
  .heading { min-width: 0; flex: 1; }
  h2 { margin: 0; font-size: var(--fs-2xl); line-height: 1.4; }
  h2:focus { outline: none; }
  header p { margin: 4px 0 0; color: var(--text-2); font-size: var(--fs-xs); line-height: 1.55; }
  /* The close button of the app's dialogs: quiet, red when pointed at. */
  .close { display: grid; place-items: center; width: 34px; height: 34px; min-height: 34px; flex-shrink: 0; padding: 0; border: 0; border-radius: 8px; background: transparent; color: var(--text-2); cursor: pointer; transition: color .15s, background .15s; }
  .close:hover, .close:focus-visible { background: var(--danger-bg); color: var(--danger); }
  .close :global(svg) { width: 18px; height: 18px; }
  button { font: inherit; }
  button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

  .tools { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; padding: 0 22px 10px; flex-shrink: 0; }
  .picks { display: inline-flex; gap: 6px; flex-wrap: wrap; }
  .pick { padding: 4px 11px; border: 1px solid var(--border-strong); border-radius: 999px; background: var(--surface); color: var(--text-2); font-size: var(--fs-2xs); font-weight: 600; cursor: pointer; }
  .pick:hover:not(:disabled) { border-color: var(--accent); background: var(--accent-bg); color: var(--accent); }
  .pick:disabled { opacity: .5; cursor: not-allowed; }
  .tally { color: var(--text-3); font-size: var(--fs-2xs); font-variant-numeric: tabular-nums; }

  /* The one part that scrolls: Psalms has 150 chapters. */
  .body { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; scrollbar-gutter: stable; padding: 4px 22px 12px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(42px, 1fr)); gap: 6px; }
  .cell { position: relative; display: grid; place-items: center; min-width: 0; height: 38px; padding: 0; box-sizing: border-box; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-2); color: var(--text); font-size: var(--fs-xs); font-weight: 600; font-variant-numeric: tabular-nums; transition: background .12s, border-color .12s, color .12s, transform .12s; }
  button.cell { cursor: pointer; }
  button.cell:hover { border-color: var(--accent); background: var(--accent-bg); color: var(--accent); }
  button.cell:active { transform: scale(.96); }
  /* Selected: the accent fill the chapter navigator uses for its chapter. */
  .cell.on { border-color: var(--accent); background: var(--accent); color: #fff; }
  button.cell.on:hover { background: var(--accent); color: #fff; filter: brightness(.94); }
  /* The chapter that is open in the editor. */
  .cell.here::after { content: ""; position: absolute; bottom: 4px; left: 50%; width: 4px; height: 4px; margin-left: -2px; border-radius: 50%; background: currentColor; opacity: .7; }
  .hint { margin: 10px 0 0; color: var(--text-3); font-size: var(--fs-2xs); line-height: 1.5; }
  .hint.other { margin: 0 0 10px; color: var(--warning); }

  /* The same boxes as the progress map. */
  .cell.done { cursor: default; }
  button.cell.done { cursor: pointer; }
  .cell.waiting { color: var(--text-3); }
  .cell.running { border-color: var(--accent); background: var(--accent-bg); color: var(--accent); animation: pulse 1.6s ease-in-out infinite; }
  .cell.clean { border-color: color-mix(in srgb, var(--success) 45%, transparent); background: var(--success-bg); color: var(--success); }
  .cell.review { border-color: color-mix(in srgb, var(--warning) 50%, transparent); background: var(--warning-bg); color: #8A4B05; }
  .cell.failed { border-color: color-mix(in srgb, var(--danger) 45%, transparent); background: var(--danger-bg); color: var(--danger); }
  .cell.partial { border-style: dashed; border-color: var(--border-strong); color: var(--text-2); }
  button.cell.clean:hover, button.cell.review:hover, button.cell.failed:hover, button.cell.partial:hover, button.cell.waiting:hover { filter: brightness(.96); }
  button.cell.clean:hover { border-color: var(--success); background: var(--success-bg); color: var(--success); }
  button.cell.review:hover { border-color: var(--warning); background: var(--warning-bg); color: #8A4B05; }
  button.cell.failed:hover { border-color: var(--danger); background: var(--danger-bg); color: var(--danger); }
  @keyframes pulse { 0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 34%, transparent); } 50% { box-shadow: 0 0 0 5px transparent; } }

  .legend { display: flex; flex-wrap: wrap; gap: 4px 14px; margin: 12px 0 0; padding: 0; list-style: none; color: var(--text-3); font-size: var(--fs-2xs); }
  .legend li { display: inline-flex; align-items: center; gap: 6px; }
  .swatch { width: 10px; height: 10px; border-radius: 3px; border: 1px solid var(--border-strong); background: var(--surface-2); }
  .swatch.running { border-color: var(--accent); background: var(--accent-bg); }
  .swatch.clean { border-color: var(--success); background: var(--success-bg); }
  .swatch.review { border-color: var(--warning); background: var(--warning-bg); }
  .swatch.failed { border-color: var(--danger); background: var(--danger-bg); }

  footer { flex-shrink: 0; display: flex; flex-direction: column; gap: 10px; padding: 12px 22px 18px; border-top: 1px solid var(--border); background: var(--surface-2); }
  .summary { display: flex; align-items: center; justify-content: space-between; gap: 6px 12px; flex-wrap: wrap; min-height: 26px; font-size: var(--fs-xs); font-variant-numeric: tabular-nums; }
  .figures { display: inline-flex; align-items: baseline; gap: 4px 12px; flex-wrap: wrap; color: var(--text-2); }
  .figures b { color: var(--text); }
  .cost { padding: 3px 10px; border-radius: 999px; background: var(--accent-bg); color: var(--accent); font-weight: 700; white-space: nowrap; }
  .cost.plan { white-space: normal; }
  .muted { color: var(--text-3); }
  .working { display: inline-flex; align-items: center; gap: 8px; color: var(--text-2); }
  .result b { color: var(--success); }
  .result.mixed b { color: #8A4B05; }
  .problem { margin: 0; color: var(--danger); font-size: var(--fs-xs); line-height: 1.5; overflow-wrap: anywhere; }
  .link { padding: 0; border: 0; background: none; color: var(--accent); font-size: var(--fs-xs); font-weight: 600; text-decoration: underline; cursor: pointer; }
  .bar { width: 100%; height: 6px; border: 0; border-radius: 999px; overflow: hidden; appearance: none; background: var(--border); accent-color: var(--accent); }
  .bar::-webkit-progress-bar { background: var(--border); border-radius: 999px; }
  .bar::-webkit-progress-value { background: var(--accent); border-radius: 999px; transition: width .3s; }
  .actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
  .note { flex: 1 1 220px; min-width: 0; color: var(--text-3); font-size: var(--fs-2xs); line-height: 1.45; }
  .grow { flex: 1; }
  .spin { width: 12px; height: 12px; flex: none; border: 2px solid var(--accent-bg); border-top-color: var(--accent); border-radius: 50%; animation: spin .8s linear infinite; display: inline-block; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* A narrow window: the dialog is the page. */
  @media (max-width: 520px) {
    header { padding: 16px 16px 10px; gap: 10px; }
    .tools, .body { padding-left: 16px; padding-right: 16px; }
    footer { padding: 10px 16px 14px; }
    .grid { grid-template-columns: repeat(auto-fill, minmax(38px, 1fr)); gap: 5px; }
    .actions .ui-btn { flex: 1 1 auto; }
    .grow { display: none; }
  }
  @media (prefers-reduced-motion: reduce) {
    .cell, .bar::-webkit-progress-value { transition: none; }
    .cell.running, .spin { animation: none; }
  }
</style>
