<script lang="ts">
  // #428 / #431 / #432 / #433 / #434 / #435: the Paratext QA review queue.
  //
  // The queue is the open book's QA proposals (parsed from its Paratext
  // notes, #427) in Scripture order, with the reviewer's decisions beside
  // them. "Apply and next" edits Bridge's copy of the verse through the one
  // Scripture writer (verse.edit's) after the engine located the exact
  // Original once in the current text, and is recorded as verified only after
  // the saved verse was read back. Reject / Completed manually need a comment;
  // Leave for later is not terminal. Browsing (Previous / Next / Go to verse)
  // never changes the stored target of a proposal: the engine locates it
  // again at apply time. Nothing here writes into Paratext; "Resolve thread in
  // Paratext" is offered as a click once every proposal in the thread has a
  // terminal decision, and goes through the existing outbox.
  import { onDestroy, onMount, tick } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import { askConfirmation } from "../confirmAction";
  import type {
    ParatextReviewFilter, ParatextReviewItem, ParatextReviewPreview, ParatextReviewQueue, ParatextReviewReport,
  } from "../types/paratext";

  export let onClose: () => void;
  /** App's navigateToReportRow: opens the book if needed and selects the verse. */
  export let onNavigate: ((book: string, chapter: string, verse: string) => Promise<void>) | null = null;

  let data: ParatextReviewQueue | null = null;
  let error = "";
  let notice = "";
  let busy = "";
  let tab: "review" | "reports" = "review";
  let position = "";
  let replacement = "";
  let comment = "";
  let preview: ParatextReviewPreview | null = null;
  let previewRequest = 0;
  let report: ParatextReviewReport | null = null;
  let latestHtml = "";
  let latestPath = "";
  let replacementBox: HTMLInputElement | null = null;

  const ROUTE_LABEL: Record<string, string> = {
    literal: "Literal correction", review: "Needs a reviewer's decision", structure: "USFM structure · review only",
    noChange: "No change proposed", legacy: "Older note label", unreadable: "Could not be read",
  };
  const DECISION_LABEL: Record<string, string> = {
    applied: "Applied", rejected: "Rejected", manual: "Completed manually", deferred: "Left for later", reverted: "Reverted",
  };

  $: items = data?.items ?? [];
  $: current = items.find((item) => item.proposalId === position) ?? null;
  $: index = current ? items.indexOf(current) : -1;
  $: canApply = Boolean(current) && (current!.proposal.route === "literal" || current!.proposal.route === "review")
    && current!.proposal.region === "body"
    && ["replace", "alternatives", "delete"].includes(current!.proposal.operation)
    && Boolean(preview?.ok) && !(current!.decision?.decision === "applied" && current!.decision.verified);
  $: isDeletion = Boolean(current) && (current!.proposal.operation === "delete" || replacement.trim() === "");
  $: uncertain = items.filter((item) => item.decision?.decision === "applied" && !item.decision.verified);
  $: resolvable = items.filter((item) => item.thread.complete && !item.threadResolved);

  function fail(cause: unknown): void {
    error = cause instanceof Error ? cause.message : String(cause);
  }

  async function load(status: ParatextReviewFilter | "" = ""): Promise<void> {
    try {
      data = await bridge.paratextReviewQueue(status);
      error = "";
      if (!data.state.sessionStartedAt) {
        const saved = await bridge.paratextReviewSaveState({ sessionStartedAt: new Date().toISOString() });
        data = { ...data, state: saved.state };
      }
      const wanted = data.items.find((item) => item.proposalId === data!.state.position)
        ?? data.items.find((item) => !item.decision || item.decision.decision === "deferred")
        ?? data.items[0] ?? null;
      await show(wanted?.proposalId ?? "", false);
    } catch (cause) {
      fail(cause);
    }
  }

  /** Keep the draft of the item being left, take the next item's. */
  async function show(proposalId: string, saveLeaving = true): Promise<void> {
    if (saveLeaving && current) await keepDraft();
    position = proposalId;
    // Read from `data` itself: `items` is derived and lags one tick when
    // show() runs right after load() replaced data.
    const item = (data?.items ?? []).find((entry) => entry.proposalId === proposalId) ?? null;
    replacement = item?.draft?.replacement ?? item?.decision?.replacement ?? item?.proposal.suggested ?? "";
    if (item && item.proposal.operation === "alternatives" && !item.draft && !item.decision) replacement = "";
    if (item && item.proposal.operation === "delete") replacement = "";
    comment = item?.draft?.comment ?? item?.decision?.comment ?? "";
    notice = "";
    // `current` is derived from `position` and only recomputes after this
    // tick, so the item is passed, not read back.
    await refreshPreview(item);
    if (item) void bridge.paratextReviewSaveState({ position: proposalId }).catch(() => undefined);
  }

  async function refreshPreview(item: ParatextReviewItem | null = current): Promise<void> {
    preview = null;
    if (!item) return;
    const mine = ++previewRequest;
    try {
      const result = await bridge.paratextReviewPreview(item.proposalId, replacement);
      if (mine === previewRequest) preview = result;
    } catch (cause) {
      if (mine === previewRequest) fail(cause);
    }
  }

  async function keepDraft(): Promise<void> {
    if (!current || !data) return;
    const drafts = { ...data.state.drafts };
    const untouched = replacement === (current.proposal.suggested ?? "") && !comment.trim();
    if (untouched || current.decision?.decision === "applied") delete drafts[current.proposalId];
    else drafts[current.proposalId] = { replacement, comment };
    try {
      const saved = await bridge.paratextReviewSaveState({ drafts });
      data = { ...data, state: saved.state };
    } catch {
      // a draft that could not be saved is still on screen
    }
  }

  function replaceItem(item: ParatextReviewItem): void {
    if (!data) return;
    const next = data.items.map((entry) => entry.proposalId === item.proposalId ? item : entry);
    // Siblings in the same thread share its completion.
    for (const entry of next) if (entry.threadId === item.threadId) entry.thread = item.thread;
    const counts = { ...data.counts };
    data = { ...data, items: next, counts };
  }

  async function decide(kind: "applied" | "rejected" | "manual" | "deferred"): Promise<void> {
    if (!current || busy) return;
    if ((kind === "rejected" || kind === "manual") && !comment.trim()) {
      notice = "Say why in the comment first.";
      return;
    }
    if (kind === "applied" && isDeletion) {
      const extent = current.proposal.original;
      const ok = await askConfirmation({
        title: `Delete “${extent}” from ${current.verseRef}?`,
        body: `Exactly this text is removed from the verse: “${extent}”. Nothing else changes.`,
        confirmLabel: "Delete it", danger: true,
      });
      if (!ok) return;
    }
    busy = kind;
    notice = "";
    try {
      const result = await bridge.paratextReviewDecide(current.proposalId, kind, {
        comment: comment.trim(), replacement: kind === "applied" ? replacement : null, confirmDelete: isDeletion,
      });
      replaceItem(result.item);
      await load(data?.status ?? "");
      const verified = result.decision.decision === "applied" ? (result.decision.verified ? " and verified" : ", NOT verified") : "";
      await next(false);
      notice = `${DECISION_LABEL[result.decision.decision]}${verified}.`;
    } catch (cause) {
      fail(cause);
    } finally {
      busy = "";
    }
  }

  async function next(saveLeaving = true): Promise<void> {
    if (!items.length) return;
    const from = index < 0 ? 0 : index + 1;
    const after = items.slice(from).find((item) => !item.decision || item.decision.decision === "deferred")
      ?? items[Math.min(from, items.length - 1)];
    await show(after.proposalId, saveLeaving);
  }

  async function previous(): Promise<void> {
    if (!items.length) return;
    await show(items[Math.max(0, index - 1)].proposalId);
  }

  async function goToVerse(): Promise<void> {
    if (!current || !onNavigate) return;
    await keepDraft();
    await onNavigate(current.book, current.chapter, current.verse);
  }

  async function changeFilter(event: Event): Promise<void> {
    const status = (event.target as HTMLSelectElement).value as ParatextReviewFilter;
    await keepDraft();
    await bridge.paratextReviewSaveState({ status });
    await load(status);
  }

  async function resolveThread(item: ParatextReviewItem): Promise<void> {
    if (busy) return;
    busy = `resolve:${item.threadId}`;
    try {
      const result = await bridge.paratextResolveThread(item.threadId, "note", item.threadId);
      notice = result.item?.status === "sent"
        ? "Resolve sent to Paratext; the thread shows as resolved once Bridge has read the file again."
        : `Resolve queued for Paratext. ${result.item?.lastError ?? ""}`;
    } catch (cause) {
      fail(cause);
    } finally {
      busy = "";
    }
  }

  async function revertLatest(): Promise<void> {
    if (busy) return;
    const ok = await askConfirmation({
      title: "Revert the latest verified correction?",
      body: "The verse is restored to its text before that correction, only if nobody changed it since. The decision history is kept.",
      confirmLabel: "Revert", danger: true,
    });
    if (!ok) return;
    busy = "revert";
    try {
      const result = await bridge.paratextReviewRevertLatest();
      notice = `Reverted ${result.decision.verseRef}${result.decision.revertVerified ? " and verified" : " (NOT verified)"}.`;
      await load(data?.status ?? "");
    } catch (cause) {
      fail(cause);
    } finally {
      busy = "";
    }
  }

  async function exportCsv(): Promise<void> {
    if (busy) return;
    try {
      const path = await bridge.pickSavePath(`paratext-review-${data?.book ?? "book"}.csv`);
      if (!path) return;
      busy = "csv";
      const result = await bridge.paratextReviewExportCsv(path);
      notice = `Wrote ${result.count} decision${result.count === 1 ? "" : "s"} to ${result.path}`;
    } catch (cause) {
      fail(cause);
    } finally {
      busy = "";
    }
  }

  async function saveReport(): Promise<void> {
    if (busy) return;
    busy = "report";
    try {
      report = await bridge.paratextReviewReport();
      if (report.written) {
        latestHtml = report.html;
        latestPath = report.path;
      }
    } catch (cause) {
      fail(cause);
    } finally {
      busy = "";
    }
  }

  async function viewLatest(): Promise<void> {
    try {
      const latest = await bridge.paratextReviewLatestReport();
      latestHtml = latest.html;
      latestPath = latest.path;
      if (!latest.path) notice = "No report has been saved for this book yet.";
    } catch (cause) {
      fail(cause);
    }
  }

  async function copyPath(): Promise<void> {
    try {
      await navigator.clipboard.writeText(latestPath);
      notice = "Report path copied; open it in your browser.";
    } catch {
      notice = latestPath;
    }
  }

  function usePreset(text: string): void {
    comment = text;
  }

  function onKey(event: KeyboardEvent): void {
    if (event.key === "Escape") void close();
  }

  async function close(): Promise<void> {
    await keepDraft();
    onClose();
  }

  onMount(() => { void load(); });
  onDestroy(() => { previewRequest += 1; });

  const when = (value: string): string => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  };
