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
  import { bridge as unboundBridge } from "../api/bridgeClient";
  import { bindReviewProject } from "../reviewProjectGuard";
  import { askConfirmation } from "../confirmAction";
  import { project, targetDir, targetLang } from "../stores";
  import { refreshParatextReviewEditor } from "../paratextReviewRefresh";
  import type {
    ParatextNoteThread,
    ParatextReviewFilter, ParatextReviewItem, ParatextReviewPreview, ParatextReviewQueue, ParatextReviewReport,
    ParatextReviewReports, ParatextReviewScope, ParatextReconcileOutcome, ParatextReviewDecision,
  } from "../types/paratext";

  export let onClose: () => void;
  export let standalone = false;
  export let revision = 0;
  export let onDetach: (() => Promise<void>) | null = null;
  export let onRefresh = refreshParatextReviewEditor;
  /** App's navigateToReportRow: opens the book if needed and selects the verse. */
  export let onNavigate: ((book: string, chapter: string, verse: string) => Promise<void>) | null = null;
  const queuePath = $project?.path ?? "";
  const bridge = bindReviewProject(unboundBridge, queuePath);
  let alive = true;
  const active = () => alive && ($project?.path ?? "") === queuePath;
  let loadRequest = 0;
  let loading = false;
  let discussion: ParatextNoteThread | null = null;
  let threadRequest = 0;
  const viewKey = `bridge.reviewQueue.view:${queuePath}`;
  const draftKey = `bridge.reviewQueue.draft:${queuePath}`;

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
  let previewTimer: ReturnType<typeof setTimeout> | undefined;
  let report: ParatextReviewReport | null = null;
  let reports: ParatextReviewReports | null = null;
  let latestHtml = "";
  let latestPath = "";
  let replacementBox: HTMLTextAreaElement | null = null;
  let scopeOpen = false;
  let scopeBooks: string[] = [];
  let scopeStart = "";
  let loadedFor = "";
  // DECISIONS 2026-11-02 (Benz): after a verified Bridge apply the same exact
  // replacement may also be written into the linked Paratext project. Off by
  // default; required for a region Bridge keeps no copy of.
  let writeParatext = false;
  try {
    const view = JSON.parse(localStorage.getItem(viewKey) ?? "null");
    if (view?.tab === "reports") tab = "reports";
    writeParatext = view?.writeParatext === true;
  } catch { /* unreadable preferences */ }
  $: if (revision && current && !busy) void refreshPreview(current);

  function rememberView(): void {
    try { localStorage.setItem(viewKey, JSON.stringify({ tab, writeParatext })); } catch { /* session only */ }
  }
  function rememberDraft(): void {
    if (!current) return;
    try {
      localStorage.setItem(draftKey, JSON.stringify({ id: current.proposalId,
        original: current.proposal.original, suggested: current.proposal.suggested, replacement, comment }));
    } catch { /* engine save still available */ }
  }
  function forgetDraft(): void { try { localStorage.removeItem(draftKey); } catch { /* unavailable */ } }

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
  // The host keys instances by project path. Old async continuations keep
  // their original engine precondition and cannot populate the new instance.

  function fail(cause: unknown): void {
    error = cause instanceof Error ? cause.message : String(cause);
  }

  async function refreshEditor(path: string, decision: ParatextReviewDecision): Promise<string> {
    try {
      await onRefresh(path, decision);
      return "";
    } catch {
      // The write already finished: a read failure must not invite Apply again.
      return " The decision was saved, but the editor could not refresh. Reopen the book to reload its saved text.";
    }
  }

  async function load(status: ParatextReviewFilter | "" = "", scope: ParatextReviewScope | null = null): Promise<void> {
    const mine = ++loadRequest;
    loading = true;
    try {
      loadedFor = $project?.path ?? "";
      const result = await bridge.paratextReviewQueue(status, scope);
      if (!active() || mine !== loadRequest) return;
      data = result;
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
      if (active() && mine === loadRequest) fail(cause);
    } finally { if (mine === loadRequest) loading = false; }
  }

  /** Keep the draft of the item being left, take the next item's. */
  async function show(proposalId: string, saveLeaving = true, keepNotice = false): Promise<void> {
    if (!active()) return;
    if (saveLeaving && current && !(await keepDraft())) return;
    position = proposalId;
    discussion = null;
    const threadMine = ++threadRequest;
    // Read from `data` itself: `items` is derived and lags one tick when
    // show() runs right after load() replaced data.
    const item = (data?.items ?? []).find((entry) => entry.proposalId === proposalId) ?? null;
    if (item && item.openBook !== false && typeof unboundBridge.paratextNoteThread === "function") {
      void bridge.paratextNoteThread(item.threadId).then((result) => {
        if (active() && threadMine === threadRequest) discussion = result.thread;
      }).catch(() => { /* the parsed proposal remains available */ });
    }
    replacement = item?.draft?.replacement ?? item?.decision?.replacement ?? item?.proposal.suggested ?? "";
    if (item && item.proposal.operation === "alternatives" && !item.draft && !item.decision) replacement = "";
    if (item && item.proposal.operation === "delete") replacement = "";
    comment = item?.draft?.comment ?? item?.decision?.comment ?? "";
    try {
      const local = JSON.parse(localStorage.getItem(draftKey) ?? "null");
      if (item && item.decision?.decision !== "applied" && local?.id === item.proposalId
          && local.original === item.proposal.original && local.suggested === item.proposal.suggested) {
        replacement = local.replacement;
        comment = local.comment;
      }
    } catch { /* use the engine's draft */ }
    if (!keepNotice) notice = "";
    // `current` is derived from `position` and only recomputes after this
    // tick, so the item is passed, not read back.
    await refreshPreview(item);
    if (item) void bridge.paratextReviewSaveState({ position: proposalId }).catch(() => undefined);
  }

  async function refreshPreview(item: ParatextReviewItem | null = current): Promise<void> {
    clearTimeout(previewTimer);
    preview = null;
    if (!item || item.openBook === false || appliedSnapshot(item)) return;
