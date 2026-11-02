<script lang="ts">
  import PanelHeader from "./PanelHeader.svelte";
  // #357: the Paratext team's Project Notes on the selected verse. Threads
  // come from every Notes_<User>.xml of the linked Paratext folder, merged by
  // thread; comments are shown in date order.
  //
  // #426: the panel also writes, through the engine's outbox to the book's
  // linked Paratext project (connector 0.8.0): a new note on the verse (on its
  // selected text when one is given), a reply, a resolve. A write that cannot
  // go now stays queued with its reason and is shown under "Pending"; a note
  // sent but not yet read back from Paratext's file is pending too, never
  // shown as a thread before the file holds it. Drafts survive moving between
  // verses in this session.
  //
  // #427: the QA proposals a thread carries (Original / Suggested / Reason,
  // parsed by the engine) are shown read-only with what the parser could say
  // about them. Nothing here applies a proposal to Scripture.
  import { onDestroy, tick } from "svelte";
  import ParatextReviewQueue from "./ParatextReviewQueue.svelte";
  import { bridge } from "../api/bridgeClient";
  import { currentChapter, project, selectedVerse, verseKey } from "../stores";
  import {
    draftKey, dropDraft, loadParatextNoteCounts, paratextNoteRequest, readDraft, saveDraft,
  } from "../paratextNotes";
  import type {
    ParatextLinkState, ParatextNoteThread, ParatextNotesIndexState, ParatextOutboxItem, ParatextProposal,
  } from "../types/paratext";

  /** App's navigateToReportRow, for the review queue's "Go to verse" (#432). */
  export let onNavigate: ((book: string, chapter: string, verse: string) => Promise<void>) | null = null;

  const POLL_MS = 1500;
  const PENDING_POLL_MS = 4000;
  const PENDING_POLLS = 15;

  // #432: the review queue over this book's QA proposals, a modal dialog.
  let queueOpen = false;
  function closeQueue(): void {
    queueOpen = false;
    void load($currentChapter, $selectedVerse);
    void loadParatextNoteCounts($currentChapter);
  }

  let threads: ParatextNoteThread[] = [];
  let pending: ParatextOutboxItem[] = [];
  let state: ParatextNotesIndexState | "" = "";
  let linkState: ParatextLinkState | "" = "";
  let error = "";
  let refreshing = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let request = 0;
  let pendingPolls = 0;

  // The composer (#426).
  let composing = false;
  let noteText = "";
  let noteSelection = "";
  let sending = "";
  let notice = "";
  let replyFor = "";
  let replyText = "";
  let composerBox: HTMLTextAreaElement | null = null;
  let draftFor = "";

  const FOOTER = /\n*\[Bridge ref [^\]]+\]\s*$/;
  /** The footer is for Bridge's duplicate check, not for the reviewer. */
  const shown = (contents: string): string => contents.replace(FOOTER, "");

  function stopPolling(): void {
    if (timer) clearTimeout(timer);
    timer = null;
  }
  onDestroy(stopPolling);

  async function load(chapter: string, verse: string | null, keepPolling = false): Promise<void> {
    stopPolling();
    const mine = ++request;
    error = "";
    if (!keepPolling) pendingPolls = 0;
    if (!verse) {
      threads = [];
      pending = [];
      state = "";
      return;
    }
    try {
      const result = await bridge.paratextNotesForVerse(chapter, verse);
      if (mine !== request) return;
      threads = result.threads;
      pending = result.pending ?? [];
      state = result.state;
      if (state === "unavailable" && !linkState) linkState = (await bridge.paratextLinkStatus()).state;
      if (state === "building" || state === "stale") {
        timer = setTimeout(() => void load(chapter, verse, true), POLL_MS);
      } else if (pending.length && pendingPolls < PENDING_POLLS) {
        // A sent note shows as a thread once Bridge has read the file again,
        // and a queued one goes when Paratext answers: look again for a while.
        pendingPolls += 1;
        timer = setTimeout(() => void load(chapter, verse, true), PENDING_POLL_MS);
      }
    } catch (value) {
      if (mine !== request) return;
      error = value instanceof Error ? value.message : String(value);
    }
  }

  async function refresh(): Promise<void> {
    refreshing = true;
    try {
      const status = await bridge.paratextRefresh();
      linkState = status.state;
      await load($currentChapter, $selectedVerse);
      void loadParatextNoteCounts($currentChapter);
    } catch (value) {
      error = value instanceof Error ? value.message : String(value);
    } finally {
      refreshing = false;
    }
  }

  function when(value: string): string {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  }

  const KIND_LABEL: Record<string, string> = { conflict: "Conflict", biblicalTerm: "Biblical term" };

  // #427: what the parser could say about a proposal, in the reviewer's words.
  const ROUTE_LABEL: Record<ParatextProposal["route"], string> = {
    literal: "Literal correction · review before use",
    review: "Needs a reviewer's decision",
    structure: "USFM structure · review only",
    noChange: "No change proposed",
    legacy: "Older note label",
    unreadable: "Could not be read",
  };
  const OPERATION_LABEL: Partial<Record<ParatextProposal["operation"], string>> = {
    insert: "insertion", delete: "deletion", alternatives: "alternatives", instruction: "instruction to the reviewer",
    markerRename: "marker rename", structural: "structural change",
  };
  const REGION_LABEL: Partial<Record<ParatextProposal["region"], string>> = {
    introduction: "introduction", heading: "heading", footnote: "footnote", crossReference: "cross-reference",
    structure: "USFM structure",
  };

  // -- the composer -----------------------------------------------------------

  /** Keep the draft of the verse being left, take the one of the verse arrived at. */
  function switchDraft(key: string): void {
    if (draftFor && draftFor !== key) saveDraft(draftFor, { text: noteText, selectedText: noteSelection });
    draftFor = key;
    const draft = key ? readDraft(key) : null;
    noteText = draft?.text ?? "";
    noteSelection = draft?.selectedText ?? "";
    composing = Boolean(draft);
    notice = "";
    replyFor = "";
    replyText = "";
  }

  async function openComposer(selectedText = ""): Promise<void> {
    composing = true;
    if (selectedText) noteSelection = selectedText;
    notice = "";
    await tick();
    composerBox?.focus();
  }

  function closeComposer(): void {
    composing = false;
    noteText = "";
    noteSelection = "";
    if (draftFor) dropDraft(draftFor);
  }

  function outcome(item: ParatextOutboxItem | null, sent: string): string {
    if (!item) return "";
    if (item.status === "sent") return sent;
    if (item.status === "refused") return `Paratext refused it: ${item.lastError}`;
    return `Queued for Paratext. ${item.lastError || "It goes when Paratext is available."}`;
  }

  async function sendNote(): Promise<void> {
    if (sending || !noteText.trim() || !$selectedVerse) return;
    sending = "note";
    notice = "";
    try {
      const result = await bridge.paratextCreateNote($currentChapter, $selectedVerse, noteText.trim(), noteSelection.trim());
      notice = outcome(result.item, "Note sent to Paratext. It shows here once Bridge has read Paratext's notes file again.");
      closeComposer();
      await load($currentChapter, $selectedVerse);
    } catch (cause) {
      notice = cause instanceof Error ? cause.message : String(cause);
    } finally {
      sending = "";
    }
  }

  async function sendReply(threadId: string): Promise<void> {
    if (sending || !replyText.trim()) return;
    sending = `reply:${threadId}`;
    notice = "";
    try {
      const result = await bridge.paratextReplyThread(threadId, replyText.trim(), "note", threadId);
      notice = outcome(result.item, "Reply sent to Paratext.");
      replyFor = "";
      replyText = "";
      await load($currentChapter, $selectedVerse);
    } catch (cause) {
      notice = cause instanceof Error ? cause.message : String(cause);
    } finally {
      sending = "";
    }
  }

  async function resolveThread(threadId: string): Promise<void> {
    if (sending) return;
    sending = `resolve:${threadId}`;
    notice = "";
    try {
      const result = await bridge.paratextResolveThread(threadId, "note", threadId);
      notice = outcome(result.item, "Resolved in Paratext. The thread shows as resolved once Bridge has read the file again.");
      await load($currentChapter, $selectedVerse);
    } catch (cause) {
      notice = cause instanceof Error ? cause.message : String(cause);
    } finally {
      sending = "";
    }
  }

  function pendingLabel(item: ParatextOutboxItem): string {
    const what = item.op === "resolve" ? "Resolve" : item.op === "add_comment" ? "Reply" : "Note";
    if (item.status === "sent") return `${what} sent. It shows here once Bridge has read Paratext's notes file again.`;
    if (item.status === "refused") return `${what} refused by Paratext: ${item.lastError}`;
    return `${what} queued for Paratext. ${item.lastError || "It goes when Paratext is available."}`;
  }

  $: { void $project; linkState = ""; }
  $: void load($currentChapter, $selectedVerse);
  // The stores are named here, not only inside currentDraftKey(): Svelte
  // tracks what the statement itself reads.
  $: switchDraft($project && $selectedVerse ? draftKey($project.path, $currentChapter, $selectedVerse) : "");
  $: if ($paratextNoteRequest && $paratextNoteRequest.chapter === $currentChapter
         && $paratextNoteRequest.verse === $selectedVerse) {
    const asked = $paratextNoteRequest;
    paratextNoteRequest.set(null);
    void openComposer(asked.selectedText);
  }

  const canWrite = (s: ParatextNotesIndexState | ""): boolean => s === "ready" || s === "stale" || s === "building";
