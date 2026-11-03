<script lang="ts">
  // #428 / #429 / #430 / #431 / #432 / #433 / #434 / #435: the Paratext QA
  // review queue.
  //
  // The queue is the QA proposals (parsed from Paratext notes, #427) of the
  // books in scope -- the open book, or several books of the collection,
  // scanned from the Paratext notes index without opening a sibling -- in
  // Scripture order from a chosen starting book, with the reviewer's
  // decisions beside them. "Apply and next" edits Bridge's copy through the
  // engine's writers after it located the exact Original once in the
  // proposal's own region (body, footnote, cross-reference, heading), and is
  // recorded as verified only after the saved text was read back; an
  // introduction correction or a heading-marker rename exists only in
  // Paratext and needs "Also write to Paratext". Reject / Completed manually
  // need a comment; Leave for later is not terminal. Browsing (Previous /
  // Next / Go to verse / Show in Paratext) never changes the stored target of
  // a proposal: the engine locates it again at apply time. A proposal of a
  // book that is not open is read here and decided after "Open <book>".
  // "Resolve thread in Paratext" is offered once every proposal in the
  // thread has a terminal decision and goes through the existing outbox,
  // behind the engine's completion gate. The Reports / recovery tab holds
  // the saved reports, interrupted applies to reconcile, saved resolves that
  // have not gone yet, and the checked revert.
  import { onDestroy, onMount, tick } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import { askConfirmation } from "../confirmAction";
  import { project } from "../stores";
  import { refreshParatextReviewEditor } from "../paratextReviewRefresh";
  import type {
    ParatextReviewFilter, ParatextReviewItem, ParatextReviewPreview, ParatextReviewQueue, ParatextReviewReport,
    ParatextReviewReports, ParatextReviewScope, ParatextReconcileOutcome, ParatextReviewDecision,
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
  let reports: ParatextReviewReports | null = null;
  let latestHtml = "";
  let latestPath = "";
  let replacementBox: HTMLInputElement | null = null;
  let scopeOpen = false;
  let scopeBooks: string[] = [];
  let scopeStart = "";
  let loadedFor = "";
  // DECISIONS 2026-11-02 (Benz): after a verified Bridge apply the same exact
  // replacement may also be written into the linked Paratext project. Off by
  // default; required for a region Bridge keeps no copy of.
  let writeParatext = false;

  function paratextOutcome(decision: { paratext?: { status: string; lastError: string; verified?: boolean } }): string {
    const pt = decision.paratext;
    if (!pt) return "";
    if (pt.status === "sent") return pt.verified ? " Written to Paratext and read back." : " Written to Paratext but NOT verified there.";
    if (pt.status === "refused") return ` Paratext refused the write: ${pt.lastError}`;
    if (pt.status === "not_sent") return ` ${pt.lastError}`;
    return ` Queued for Paratext. ${pt.lastError || "It goes when Paratext is available."}`;
  }

  const ROUTE_LABEL: Record<string, string> = {
    literal: "Literal correction", review: "Needs a reviewer's decision", structure: "USFM structure",
    noChange: "No change proposed", legacy: "Older note label", unreadable: "Could not be read",
  };
  const DECISION_LABEL: Record<string, string> = {
    applied: "Applied", rejected: "Rejected", manual: "Completed manually", deferred: "Left for later", reverted: "Reverted",
  };
  const REGION_LABEL: Record<string, string> = {
    body: "verse text", introduction: "book introduction", heading: "heading", footnote: "footnote",
    crossReference: "cross-reference", structure: "USFM structure",
  };
  const CLASSIFIED_LABEL: Record<string, string> = {
    verified: "the text now reads as the apply intended",
    notApplied: "the text still reads as before the apply",
    conflict: "the text reads as neither: another edit, or a partial save",
  };

  $: items = data?.items ?? [];
  $: current = items.find((item) => item.proposalId === position) ?? null;
  $: index = current ? items.indexOf(current) : -1;
  $: region = current?.proposal.region ?? "body";
  $: paratextOnly = region === "introduction" || region === "structure";
  $: multiBook = (data?.booksInScope?.length ?? 1) > 1;
  $: canApply = Boolean(current) && current!.openBook !== false
    && (current!.proposal.route === "literal" || current!.proposal.route === "review" || current!.proposal.route === "structure")
    && Boolean(preview?.ok)
    && (!paratextOnly || writeParatext)
    && (region === "structure" || ["replace", "alternatives", "delete"].includes(current!.proposal.operation))
    && !(current!.decision?.decision === "applied" && current!.decision.verified);
  $: isDeletion = Boolean(current) && region !== "structure" && (current!.proposal.operation === "delete" || replacement.trim() === "");
  // #446: a verified apply is shown from its saved before/after snapshots.
  // Locating the Original in the already-corrected text previewed the
  // correction applied a second time ("a footfootnote") whenever the
  // replacement contains the Original; the preview RPC is not called at all.
  $: applied = appliedSnapshot(current);

  function appliedSnapshot(item: ParatextReviewItem | null): ParatextReviewDecision | null {
    const d = item?.decision;
    return d && d.decision === "applied" && d.verified && d.before && d.after ? d : null;
  }
  $: uncertain = items.filter((item) => item.decision?.decision === "applied" && !item.decision.verified);
  $: resolvable = items.filter((item) => item.thread.complete && !item.threadResolved && item.openBook !== false);
  $: pendingResolves = reports?.pendingResolves ?? data?.pendingResolves ?? [];
  $: recoveryCount = uncertain.length + resolvable.length + pendingResolves.length;
  $: firstWrapped = items.findIndex((item) => item.wrapped);
  // A book switch (Go to verse into a sibling) reloads the queue; the engine
  // keeps the scope and the position per linked project.
  $: if ($project?.path && loadedFor && $project.path !== loadedFor) void load();

  function fail(cause: unknown): void {
    error = cause instanceof Error ? cause.message : String(cause);
  }

  async function refreshEditor(path: string, decision: ParatextReviewDecision): Promise<string> {
    try {
      await refreshParatextReviewEditor(path, decision);
      return "";
    } catch {
      // The write already finished: a read failure must not invite Apply again.
      return " The decision was saved, but the editor could not refresh. Reopen the book to reload its saved text.";
    }
  }

  async function load(status: ParatextReviewFilter | "" = "", scope: ParatextReviewScope | null = null): Promise<void> {
    try {
      loadedFor = $project?.path ?? "";
      data = await bridge.paratextReviewQueue(status, scope);
      error = "";
      if (!data.state.sessionStartedAt) {
        const saved = await bridge.paratextReviewSaveState({ sessionStartedAt: new Date().toISOString() });
        data = { ...data, state: saved.state };
      }
      scopeBooks = [...(data.booksInScope ?? [data.book])];
      scopeStart = data.state.scope?.startBook ?? "";
      if (data.staleDraftsDropped?.length) {
        notice = `${data.staleDraftsDropped.length} saved draft${data.staleDraftsDropped.length === 1 ? "" : "s"} belonged to a proposal that changed in Paratext and ${data.staleDraftsDropped.length === 1 ? "was" : "were"} discarded.`;
      }
      const wanted = data.items.find((item) => item.proposalId === data!.state.position)
        ?? data.items.find((item) => !item.decision || item.decision.decision === "deferred")
        ?? data.items[0] ?? null;
      await show(wanted?.proposalId ?? "", false, Boolean(data.staleDraftsDropped?.length));
    } catch (cause) {
      fail(cause);
    }
  }

  /** Keep the draft of the item being left, take the next item's. */
  async function show(proposalId: string, saveLeaving = true, keepNotice = false): Promise<void> {
    if (saveLeaving && current) await keepDraft();
    position = proposalId;
    // Read from `data` itself: `items` is derived and lags one tick when
    // show() runs right after load() replaced data.
    const item = (data?.items ?? []).find((entry) => entry.proposalId === proposalId) ?? null;
    replacement = item?.draft?.replacement ?? item?.decision?.replacement ?? item?.proposal.suggested ?? "";
    if (item && item.proposal.operation === "alternatives" && !item.draft && !item.decision) replacement = "";
    if (item && item.proposal.operation === "delete") replacement = "";
    comment = item?.draft?.comment ?? item?.decision?.comment ?? "";
    if (!keepNotice) notice = "";
    // `current` is derived from `position` and only recomputes after this
    // tick, so the item is passed, not read back.
    await refreshPreview(item);
    if (item) void bridge.paratextReviewSaveState({ position: proposalId }).catch(() => undefined);
  }

  async function refreshPreview(item: ParatextReviewItem | null = current): Promise<void> {
    preview = null;
    if (!item || item.openBook === false || appliedSnapshot(item)) return;
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
    const expectedPath = $project?.path ?? "";
    if (current.openBook === false) {
      notice = `This proposal is in ${current.book}; open that book first.`;
      return;
    }
    if ((kind === "rejected" || kind === "manual") && !comment.trim()) {
      notice = "Say why in the comment first.";
      return;
    }
    if (kind === "applied" && isDeletion) {
      const extent = current.proposal.original;
      const ok = await askConfirmation({
        title: `Delete “${extent}” from ${current.verseRef}?`,
        body: `Exactly this text is removed from the ${REGION_LABEL[region] ?? region}: “${extent}”. Nothing else changes.`,
        confirmLabel: "Delete it", danger: true,
      });
      if (!ok) return;
    }
    if (kind === "applied" && region === "structure" && preview?.rename) {
      const ok = await askConfirmation({
        title: `Rename \\${preview.rename.fromMarker} to \\${preview.rename.toMarker} at ${current.verseRef}?`,
        body: `In Paratext, the heading “${preview.rename.label}” changes its marker only; its text stays. Bridge's heading follows.`,
        confirmLabel: "Rename it", danger: false,
      });
      if (!ok) return;
    }
    busy = kind;
    notice = "";
    try {
      const result = await bridge.paratextReviewDecide(current.proposalId, kind, {
        comment: comment.trim(), replacement: kind === "applied" ? replacement : null, confirmDelete: isDeletion,
        writeParatext: kind === "applied" && (writeParatext || paratextOnly),
      });
      replaceItem(result.item);
      const refreshNotice = kind === "applied" ? await refreshEditor(expectedPath, result.decision) : "";
      await load(data?.status ?? "");
      const verified = result.decision.decision === "applied" ? (result.decision.verified ? " and verified" : ", NOT verified") : "";
      await next(false);
      notice = `${DECISION_LABEL[result.decision.decision]}${verified}.${paratextOutcome(result.decision)}${refreshNotice}`;
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
    if (index >= 0 && from >= items.length && data?.wraparound?.occurs === false && data.state.scope?.startBook) {
      notice = "End of the scope reached; nothing before the starting book was visited (no wraparound).";
    }
    await show(after.proposalId, saveLeaving, true);
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

  /** #432: put Paratext's active window (its scroll group A-E) on the
   *  proposal's reference. The plugin says so when the window is in no group. */
  async function showInParatext(): Promise<void> {
    if (!current) return;
    try {
      await bridge.paratextSetReference(current.verseRef);
      notice = `Paratext moved to ${current.verseRef} (its active window's scroll group).`;
    } catch (cause) {
      notice = cause instanceof Error ? cause.message : String(cause);
    }
  }

  async function changeFilter(event: Event): Promise<void> {
    const status = (event.target as HTMLSelectElement).value as ParatextReviewFilter;
    await keepDraft();
    await load(status);
  }

  function toggleScopeBook(book: string, on: boolean): void {
    scopeBooks = on ? [...new Set([...scopeBooks, book])] : scopeBooks.filter((b) => b !== book);
  }

  function selectAllBooks(): void {
    scopeBooks = (data?.books ?? []).map((b) => b.book);
  }

  function selectThisBook(): void {
    scopeBooks = data ? [data.book] : [];
  }

  async function applyScope(): Promise<void> {
    await keepDraft();
    scopeOpen = false;
    const books = scopeBooks.length ? scopeBooks : [data?.book ?? ""];
    await load(data?.status ?? "", { books, startBook: books.includes(scopeStart) ? scopeStart : books[0] });
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

  async function retryResolves(): Promise<void> {
    if (busy) return;
    busy = "retry";
    try {
      await bridge.paratextFlushOutbox();
      await loadReports();
      notice = pendingResolves.length ? `Still waiting: ${pendingResolves[0].lastError}` : "Every saved resolve has gone to Paratext.";
    } catch (cause) {
      fail(cause);
    } finally {
      busy = "";
    }
  }

  async function revertLatest(): Promise<void> {
    if (busy) return;
    const expectedPath = $project?.path ?? "";
    const ok = await askConfirmation({
      title: "Revert the latest verified correction?",
      body: "The text is restored to what it was before that correction, only if nobody changed it since, in Bridge and -- when it was written there -- in Paratext. The decision history is kept.",
      confirmLabel: "Revert", danger: true,
    });
    if (!ok) return;
    busy = "revert";
    try {
      const result = await bridge.paratextReviewRevertLatest();
      const refreshNotice = await refreshEditor(expectedPath, result.decision);
      const reverse = result.decision.paratextReverse;
      const paratext = !reverse ? "" : reverse.status === "sent"
        ? (reverse.verified ? " Paratext reversed and read back." : " Paratext reversed but NOT verified there.")
        : reverse.status === "manual" ? ` ${reverse.reason ?? ""}` : ` Paratext reverse ${reverse.status}: ${reverse.lastError ?? ""}`;
      await load(data?.status ?? "");
      await loadReports();
      notice = `Reverted ${result.decision.verseRef}${result.decision.revertVerified ? " and verified" : " (NOT verified)"}.${paratext}${refreshNotice}`;
    } catch (cause) {
      fail(cause);
    } finally {
      busy = "";
    }
  }

  async function reconcile(proposalId: string, outcome: ParatextReconcileOutcome): Promise<void> {
    if (busy) return;
    busy = `reconcile:${proposalId}`;
    try {
      await bridge.paratextReviewReconcile(proposalId, outcome);
      await load(data?.status ?? "");
      await loadReports();
      // After the reload (show() clears the notice), so the outcome stays visible.
      notice = outcome === "verified" ? "Marked verified from the current text."
        : outcome === "notApplied" ? "Marked not applied; the proposal is back in the queue as left for later."
        : outcome === "conflict" ? "Conflict recorded; decide it manually or reject it."
        : "Recorded that you checked the text in Paratext.";
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

  async function saveReport(cumulative = false, chooseDestination = false): Promise<void> {
    if (busy) return;
    try {
      let outputPath = "";
      if (chooseDestination) {
        const path = await bridge.pickSavePath(`report-${data?.book ?? "book"}-${new Date().toISOString().slice(0, 10)}.html`);
        if (!path) return;
        outputPath = path;
      }
      busy = "report";
      report = await bridge.paratextReviewReport({ cumulative, outputPath });
      if (report.written) {
        latestHtml = report.html;
        latestPath = report.path;
        await loadReports();
      }
    } catch (cause) {
      fail(cause);
    } finally {
      busy = "";
    }
  }

  async function newSession(): Promise<void> {
    const ok = await askConfirmation({
      title: "Start a new review session?",
      body: "The session report will cover decisions from now on. Earlier decisions stay in the book and in a cumulative report.",
      confirmLabel: "Start new session", danger: false,
    });
    if (!ok) return;
    try {
      const saved = await bridge.paratextReviewSaveState({ sessionStartedAt: new Date().toISOString() });
      if (data) data = { ...data, state: saved.state };
      report = null;
      notice = "New session started.";
    } catch (cause) {
      fail(cause);
    }
  }

  async function loadReports(): Promise<void> {
    try {
      reports = await bridge.paratextReviewReports();
      if (reports.interrupted.length) {
        notice = `${reports.interrupted.length} interrupted report generation${reports.interrupted.length === 1 ? " was" : "s were"} cleared; save the report again -- the decisions are intact.`;
      }
    } catch (cause) {
      fail(cause);
    }
  }

  async function viewReport(path = ""): Promise<void> {
    try {
      const latest = await bridge.paratextReviewLatestReport(path);
      latestHtml = latest.html;
      latestPath = latest.path;
      if (!latest.path) notice = "No report has been saved for this book yet.";
    } catch (cause) {
      fail(cause);
    }
  }

  async function openInBrowser(path = latestPath): Promise<void> {
    if (!path) return;
    try {
      await bridge.openPath(path);
    } catch (cause) {
      notice = `The report could not be opened in the browser (${cause instanceof Error ? cause.message : String(cause)}); its path is ${path}.`;
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

  async function openTab(which: "review" | "reports"): Promise<void> {
    tab = which;
    if (which === "reports") await loadReports();
  }

  // #428: a keyboard route to every decision and to browsing, beside the
  // buttons (Alt + letter, so typing in the comment box is never captured).
  function onKey(event: KeyboardEvent): void {
    if (event.key === "Escape") { void close(); return; }
    if (!event.altKey || event.ctrlKey || event.metaKey || tab !== "review") return;
    const key = event.key.toLowerCase();
    const actions: Record<string, () => void> = {
      a: () => void decide("applied"), r: () => void decide("rejected"), m: () => void decide("manual"),
      l: () => void decide("deferred"), n: () => void next(), p: () => void previous(),
      g: () => void goToVerse(),
    };
    if (actions[key]) {
      event.preventDefault();
      actions[key]();
    }
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
      <h2>Paratext review queue{data ? ` · ${multiBook ? data.booksInScope.join(", ") : data.book}` : ""}</h2>
      {#if data}
        <button type="button" class="small-btn" on:click={() => (scopeOpen = !scopeOpen)} aria-expanded={scopeOpen}
          title="Choose which books of the project are scanned and where the queue starts">Books…</button>
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
        <button type="button" role="tab" aria-selected={tab === "review"} class:on={tab === "review"} on:click={() => openTab("review")}>Review</button>
        <button type="button" role="tab" aria-selected={tab === "reports"} class:on={tab === "reports"} on:click={() => openTab("reports")}>Reports / recovery{recoveryCount ? ` (${recoveryCount})` : ""}</button>
      </div>
      <button type="button" class="rq-close" on:click={close} aria-label="Close the review queue">Close</button>
    </header>

    {#if error}<p class="rq-msg rq-error" role="alert">{error}</p>{/if}
    {#if notice}<p class="rq-msg" role="status">{notice}</p>{/if}

    {#if data && scopeOpen}
      <section class="rq-scope" aria-label="Books in scope">
        <p class="rq-msg">Scan these books of the project (a book that was never opened is read from the Paratext notes only):</p>
        <div class="rq-scope-books">
          {#each data.books as book (book.book)}
            <label><input type="checkbox" checked={scopeBooks.includes(book.book)}
              on:change={(e) => toggleScopeBook(book.book, e.currentTarget.checked)} />
              {book.book}{book.open ? " (open)" : book.lazy ? " (not opened yet)" : ""}</label>
          {/each}
        </div>
        <div class="rq-actions">
          <button type="button" class="small-btn" on:click={selectAllBooks}>All books</button>
          <button type="button" class="small-btn" on:click={selectThisBook}>This book only</button>
          <label class="rq-filter">Start at
            <select bind:value={scopeStart}>
              {#each scopeBooks as book (book)}<option value={book}>{book}</option>{/each}
            </select>
          </label>
          <button type="button" class="small-btn primary" on:click={applyScope}>Apply scope</button>
          <button type="button" class="small-btn" on:click={() => (scopeOpen = false)}>Cancel</button>
        </div>
        {#if data.scanned?.length}
          <p class="rq-msg">{#each data.scanned as s, i (s.book)}{i ? " · " : ""}{s.book}: {s.proposals} proposal{s.proposals === 1 ? "" : "s"} in {s.threads} thread{s.threads === 1 ? "" : "s"}{s.unreadable ? ` (${s.unreadable} unreadable)` : ""}{/each}</p>
        {/if}
      </section>
    {/if}

    {#if !data}
      <p class="rq-msg">Reading the queue…</p>
    {:else if tab === "review"}
      <div class="rq-body">
        <ol class="rq-list" aria-label="Proposals in Scripture order">
          {#each items as item, i (item.proposalId)}
            {#if data.wraparound?.occurs && i === firstWrapped}
              <li class="rq-wrap" role="note">After {data.booksInScope[data.booksInScope.length - 1]} the queue wraps around to {data.wraparound.books.join(", ")}:</li>
            {/if}
            <li>
              <button type="button" class="rq-row" class:on={item.proposalId === position} class:other={item.openBook === false} on:click={() => show(item.proposalId)}>
                <span class="rq-ref">{item.verseRef}</span>
                <span class="rq-cat">{item.proposal.category}</span>
                {#if item.proposal.region && item.proposal.region !== "body"}<span class="rq-badge region">{REGION_LABEL[item.proposal.region]}</span>{/if}
                {#if item.decision}<span class="rq-badge {item.decision.decision}">{DECISION_LABEL[item.decision.decision]}</span>{/if}
                {#if item.decision?.paratext}<span class="rq-badge pt {item.decision.paratext.status}" title={item.decision.paratext.lastError}>
                  Paratext: {item.decision.paratext.status === "sent" ? (item.decision.paratext.verified ? "written" : "written, unverified") : item.decision.paratext.status}</span>{/if}
                {#if item.proposal.route === "unreadable"}<span class="rq-badge unreadable">unreadable</span>{/if}
                {#if item.openBook === false}<span class="rq-badge other">not open</span>{/if}
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
              {#if onNavigate}<button type="button" class="small-btn" on:click={goToVerse} title="Alt+G">{current.openBook === false ? `Open ${current.book}` : "Go to verse"}</button>{/if}
              <button type="button" class="small-btn" on:click={showInParatext} title="Move Paratext's active window (its scroll group) to this reference">Show in Paratext</button>
              {#if current.decision}<span class="rq-badge {current.decision.decision}">{DECISION_LABEL[current.decision.decision]} · {when(current.decision.decidedAt)}</span>{/if}
            </div>
            {#if current.openBook === false}
              <p class="rq-msg warn">This proposal is in {current.book}, which is not open. Its text and decisions are shown read-only; open the book to decide it. The queue keeps its place.</p>
            {/if}
            <section class="rq-proposal {p.route}" aria-label="Source proposal">
              <div class="rq-tags">
                <span class="rq-route">{ROUTE_LABEL[p.route]}</span>
                {#if p.category}<span class="rq-tag">{p.category}</span>{/if}
                {#if p.pass}<span class="rq-tag">{p.pass}</span>{/if}
                {#if p.region !== "body"}<span class="rq-tag warn">in the {REGION_LABEL[p.region] ?? p.region}</span>{/if}
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

            <section class="rq-target" aria-label="Current text">
              <h3>Current {REGION_LABEL[region] ?? "text"}{preview?.paratextOnly ? " · in Paratext only" : ""}</h3>
              {#if current.openBook === false}
                <p class="rq-msg">Open {current.book} to see its current text.</p>
              {:else if applied}
                <p class="rq-msg">Applied {when(applied.decidedAt)}. This is the saved before and after of that correction, not a new preview.</p>
                <h3>Before</h3>
                <p class="target rq-verse" data-testid="applied-before">
                  {#if applied.span}{applied.before?.plain.slice(0, applied.span.plainStart)}<mark>{applied.before?.plain.slice(applied.span.plainStart, applied.span.plainEnd)}</mark>{applied.before?.plain.slice(applied.span.plainEnd)}{:else}{applied.before?.plain}{/if}
                </p>
                <h3>After · saved and verified</h3>
                <p class="target rq-verse rq-after" data-testid="applied-after">{applied.after?.plain}</p>
              {:else if preview}
                <p class="target rq-verse">
                  {#if preview.span}{preview.plain.slice(0, preview.span.plainStart)}<mark>{preview.plain.slice(preview.span.plainStart, preview.span.plainEnd)}</mark>{preview.plain.slice(preview.span.plainEnd)}{:else}{preview.plain}{/if}
                </p>
                {#if preview.ok}
                  <h3>After</h3>
                  <p class="target rq-verse rq-after">{preview.after}</p>
                {/if}
                {#if preview.reason}<p class="rq-msg warn">{preview.reason}</p>{/if}
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
              {#if region !== "structure"}
                <label class="rq-field">
                  <span>Replacement (exactly what goes in place of the Original)</span>
                  <input type="text" class="target" bind:this={replacementBox} bind:value={replacement} on:change={() => refreshPreview()}
                    disabled={p.operation === "delete" || current.openBook === false} />
                </label>
              {/if}
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

            <label class="rq-check" title="After the correction is applied and verified in Bridge, write the same exact replacement into the linked Paratext project (connector 0.10.0). Paratext's logged-in user is the editor of record; you are named in the evidence.">
              <input type="checkbox" bind:checked={writeParatext} /> Also write to Paratext{paratextOnly ? " (required: Bridge keeps no copy of this region)" : ""}
            </label>
            <div class="rq-actions">
              <button type="button" class="small-btn primary" disabled={!canApply || Boolean(busy)} on:click={() => decide("applied")}
                title={canApply ? "Alt+A · Apply this correction and go to the next proposal" : preview?.reason || "This proposal cannot be applied as it is"}>
                {busy === "applied" ? "Applying…" : region === "structure" ? "Rename marker and next" : isDeletion ? "Delete and next" : "Apply and next"}</button>
              <button type="button" class="small-btn" disabled={Boolean(busy)} on:click={() => decide("rejected")} title="Alt+R">Reject and next</button>
              <button type="button" class="small-btn" disabled={Boolean(busy)} on:click={() => decide("manual")} title="Alt+M">Completed manually / no change</button>
              <button type="button" class="small-btn" disabled={Boolean(busy)} on:click={() => decide("deferred")} title="Alt+L">Leave for later</button>
              <span class="rq-spacer" />
              <button type="button" class="small-btn" disabled={index <= 0} on:click={previous} title="Alt+P">Previous</button>
              <button type="button" class="small-btn" disabled={index >= items.length - 1} on:click={() => next()} title="Alt+N">Next</button>
            </div>
            <p class="rq-msg rq-keys">Keyboard: Alt+A apply · Alt+R reject · Alt+M manual · Alt+L later · Alt+N next · Alt+P previous · Alt+G go to verse · Esc close</p>
            {#if current.thread.complete && !current.threadResolved && current.openBook !== false}
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
          <p class="rq-msg">Decisions since {data.state.sessionStartedAt ? when(data.state.sessionStartedAt) : "this session started"}, with before/after snapshots, who decided, what Paratext did and where each thread was resolved, saved as an offline HTML file in this project's folder.</p>
          <div class="rq-actions">
            <button type="button" class="small-btn primary" disabled={Boolean(busy)} on:click={() => saveReport()}>{busy === "report" ? "Saving…" : "Save session report"}</button>
            <button type="button" class="small-btn" disabled={Boolean(busy)} on:click={() => saveReport(true)} title="Every decision of this book, not only this session's">Save cumulative report</button>
            <button type="button" class="small-btn" disabled={Boolean(busy)} on:click={() => saveReport(false, true)} title="Choose where the report file goes">Save report as…</button>
            <button type="button" class="small-btn" on:click={() => viewReport()}>View latest report</button>
            <button type="button" class="small-btn" disabled={Boolean(busy)} on:click={exportCsv}>Export decisions as CSV…</button>
            <button type="button" class="small-btn" on:click={newSession} title="Later reports cover decisions from now on">Start a new session</button>
          </div>
          {#if report && !report.written}<p class="rq-msg">{report.reason}</p>{/if}
          {#if reports?.reports.length}
            <ul class="rq-saved" aria-label="Saved reports">
              {#each reports.reports as saved (saved.path)}
                <li>{saved.name} · {when(saved.modifiedAt)}
                  <button type="button" class="small-btn" on:click={() => viewReport(saved.path)}>View</button>
                  <button type="button" class="small-btn" on:click={() => openInBrowser(saved.path)}>Open in browser</button></li>
              {/each}
            </ul>
          {/if}
          {#if latestPath}
            <p class="rq-msg">{latestPath}
              <button type="button" class="small-btn" on:click={() => openInBrowser()}>Open in browser</button>
              <button type="button" class="small-btn" on:click={copyPath}>Copy path</button></p>
            <iframe class="rq-report" title="Latest session report" sandbox="allow-same-origin allow-scripts" srcdoc={latestHtml} />
          {/if}
        </section>
        <section>
          <h3>Uncertain edits</h3>
          {#if reports?.uncertain.length}
            <ul>
              {#each reports.uncertain as u (u.decision.proposalId)}
                <li class="target">{u.decision.verseRef}: applied but not verified — {CLASSIFIED_LABEL[u.classified]}.
                  {#if u.paratextPending}<span class="warn">{u.paratextPending}.</span>{/if}
                  <span class="rq-actions">
                    {#if u.classified === "verified" && !u.decision.verified}<button type="button" class="small-btn" disabled={Boolean(busy)} on:click={() => reconcile(u.decision.proposalId, "verified")}>Mark verified</button>{/if}
                    {#if u.classified === "notApplied"}<button type="button" class="small-btn" disabled={Boolean(busy)} on:click={() => reconcile(u.decision.proposalId, "notApplied")}>Mark not applied</button>{/if}
                    {#if u.classified === "conflict" && u.decision.reconciled?.state !== "conflict"}<button type="button" class="small-btn" disabled={Boolean(busy)} on:click={() => reconcile(u.decision.proposalId, "conflict")}>Record conflict</button>{/if}
                    {#if u.paratextPending}<button type="button" class="small-btn" disabled={Boolean(busy)} on:click={() => reconcile(u.decision.proposalId, "paratextChecked")}>Checked in Paratext</button>{/if}
                  </span></li>
              {/each}
            </ul>
          {:else if uncertain.length}
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
            <p class="rq-msg">None waiting.</p>
          {/if}
          <h3>Saved resolves not yet in Paratext</h3>
          {#if pendingResolves.length}
            <ul>
              {#each pendingResolves as pending (pending.messageId)}
                <li>{pending.reference || pending.threadId} · {pending.status} · {pending.lastError}</li>
              {/each}
            </ul>
            <div class="rq-actions">
              <button type="button" class="small-btn" disabled={Boolean(busy)} on:click={retryResolves}>Retry sending</button>
              <span class="rq-msg">A retry sends the resolve only; it never reapplies a correction.</span>
            </div>
          {:else}
            <p class="rq-msg">None waiting. A resolve retry never reapplies a correction.</p>
          {/if}
        </section>
      </div>
    {/if}
  </div>
</div>

<style>
  /* #444: an app dialog on --z-dialog, so the confirmation it asks (Revert, Delete, Rename, New session;
     --z-dialog-over-dialog) renders above it. A literal 60 tied that layer and the queue, mounted later, won. */
  .rq-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.35); z-index: var(--z-dialog); display: flex; align-items: center; justify-content: center; padding: 12px; }
  /* Fits a 1366x768 desktop: at most the window less the padding, never taller. */
  .rq-dialog { width: min(1180px, 100%); height: min(740px, 100%); display: flex; flex-direction: column; background: var(--surface); color: var(--text);
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
  .rq-scope { border-bottom: 1px solid var(--border); padding: 4px 0 8px; display: grid; gap: 4px; }
  .rq-scope-books { display: flex; flex-wrap: wrap; gap: 4px 12px; margin: 0 12px; font-size: var(--fs-2xs); }
  .rq-scope .rq-actions { margin: 0 12px; }
  .rq-body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(200px, 280px) minmax(0, 1fr); }
  .rq-list { list-style: none; margin: 0; padding: 6px; overflow-y: auto; border-right: 1px solid var(--border); }
  .rq-wrap { margin: 6px 4px 2px; color: var(--warning); font-size: var(--fs-2xs); font-weight: 650; }
  .rq-row { width: 100%; text-align: left; display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: center; border: 1px solid transparent; background: none;
    color: var(--text); font: inherit; border-radius: 6px; padding: 5px 7px; cursor: pointer; }
  .rq-row.on { border-color: var(--accent); background: var(--accent-bg); }
  .rq-row.other { opacity: .75; }
  .rq-ref { font-weight: 700; }
  .rq-cat { color: var(--text-2); font-size: var(--fs-2xs); }
  .rq-badge { border-radius: 999px; padding: 0 7px; font-size: var(--fs-2xs); font-weight: 700; background: var(--accent-bg); color: var(--accent); }
  .rq-badge.applied { background: var(--success-bg); color: var(--success); }
  .rq-badge.rejected, .rq-badge.unreadable { background: var(--danger-bg, #fee); color: var(--danger); }
  .rq-badge.region, .rq-badge.other { background: transparent; border: 1px solid var(--border-strong); color: var(--text-2); }
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
  .rq-check { display: inline-flex; align-items: center; gap: 6px; font-size: var(--fs-2xs); color: var(--text-2); }
  .rq-keys { margin: 0; }
  .rq-badge.pt { background: transparent; border: 1px solid var(--accent); }
  .rq-badge.pt.refused, .rq-badge.pt.not_sent { border-color: var(--danger); color: var(--danger); }
  .rq-spacer { flex: 1; }
  .small-btn { border-radius: 5px; cursor: pointer; font-size: var(--fs-2xs); padding: 5px 8px; color: var(--text-2);
    background: var(--surface); border: 1px solid var(--border-strong); }
  .small-btn.primary { color: var(--accent); border-color: var(--accent); font-weight: 650; }
  .small-btn:disabled { opacity: .55; cursor: not-allowed; }
  .rq-reports { flex: 1; min-height: 0; overflow-y: auto; padding: 10px 12px; display: grid; gap: 12px; align-content: start; }
  .rq-reports ul { margin: 4px 0; padding-left: 18px; }
  .rq-saved li { margin: 2px 0; }
  .rq-report { width: 100%; height: 320px; border: 1px solid var(--border); border-radius: 6px; background: #fff; }
</style>