</script>

<svelte:window on:keydown={onKey} />

<div class="rq-backdrop" role="presentation">
  <div class="rq-dialog" role="dialog" aria-modal="true" aria-label="Paratext review queue" data-testid="paratext-review-queue">
    <header class="rq-head">
      <h2>Paratext review queue{data ? ` · ${data.book}` : ""}</h2>
      {#if data}
        <label class="rq-filter">Show
          <select value={data.status} on:change={changeFilter}>
            <option value="unresolved">Unresolved notes</option>
            <option value="resolved">Resolved notes</option>
            <option value="all">All notes</option>
          </select>
        </label>
        <span class="rq-progress" role="status">
          {index >= 0 ? index + 1 : 0} of {data.counts.total} · {data.counts.undecided} undecided · {data.counts.applied} applied · {data.counts.rejected} rejected · {data.counts.manual} manual · {data.counts.deferred} later
        </span>
      {/if}
      <div class="rq-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "review"} class:on={tab === "review"} on:click={() => (tab = "review")}>Review</button>
        <button type="button" role="tab" aria-selected={tab === "reports"} class:on={tab === "reports"} on:click={() => (tab = "reports")}>Reports / recovery{uncertain.length || resolvable.length ? ` (${uncertain.length + resolvable.length})` : ""}</button>
      </div>
      <button type="button" class="rq-close" on:click={close} aria-label="Close the review queue">Close</button>
    </header>

    {#if error}<p class="rq-msg rq-error" role="alert">{error}</p>{/if}
    {#if notice}<p class="rq-msg" role="status">{notice}</p>{/if}

    {#if !data}
      <p class="rq-msg">Reading the queue…</p>
    {:else if tab === "review"}
      <div class="rq-body">
        <ol class="rq-list" aria-label="Proposals in Scripture order">
          {#each items as item (item.proposalId)}
            <li>
              <button type="button" class="rq-row" class:on={item.proposalId === position} on:click={() => show(item.proposalId)}>
                <span class="rq-ref">{item.verseRef}</span>
                <span class="rq-cat">{item.proposal.category}</span>
                {#if item.decision}<span class="rq-badge {item.decision.decision}">{DECISION_LABEL[item.decision.decision]}</span>{/if}
                {#if item.proposal.route === "unreadable"}<span class="rq-badge unreadable">unreadable</span>{/if}
              </button>
            </li>
          {/each}
          {#if !items.length}<li class="rq-msg">No proposals in this scope.</li>{/if}
        </ol>

        <section class="rq-main" aria-live="polite">
          {#if current}
            {@const p = current.proposal}
            <div class="rq-title">
              <strong>{current.verseRef}</strong>
              <span>{current.threadResolved ? "thread resolved in Paratext" : "thread open in Paratext"}</span>
              {#if onNavigate}<button type="button" class="small-btn" on:click={goToVerse}>Go to verse</button>{/if}
              {#if current.decision}<span class="rq-badge {current.decision.decision}">{DECISION_LABEL[current.decision.decision]} · {when(current.decision.decidedAt)}</span>{/if}
            </div>
            <section class="rq-proposal {p.route}" aria-label="Source proposal">
              <div class="rq-tags">
                <span class="rq-route">{ROUTE_LABEL[p.route]}</span>
                {#if p.category}<span class="rq-tag">{p.category}</span>{/if}
                {#if p.pass}<span class="rq-tag">{p.pass}</span>{/if}
                {#if p.region !== "body"}<span class="rq-tag warn">in the {p.region}</span>{/if}
                {#if p.reviewerDecision}<span class="rq-tag warn">Reviewer decision needed</span>{/if}
                {#if p.confidence}<span class="rq-tag">confidence {p.confidence}</span>{/if}
              </div>
              <dl class="rq-fields">
                <dt>Original</dt><dd class="target">{p.original}</dd>
                <dt>Suggested</dt><dd class="target">{p.suggested}</dd>
                {#if p.reason}<dt>Reason</dt><dd>{p.reason}</dd>{/if}
                {#if p.location}<dt>Location</dt><dd>{p.location}</dd>{/if}
              </dl>
              {#each p.diagnostics as line, i (i)}<p class="rq-msg warn">{line}</p>{/each}
              {#if p.anchorWarning}<p class="rq-msg warn">The pass could not find the Original verbatim; check the target text.</p>{/if}
            </section>

            <section class="rq-target" aria-label="Current verse">
              <h3>Current text</h3>
              {#if preview}
                <p class="target rq-verse">
                  {#if preview.span}{preview.plain.slice(0, preview.span.plainStart)}<mark>{preview.plain.slice(preview.span.plainStart, preview.span.plainEnd)}</mark>{preview.plain.slice(preview.span.plainEnd)}{:else}{preview.plain}{/if}
                </p>
                {#if preview.ok}
                  <h3>After</h3>
                  <p class="target rq-verse rq-after">{preview.after}</p>
                {:else}
                  <p class="rq-msg warn">{preview.reason}</p>
                {/if}
              {:else}
                <p class="rq-msg">Locating the Original…</p>
              {/if}
            </section>

            <section class="rq-edit" aria-label="Correction">
              {#if p.alternatives.length}
                <fieldset class="rq-alts">
                  <legend>Choose the correction</legend>
                  {#each p.alternatives as alt, i (i)}
                    <label><input type="radio" name="alt" value={alt} bind:group={replacement} on:change={() => refreshPreview()} /> <span class="target">{alt}</span></label>
                  {/each}
                </fieldset>
              {/if}
              <label class="rq-field">
                <span>Replacement (exactly what goes in place of the Original)</span>
                <input type="text" class="target" bind:this={replacementBox} bind:value={replacement} on:change={() => refreshPreview()}
                  disabled={p.operation === "delete"} />
              </label>
              <label class="rq-field">
                <span>Comment</span>
                <textarea rows="2" bind:value={comment} />
              </label>
              <div class="rq-presets" aria-label="Comment presets">
                {#each data.presets as preset (preset.id)}
                  <button type="button" class="small-btn" on:click={() => usePreset(preset.text)} title={preset.text}>{preset.label}</button>
                {/each}
              </div>
            </section>

            <div class="rq-actions">
              <button type="button" class="small-btn primary" disabled={!canApply || Boolean(busy)} on:click={() => decide("applied")}
                title={canApply ? "Apply this correction to the verse and go to the next proposal" : preview?.reason || "This proposal cannot be applied as it is"}>
                {busy === "applied" ? "Applying…" : isDeletion ? "Delete and next" : "Apply and next"}</button>
              <button type="button" class="small-btn" disabled={Boolean(busy)} on:click={() => decide("rejected")}>Reject and next</button>
              <button type="button" class="small-btn" disabled={Boolean(busy)} on:click={() => decide("manual")}>Completed manually / no change</button>
              <button type="button" class="small-btn" disabled={Boolean(busy)} on:click={() => decide("deferred")}>Leave for later</button>
              <span class="rq-spacer" />
              <button type="button" class="small-btn" disabled={index <= 0} on:click={previous}>Previous</button>
              <button type="button" class="small-btn" disabled={index >= items.length - 1} on:click={() => next()}>Next</button>
            </div>
            {#if current.thread.complete && !current.threadResolved}
              <p class="rq-msg">Every proposal in this thread has a decision.
                <button type="button" class="small-btn" disabled={Boolean(busy)} on:click={() => resolveThread(current)}>Resolve thread in Paratext</button></p>
            {:else if !current.thread.complete && current.threadOutstanding > 1}
              <p class="rq-msg">{current.threadOutstanding} proposals in this thread; the thread can be resolved once all have a decision.</p>
            {/if}
          {:else}
            <p class="rq-msg">Choose a proposal on the left.</p>
          {/if}
        </section>
      </div>
    {:else}
      <div class="rq-reports">
        <section>
          <h3>Session report</h3>
          <p class="rq-msg">Decisions since {data.state.sessionStartedAt ? when(data.state.sessionStartedAt) : "this session started"}, with before/after snapshots and comments, saved as an offline HTML file in this project's folder.</p>
          <div class="rq-actions">
            <button type="button" class="small-btn primary" disabled={Boolean(busy)} on:click={saveReport}>{busy === "report" ? "Saving…" : "Save session report"}</button>
            <button type="button" class="small-btn" on:click={viewLatest}>View latest report</button>
            <button type="button" class="small-btn" disabled={Boolean(busy)} on:click={exportCsv}>Export decisions as CSV…</button>
          </div>
          {#if report && !report.written}<p class="rq-msg">{report.reason}</p>{/if}
          {#if latestPath}
            <p class="rq-msg">{latestPath} <button type="button" class="small-btn" on:click={copyPath}>Copy path for your browser</button></p>
            <iframe class="rq-report" title="Latest session report" sandbox="allow-same-origin allow-scripts" srcdoc={latestHtml} />
          {/if}
        </section>
        <section>
          <h3>Uncertain edits</h3>
          {#if uncertain.length}
            <ul>
              {#each uncertain as item (item.proposalId)}
                <li class="target">{item.verseRef}: applied but not verified — {item.decision?.unverifiedReason || "the saved text did not read back as intended"}. Check the verse before applying again.</li>
              {/each}
            </ul>
          {:else}
            <p class="rq-msg">None: every applied correction was read back and verified.</p>
          {/if}
          <div class="rq-actions">
            <button type="button" class="small-btn" disabled={Boolean(busy)} on:click={revertLatest}>Revert latest verified correction…</button>
          </div>
        </section>
        <section>
          <h3>Threads ready to resolve in Paratext</h3>
          {#if resolvable.length}
            <ul>
              {#each [...new Map(resolvable.map((item) => [item.threadId, item])).values()] as item (item.threadId)}
                <li>{item.verseRef} · thread {item.threadId}
                  <button type="button" class="small-btn" disabled={Boolean(busy)} on:click={() => resolveThread(item)}>Resolve in Paratext</button></li>
              {/each}
            </ul>
          {:else}
            <p class="rq-msg">None waiting. A resolve retry never reapplies a correction.</p>
          {/if}
        </section>
      </div>
    {/if}
  </div>
</div>

<style>
  .rq-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.35); z-index: 60; display: flex; align-items: center; justify-content: center; padding: 12px; }
  .rq-dialog { width: min(1180px, 100%); height: min(760px, 100%); display: flex; flex-direction: column; background: var(--surface); color: var(--text);
    border: 1px solid var(--border-strong); border-radius: 10px; box-shadow: 0 12px 40px rgba(0,0,0,.3); font-size: var(--fs-xs); min-height: 0; }
  .rq-head { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px; padding: 8px 12px; border-bottom: 1px solid var(--border); }
  .rq-head h2 { margin: 0; font-size: var(--fs-sm); }
  .rq-filter select { font: inherit; margin-left: 4px; }
  .rq-progress { color: var(--text-2); font-size: var(--fs-2xs); }
  .rq-tabs { margin-left: auto; display: flex; gap: 4px; }
  .rq-tabs button { border: 1px solid var(--border-strong); background: var(--surface); color: var(--text-2); border-radius: 6px; padding: 3px 9px; font: inherit; cursor: pointer; }
  .rq-tabs button.on { color: var(--accent); border-color: var(--accent); font-weight: 650; }
  .rq-close { border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); border-radius: 6px; padding: 3px 9px; font: inherit; cursor: pointer; }
  .rq-msg { margin: 4px 12px; color: var(--text-2); font-size: var(--fs-2xs); line-height: 1.45; }
  .rq-error { color: var(--danger); }
  .warn { color: var(--warning); }
  .rq-body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(200px, 280px) minmax(0, 1fr); }
  .rq-list { list-style: none; margin: 0; padding: 6px; overflow-y: auto; border-right: 1px solid var(--border); }
  .rq-row { width: 100%; text-align: left; display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: center; border: 1px solid transparent; background: none;
    color: var(--text); font: inherit; border-radius: 6px; padding: 5px 7px; cursor: pointer; }
  .rq-row.on { border-color: var(--accent); background: var(--accent-bg); }
  .rq-ref { font-weight: 700; }
  .rq-cat { color: var(--text-2); font-size: var(--fs-2xs); }
  .rq-badge { border-radius: 999px; padding: 0 7px; font-size: var(--fs-2xs); font-weight: 700; background: var(--accent-bg); color: var(--accent); }
  .rq-badge.applied { background: var(--success-bg); color: var(--success); }
  .rq-badge.rejected, .rq-badge.unreadable { background: var(--danger-bg, #fee); color: var(--danger); }
  .rq-main { min-height: 0; overflow-y: auto; padding: 10px 12px; display: grid; gap: 8px; align-content: start; }
  .rq-title { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: center; color: var(--text-2); }
  .rq-title strong { color: var(--text); font-size: var(--fs-sm); }
  .rq-proposal { border: 1px dashed var(--border-strong); border-radius: 7px; padding: 7px 9px; display: grid; gap: 4px; }
  .rq-proposal.literal { border-color: var(--success); }
  .rq-proposal.unreadable { border-color: var(--danger); }
  .rq-tags { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: center; font-size: var(--fs-2xs); color: var(--text-2); }
  .rq-route { font-weight: 700; color: var(--text); }
  .rq-tag { border-radius: 999px; padding: 0 6px; background: var(--accent-bg); color: var(--accent); }
  .rq-tag.warn { background: transparent; border: 1px solid var(--warning); }
  .rq-fields { margin: 0; display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 2px 8px; }
  .rq-fields dt { color: var(--text-2); font-weight: 650; }
  .rq-fields dd { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; min-width: 0; max-height: 160px; overflow-y: auto; }
  .rq-target h3, .rq-reports h3 { margin: 4px 0 2px; font-size: var(--fs-2xs); color: var(--text-2); text-transform: uppercase; letter-spacing: .04em; }
  .rq-verse { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.6; max-height: 140px; overflow-y: auto; }
  .rq-verse mark { background: var(--warning-bg, #fe9); color: inherit; }
  .rq-after { color: var(--success); }
  .target { font-family: var(--font-target, inherit); }
  .rq-edit { display: grid; gap: 6px; }
  .rq-alts { border: 1px solid var(--border); border-radius: 6px; padding: 4px 8px; display: grid; gap: 2px; }
  .rq-field { display: grid; gap: 3px; font-size: var(--fs-2xs); font-weight: 650; color: var(--text-2); }
  .rq-field input, .rq-field textarea { width: 100%; box-sizing: border-box; border: 1px solid var(--border); border-radius: 5px; padding: 6px 7px;
    font: inherit; font-weight: 400; color: var(--text); background: var(--surface); resize: vertical; }
  .rq-presets { display: flex; flex-wrap: wrap; gap: 4px; }
  .rq-actions { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .rq-spacer { flex: 1; }
  .small-btn { border-radius: 5px; cursor: pointer; font-size: var(--fs-2xs); padding: 5px 8px; color: var(--text-2);
    background: var(--surface); border: 1px solid var(--border-strong); }
  .small-btn.primary { color: var(--accent); border-color: var(--accent); font-weight: 650; }
  .small-btn:disabled { opacity: .55; cursor: not-allowed; }
  .rq-reports { flex: 1; min-height: 0; overflow-y: auto; padding: 10px 12px; display: grid; gap: 12px; align-content: start; }
  .rq-reports ul { margin: 4px 0; padding-left: 18px; }
  .rq-report { width: 100%; height: 360px; border: 1px solid var(--border); border-radius: 6px; background: #fff; }
</style>
