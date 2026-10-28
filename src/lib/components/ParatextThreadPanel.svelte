<script lang="ts">
  // #358 (e): the Paratext threads linked to one Bridge record (an issue
  // resolution today), what Paratext says on them, and the three write-backs:
  // Reply, Resolve in Paratext, Link existing thread. Every write goes through
  // the engine's outbox to the book's linked Paratext project (connector
  // 0.8.0); a write that cannot go now stays queued with its reason.
  // Paratext's own state -- a reply, a `done` -- is shown and never applied to
  // the Bridge record (decision 3 on #358); when the owner passes
  // `onResolveHere`, a thread resolved in Paratext offers it as one click.
  import { onDestroy } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import type { ParatextNoteSummary, ParatextThreadsFor, ParatextWriteKind } from "../types/paratext";

  export let kind: ParatextWriteKind;
  export let localId: string;
  export let chapter: string;
  export let verse: string;
  /** Bump to read the threads again (after a send or a retry elsewhere). */
  export let refreshKey = 0;
  /** The Bridge record is already resolved: no one-click offer. */
  export let bridgeResolved = false;
  /** Decision 3's one click; the owner writes its own record. */
  export let onResolveHere: ((threadId: string) => Promise<void>) | null = null;

  let data: ParatextThreadsFor | null = null;
  let error = "";
  let busy = "";
  let notice = "";
  let replyFor = "";
  let replyText = "";
  let candidates: ParatextNoteSummary[] | null = null;
  let request = 0;

  const FOOTER = /\n*\[Bridge ref [^\]]+\]\s*$/;
  /** The footer is for Bridge's duplicate check, not for the reviewer. */
  const shown = (contents: string): string => contents.replace(FOOTER, "");

  function when(value: string): string {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  }

  async function load(): Promise<void> {
    const mine = ++request;
    try {
      const result = await bridge.paratextThreadsFor(kind, localId);
      if (mine !== request) return;
      data = result;
      error = "";
    } catch (cause) {
      if (mine !== request) return;
      data = null;
      error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  $: void (refreshKey, kind, localId, load());
  onDestroy(() => { request += 1; });

  function outcome(item: { status: string; lastError?: string } | null | undefined, sent: string): string {
    if (!item) return "";
    return item.status === "sent" ? sent : `Queued for Paratext. ${item.lastError || "It goes when Paratext is available."}`;
  }

  async function sendReply(threadId: string): Promise<void> {
    if (busy || !replyText.trim()) return;
    busy = `reply:${threadId}`;
    notice = "";
    try {
      const result = await bridge.paratextReplyThread(threadId, replyText.trim(), kind, localId);
      notice = outcome(result.item, "Reply sent to Paratext.");
      replyFor = "";
      replyText = "";
      await load();
    } catch (cause) {
      notice = cause instanceof Error ? cause.message : String(cause);
    } finally {
      busy = "";
    }
  }

  async function resolveThread(threadId: string): Promise<void> {
    if (busy) return;
    busy = `resolve:${threadId}`;
    notice = "";
    try {
      const result = await bridge.paratextResolveThread(threadId, kind, localId);
      notice = outcome(result.item, "Resolved in Paratext.");
      await load();
    } catch (cause) {
      notice = cause instanceof Error ? cause.message : String(cause);
    } finally {
      busy = "";
    }
  }

  async function resolveHere(threadId: string): Promise<void> {
    if (busy || !onResolveHere) return;
    busy = `here:${threadId}`;
    notice = "";
    try {
      await onResolveHere(threadId);
    } catch (cause) {
      notice = cause instanceof Error ? cause.message : String(cause);
    } finally {
      busy = "";
    }
  }

  async function showCandidates(): Promise<void> {
    notice = "";
    try {
      const result = await bridge.paratextNotesForVerse(chapter, verse);
      const linked = new Set((data?.links ?? []).map((link) => link.threadId));
      candidates = result.threads.filter((thread) => !linked.has(thread.id));
    } catch (cause) {
      notice = cause instanceof Error ? cause.message : String(cause);
    }
  }

  async function linkThread(threadId: string): Promise<void> {
    if (busy) return;
    busy = `link:${threadId}`;
    try {
      await bridge.paratextLinkThread(threadId, kind, localId);
      candidates = null;
      notice = "Linked to the Paratext thread.";
      await load();
    } catch (cause) {
      notice = cause instanceof Error ? cause.message : String(cause);
    } finally {
      busy = "";
    }
  }
</script>

<section class="pt-threads" aria-label="Paratext threads">
  {#if error}
    <p class="pt-msg">{error}</p>
  {:else if data}
    {#each data.links as link (link.threadId)}
      {@const thread = link.thread}
      <article class="pt-thread" class:resolved={thread?.resolved} data-thread-id={link.threadId}>
        <header>
          <span class="pt-title">Paratext thread{thread?.verseRef ? ` · ${thread.verseRef}` : ""}</span>
          {#if thread?.resolved}
            <span class="pt-state done" title={bridgeResolved ? "" : "Shown only: Bridge's status changes only if you mark it resolved."}>Resolved in Paratext</span>
          {:else if thread}
            <span class="pt-state">Open in Paratext</span>
          {/if}
        </header>
        {#if !thread}
          <p class="pt-msg">Sent. The thread shows here once Bridge has read Paratext's notes file again.</p>
        {:else}
          <ol class="pt-comments">
            {#each thread.comments as comment, i (i)}
              <li>
                <div class="pt-meta"><strong>{comment.user}</strong> · {when(comment.date)}{comment.status === "done" || comment.status === "deleted" ? " · resolved" : ""}</div>
                {#if comment.contents}<div class="pt-text">{shown(comment.contents)}</div>{/if}
              </li>
            {/each}
          </ol>
          {#if replyFor === link.threadId}
            <label class="pt-reply">
              <span>Reply in Paratext</span>
              <textarea bind:value={replyText} rows="2" placeholder="Your reply, as you" />
            </label>
            <div class="pt-actions">
              <button class="small-btn" on:click={() => sendReply(link.threadId)} disabled={Boolean(busy) || !replyText.trim()}>
                {busy === `reply:${link.threadId}` ? "Sending…" : "Send reply"}</button>
              <button class="small-btn" on:click={() => { replyFor = ""; replyText = ""; }} disabled={Boolean(busy)}>Cancel</button>
            </div>
          {:else}
            <div class="pt-actions">
              <button class="small-btn" on:click={() => { replyFor = link.threadId; replyText = ""; }} disabled={Boolean(busy)}>Reply</button>
              {#if !thread.resolved}
                <button class="small-btn" on:click={() => resolveThread(link.threadId)} disabled={Boolean(busy)}>
                  {busy === `resolve:${link.threadId}` ? "Resolving…" : "Resolve in Paratext"}</button>
              {:else if onResolveHere && !bridgeResolved}
                <button class="small-btn" on:click={() => resolveHere(link.threadId)} disabled={Boolean(busy)}>
                  {busy === `here:${link.threadId}` ? "Marking…" : "Mark resolved in Bridge"}</button>
              {/if}
            </div>
          {/if}
        {/if}
      </article>
    {/each}
    {#each data.pending as item (item.messageId)}
      <p class="pt-msg" role="status">
        {item.op === "resolve" ? "Resolve" : item.op === "add_comment" ? "Reply" : "Note"}
        {item.status === "refused" ? "refused by Paratext; it waits for Retry handoff." : "queued for Paratext."}
        {item.lastError}
      </p>
    {/each}
    <div class="pt-actions">
      {#if candidates === null}
        <button class="small-btn" on:click={showCandidates} disabled={Boolean(busy)}>Link existing thread</button>
      {:else if candidates.length === 0}
        <span class="pt-msg">No other Paratext thread on this verse to link.</span>
        <button class="small-btn" on:click={() => (candidates = null)}>Close</button>
      {:else}
        <ul class="pt-candidates" aria-label="Paratext threads on this verse">
          {#each candidates as thread (thread.id)}
            <li>
              <span>{thread.lastUser} · {when(thread.lastDate)} · {thread.excerpt}</span>
              <button class="small-btn" on:click={() => linkThread(thread.id)} disabled={Boolean(busy)}>Link</button>
            </li>
          {/each}
        </ul>
        <button class="small-btn" on:click={() => (candidates = null)}>Close</button>
      {/if}
    </div>
    {#if notice}<p class="pt-msg" role="status">{notice}</p>{/if}
  {/if}
</section>

<style>
  .pt-threads { display: grid; gap: 6px; margin-top: 8px; font-size: var(--fs-2xs); }
  .small-btn { border-radius: 5px; cursor: pointer; font-size: var(--fs-2xs); padding: 5px 8px; color: var(--text-2);
    background: var(--surface); border: 1px solid var(--border-strong); }
  .small-btn:disabled { opacity: .55; cursor: not-allowed; }
  .pt-thread { border: 1px solid var(--border); border-radius: 7px; padding: 7px 9px; background: var(--surface); }
  .pt-thread.resolved { opacity: .8; }
  .pt-thread header { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; }
  .pt-title { font-weight: 700; color: var(--text); }
  .pt-state { border-radius: 999px; padding: 0 7px; background: var(--accent-bg); color: var(--accent); font-weight: 700; }
  .pt-state.done { background: var(--success-bg); color: var(--success); }
  .pt-comments { list-style: none; margin: 6px 0 0; padding: 0; display: grid; gap: 5px; }
  .pt-meta { color: var(--text-2); }
  .pt-text { white-space: pre-wrap; overflow-wrap: anywhere; font-family: var(--font-target, inherit); color: var(--text); }
  .pt-msg { margin: 0; color: var(--text-2); line-height: 1.4; }
  .pt-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 6px; }
  .pt-reply { display: grid; gap: 4px; margin-top: 6px; font-weight: 650; color: var(--text-2); }
  .pt-reply textarea { width: 100%; box-sizing: border-box; border: 1px solid var(--border); border-radius: 5px; padding: 6px 7px;
    font: inherit; color: var(--text); background: var(--surface); resize: vertical; }
  .pt-candidates { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; width: 100%; }
  .pt-candidates li { display: flex; align-items: center; gap: 6px; justify-content: space-between; }
  .pt-candidates li span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-2); }
</style>