</script>

<div class="pt-notes" data-testid="paratext-notes-panel">
  <!-- #379: the shared header bar (this panel had none); the body below it is
       the panel's own scroll box. -->
  <PanelHeader id="paratext" label="the Paratext notes panel"
    title={$selectedVerse ? `Paratext notes · ${$currentChapter}:${$selectedVerse}` : "Paratext notes"}>
    {#if state && state !== "unavailable"}
      <button type="button" class="refresh" on:click={() => (queueOpen = true)}
        title="Review this book's QA proposals from Paratext notes in Scripture order">Review queue…</button>
      <button type="button" class="refresh" on:click={refresh} disabled={refreshing} title="Read the Paratext notes files again">Refresh</button>
    {/if}
  </PanelHeader>
  {#if queueOpen}
    <ParatextReviewQueue onClose={closeQueue} {onNavigate} />
  {/if}
  <div class="pt-scroll">
  {#if error}
    <p class="pt-msg pt-error" role="alert">{error}</p>
  {:else if !$selectedVerse}
    <p class="pt-msg">Select a verse to see its Paratext notes.</p>
  {:else if state === "unavailable"}
    <p class="pt-msg">
      {#if linkState === "notParatext" || linkState === ""}
        This book was not imported from a Paratext project, so there are no Paratext notes to show.
      {:else}
        The Paratext project folder is not available ({linkState === "folderMoved" ? "it was moved" : linkState === "guidMismatch" ? "it holds a different project" : "not found"}). Relink it on Project Home.
      {/if}
    </p>
  {:else if state === "building" && !threads.length && !composing}
    <p class="pt-msg" role="status">Reading the Paratext notes…</p>
  {:else if state === "error"}
    <p class="pt-msg pt-error">The Paratext notes could not be read. Try Refresh.</p>
  {:else}
    {#if state === "stale"}<p class="pt-msg" role="status">Updating from Paratext…</p>{/if}
    {#if canWrite(state)}
      {#if composing}
        <form class="pt-compose" on:submit|preventDefault={sendNote} aria-label="New Paratext note">
          <label class="pt-field">
            <span>Note for Paratext · {$currentChapter}:{$selectedVerse}</span>
            <textarea bind:this={composerBox} bind:value={noteText} rows="3"
              placeholder="Your note, as the Paratext user on this PC" disabled={Boolean(sending)} />
          </label>
          <label class="pt-field">
            <span>Attach to text (optional, must occur once in the verse)</span>
            <input type="text" bind:value={noteSelection} disabled={Boolean(sending)} class="target" />
          </label>
          <div class="pt-actions">
            <button type="submit" class="small-btn primary" disabled={Boolean(sending) || !noteText.trim()}>
              {sending === "note" ? "Sending…" : "Send to Paratext"}</button>
            <button type="button" class="small-btn" on:click={closeComposer} disabled={Boolean(sending)}>Discard</button>
          </div>
        </form>
      {:else}
        <div class="pt-actions">
          <button type="button" class="small-btn" on:click={() => openComposer()}
            title="Write a Project Note on this verse in the linked Paratext project">New note…</button>
        </div>
      {/if}
    {/if}
    {#if notice}<p class="pt-msg" role="status">{notice}</p>{/if}
    {#each pending as item (item.messageId)}
      <p class="pt-msg pt-pending" role="status" data-message-id={item.messageId}>
        {pendingLabel(item)}
        {#if item.op === "create_thread" && item.text}<span class="pt-pending-text">{shown(item.text)}</span>{/if}
      </p>
    {/each}
    {#if !threads.length && !pending.length}
      <p class="pt-msg">No Paratext notes on this verse.</p>
    {/if}
    {#each threads as thread (thread.id)}
      <article class="pt-thread" class:resolved={thread.resolved} data-thread-id={thread.id}>
        <header>
          {#if KIND_LABEL[thread.kind]}<span class="pt-kind">{KIND_LABEL[thread.kind]}</span>{/if}
          <span class="pt-status">{thread.resolved ? "Resolved" : "Open"}</span>
          {#if thread.verse && thread.verseRef}<span class="pt-ref">{thread.verseRef}</span>{/if}
          {#if thread.assignedUser}<span class="pt-assigned">Assigned to {thread.assignedUser}</span>{/if}
          {#each thread.tags as tag (tag.id)}<span class="pt-tag">{tag.name || `tag ${tag.id}`}</span>{/each}
          {#if thread.proposals?.outstanding}<span class="pt-tag pt-qa">{thread.proposals.outstanding} QA proposal{thread.proposals.outstanding === 1 ? "" : "s"}</span>{/if}
        </header>
        {#if thread.selectedText}<blockquote class="pt-quote">{thread.selectedText}</blockquote>{/if}
        {#each thread.proposalItems ?? [] as proposal (proposal.proposalId)}
          <section class="pt-proposal {proposal.route}" aria-label="QA proposal" data-proposal-id={proposal.proposalId}>
            <div class="pt-proposal-head">
              <span class="pt-route">{ROUTE_LABEL[proposal.route]}</span>
              {#if proposal.category}<span class="pt-cat">{proposal.category}</span>{/if}
              {#if proposal.pass}<span class="pt-pass">{proposal.pass}</span>{/if}
              {#if OPERATION_LABEL[proposal.operation]}<span class="pt-op">{OPERATION_LABEL[proposal.operation]}</span>{/if}
              {#if REGION_LABEL[proposal.region]}<span class="pt-op">in the {REGION_LABEL[proposal.region]}</span>{/if}
              {#if proposal.historical}<span class="pt-op">already made</span>{/if}
            </div>
            {#if proposal.original || proposal.suggested}
              <dl class="pt-diff">
                {#if proposal.original}<dt>Original</dt><dd class="target">{proposal.original}</dd>{/if}
                {#if proposal.alternatives.length}
                  <dt>Suggested</dt>
                  <dd><ul class="pt-alts">{#each proposal.alternatives as alt, i (i)}<li class="target">{alt}</li>{/each}</ul></dd>
                {:else if proposal.suggested}
                  <dt>Suggested</dt><dd class="target">{proposal.suggested}</dd>
                {/if}
                {#if proposal.reason}<dt>Reason</dt><dd>{proposal.reason}</dd>{/if}
                {#if proposal.location}<dt>Location</dt><dd>{proposal.location}</dd>{/if}
              </dl>
            {/if}
            {#if proposal.reviewerDecision && proposal.route !== "noChange" && proposal.route !== "legacy"}
              <p class="pt-msg">Reviewer decision needed{proposal.confidence ? ` · confidence ${proposal.confidence}` : ""}</p>
            {:else if proposal.confidence}
              <p class="pt-msg">Confidence {proposal.confidence}</p>
            {/if}
            {#if proposal.anchorWarning}<p class="pt-msg pt-warn">The pass could not find the Original verbatim; check the target text.</p>{/if}
            {#each proposal.diagnostics as line, i (i)}<p class="pt-msg pt-warn">{line}</p>{/each}
          </section>
        {/each}
        <ol class="pt-comments">
          {#each thread.comments as comment, i (i)}
            <li>
              <div class="pt-meta"><strong>{comment.user}</strong> · {when(comment.date)}{comment.status === "done" || comment.status === "deleted" ? " · resolved" : ""}</div>
              {#if comment.contents}<div class="pt-body">{shown(comment.contents)}</div>{/if}
            </li>
          {/each}
        </ol>
        {#if canWrite(state)}
          {#if replyFor === thread.id}
            <form class="pt-compose" on:submit|preventDefault={() => sendReply(thread.id)} aria-label="Reply in Paratext">
              <label class="pt-field">
                <span>Reply in Paratext</span>
                <textarea bind:value={replyText} rows="2" placeholder="Your reply, as the Paratext user on this PC" disabled={Boolean(sending)} />
              </label>
              <div class="pt-actions">
                <button type="submit" class="small-btn primary" disabled={Boolean(sending) || !replyText.trim()}>
                  {sending === `reply:${thread.id}` ? "Sending…" : "Send reply"}</button>
                <button type="button" class="small-btn" on:click={() => { replyFor = ""; replyText = ""; }} disabled={Boolean(sending)}>Cancel</button>
              </div>
            </form>
          {:else}
            <div class="pt-actions">
              <button type="button" class="small-btn" on:click={() => { replyFor = thread.id; replyText = ""; }} disabled={Boolean(sending)}>Reply</button>
              {#if !thread.resolved}
                <button type="button" class="small-btn" on:click={() => resolveThread(thread.id)} disabled={Boolean(sending)}
                  title="Mark the thread resolved in Paratext (the Paratext user on this PC)">
                  {sending === `resolve:${thread.id}` ? "Resolving…" : "Resolve in Paratext"}</button>
              {/if}
            </div>
          {/if}
        {/if}
      </article>
    {/each}
  {/if}
  </div>
</div>

<style>
  /* #379 item 6: the body is --surface at --fs-xs, padded 10px 12px. */
  .pt-notes { flex: 1; min-height: 0; display: flex; flex-direction: column; background: var(--surface); font-size: var(--fs-xs); color: var(--text); }
  .pt-scroll { flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; padding: 10px 12px; }
  .refresh { border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface); color: var(--text);
    padding: 2px 8px; font: inherit; font-size: var(--fs-2xs); cursor: pointer; }
  .pt-msg { margin: 0; color: var(--text-2); font-size: var(--fs-2xs); line-height: 1.45; }
  .pt-error { color: var(--danger); }
  .pt-warn { color: var(--warning); }
  .pt-pending { border-left: 3px solid var(--accent); padding-left: 8px; }
  .pt-pending-text { display: block; white-space: pre-wrap; overflow-wrap: anywhere; font-family: var(--font-target, inherit); color: var(--text); margin-top: 2px; }
  .pt-thread { border: 1px solid var(--border); border-radius: 7px; padding: 7px 9px; background: var(--surface); }
  .pt-thread.resolved { opacity: .7; }
  .pt-thread header { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: center; font-size: var(--fs-2xs); color: var(--text-2); }
  .pt-kind { font-weight: 700; color: var(--warning); }
  .pt-status { font-weight: 700; }
  .pt-tag { border-radius: 999px; padding: 0 6px; background: var(--accent-bg); color: var(--accent); }
  .pt-tag.pt-qa { font-weight: 700; }
  .pt-quote { margin: 6px 0; padding: 2px 8px; border-left: 3px solid var(--border-strong); color: var(--text-2); }
  .pt-comments { list-style: none; margin: 4px 0 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
  .pt-meta { font-size: var(--fs-2xs); color: var(--text-2); }
  .pt-body { white-space: pre-wrap; overflow-wrap: anywhere; font-family: var(--font-target, inherit); }
  /* #427: a proposal block, read-only. */
  .pt-proposal { margin: 6px 0; padding: 6px 8px; border: 1px dashed var(--border-strong); border-radius: 6px; display: grid; gap: 4px; }
  .pt-proposal.literal { border-color: var(--success); }
  .pt-proposal.unreadable { border-color: var(--danger); }
  .pt-proposal-head { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: center; font-size: var(--fs-2xs); color: var(--text-2); }
  .pt-route { font-weight: 700; color: var(--text); }
  .pt-cat, .pt-pass { border-radius: 999px; padding: 0 6px; background: var(--accent-bg); color: var(--accent); }
  .pt-diff { margin: 0; display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 2px 8px; font-size: var(--fs-2xs); }
  .pt-diff dt { color: var(--text-2); font-weight: 650; }
  .pt-diff dd { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; min-width: 0; }
  .pt-alts { margin: 0; padding-left: 16px; }
  .target { font-family: var(--font-target, inherit); }
  /* #426: the composer and the reply box. */
  .pt-compose { display: grid; gap: 6px; padding: 7px 9px; border: 1px solid var(--border); border-radius: 7px; background: var(--surface); }
  .pt-field { display: grid; gap: 3px; font-size: var(--fs-2xs); font-weight: 650; color: var(--text-2); }
  .pt-field textarea, .pt-field input { width: 100%; box-sizing: border-box; border: 1px solid var(--border); border-radius: 5px; padding: 6px 7px;
    font: inherit; font-weight: 400; color: var(--text); background: var(--surface); resize: vertical; }
  .pt-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
  .small-btn { border-radius: 5px; cursor: pointer; font-size: var(--fs-2xs); padding: 5px 8px; color: var(--text-2);
    background: var(--surface); border: 1px solid var(--border-strong); }
  .small-btn.primary { color: var(--accent); border-color: var(--accent); font-weight: 650; }
  .small-btn:disabled { opacity: .55; cursor: not-allowed; }
</style>
