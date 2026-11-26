<script lang="ts">
  /** The dashboard's Proofread dialog (#505): what a proofreading run needs
   *  and what it would cost, before anything is sent. It reads
   *  proofreading.preflight, which is worked out offline; choosing a reference
   *  folder is the only thing here that changes anything. Pure UI otherwise:
   *  the panel that opens it starts the run. */
  import { onMount } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import { compactCount } from "../proofreading";
  import type { ProofreadingPreflight } from "../types/proofreading";

  /** Another check is running on the dashboard: the dialog opens, Start does not. */
  export let checkRunning = false;
  export let onStart: (books: string[] | null, force: boolean) => void;
  export let onClose: () => void;

  // The 39 Old Testament book codes, for the scope choice.
  const OLD_TESTAMENT = new Set(
    ("gen exo lev num deu jos jdg rut 1sa 2sa 1ki 2ki 1ch 2ch ezr neh est job psa pro ecc sng isa jer lam "
      + "ezk dan hos jol amo oba jon mic nam hab zep hag zec mal").split(" "),
  );

  type Scope = "all" | "ot" | "nt" | "chosen";

  let preflight: ProofreadingPreflight | null = null;
  let error = "";
  let loading = true;
  let choosing = false;
  let scope: Scope = "all";
  let chosen = new Set<string>();
  let force = false;
  let dialog: HTMLDivElement;

  // Escape and Cancel do the same; focus goes back to the Proofread button.
  let openedFrom: Element | null = null;
  onMount(() => {
    openedFrom = document.activeElement;
    void load();
    return () => { if (openedFrom instanceof HTMLElement && openedFrom.isConnected) openedFrom.focus(); };
  });

  async function load(): Promise<void> {
    loading = true;
    try {
      preflight = await bridge.proofreadingPreflight();
      error = "";
    } catch (e) {
      // What was on screen is no longer known to be true: after a reference
      // was changed and this re-read failed, the old one would still be shown
      // and Start would run against the new one. Nothing is shown, and Start
      // waits for a re-read that works.
      preflight = null;
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  async function chooseReference(): Promise<void> {
    if (choosing) return;
    choosing = true;
    try {
      const folder = await bridge.pickFolder();
      if (folder) {
        await bridge.proofreadingSetReference(folder);
        await load();
      }
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      choosing = false;
    }
  }

  function onWindowKeydown(event: KeyboardEvent): void {
    if (event.key === "Escape" && !event.defaultPrevented) { event.preventDefault(); onClose(); }
  }

  function setChosen(bookId: string, on: boolean): void {
    if (on) chosen.add(bookId); else chosen.delete(bookId);
    chosen = chosen;
  }

  $: readable = (preflight?.books ?? []).filter((book) => book.supported);
  $: unsupported = (preflight?.books ?? []).length - readable.length;
  $: selected = readable.filter((book) => {
    const id = book.bookId.toLowerCase();
    if (scope === "ot") return OLD_TESTAMENT.has(id);
    if (scope === "nt") return !OLD_TESTAMENT.has(id);
    if (scope === "chosen") return chosen.has(book.bookId);
    return true;
  });
  // Without "read again", a book unchanged since its last run is skipped;
  // which ones are unchanged is only known once the text is staged, so the
  // estimate counts every selected book and says so.
  $: total = selected.reduce((sum, book) => ({
    requests: sum.requests + book.estimate.requests,
    tokens: sum.tokens + book.estimate.inputTokens + book.estimate.outputTokens,
    usd: sum.usd + book.estimate.estimatedCostUSD,
  }), { requests: 0, tokens: 0, usd: 0 });
  $: alreadyRead = selected.filter((book) => book.previous).length;
  $: blocked = loading ? "Checking"
    : !preflight ? "Not available"
    : !preflight.aiReady ? "Set up the AI in Settings > AI provider"
    : preflight.haltReason ? "The AI provider is not taking requests just now"
    : preflight.reference.error ? "Choose a reference Bible"
    : selected.length === 0 ? "Choose at least one book"
    : checkRunning || preflight.checkRunning ? "A check is already running"
    : "";

  function start(): void {
    if (blocked || !preflight) return;
    onStart(scope === "all" ? null : selected.map((book) => book.bookId), force);
  }

  function cost(usd: number): string {
    return usd >= 100 ? `about $${Math.round(usd).toLocaleString()}` : `about $${usd.toFixed(2)}`;
  }
</script>

<svelte:window on:keydown={onWindowKeydown} />

<div class="overlay">
  <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="proofreading-start-title" bind:this={dialog}>
    <h2 id="proofreading-start-title">Proofread</h2>
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    {#if loading && !preflight}
      <p class="note first">Checking what a run needs…</p>
    {:else if !preflight}
      <p class="note first">
        What a run needs could not be read.
        <button type="button" class="ui-btn small" on:click={load}>Try again</button>
      </p>
    {:else if preflight}
      <dl class="facts">
        <dt>AI</dt>
        <dd class:bad={!preflight.aiReady || Boolean(preflight.haltReason)}>
          {#if !preflight.aiReady}
            Not set up. Sign in or add a key in Settings &gt; AI provider.
          {:else if preflight.haltReason}
            {preflight.haltReason}
          {:else}
            {preflight.model} · {preflight.planUsage ? "your ChatGPT sign-in" : "your API key"}
          {/if}
        </dd>
        <dt>Reference</dt>
        <dd class:bad={Boolean(preflight.reference.error)}>
          <span class="reference">
            {#if preflight.reference.path}
              <span class="reference-name" title={preflight.reference.path}>{preflight.reference.label}</span>
              {#if preflight.reference.origin === "project"}<span class="muted">(the project's reference Bible)</span>{/if}
            {:else}
              No reference Bible chosen
            {/if}
            <button type="button" class="ui-btn small" disabled={choosing} on:click={chooseReference}>
              {preflight.reference.path ? "Change" : "Choose folder"}
            </button>
          </span>
          {#if preflight.reference.error && preflight.reference.path}<span class="why">{preflight.reference.error}</span>{/if}
          {#if !preflight.reference.path}<span class="why">A folder of USFM/SFM files, or a verses.tsv, of the Bible to compare against.</span>{/if}
        </dd>
        <dt>Language</dt>
        <dd>
          {preflight.language.label || preflight.language.code || "Unknown"}
          <span class="muted">· {preflight.profile.code === "generic" ? "no reviewed rule profile for this language; findings that rest on language rules are marked for review" : `${preflight.profile.name} profile`}</span>
        </dd>
      </dl>

      <div class="scope" role="radiogroup" aria-label="Books to proofread">
        <label><input type="radio" name="proofreading-scope" value="all" bind:group={scope} /> All {readable.length} books</label>
        <label><input type="radio" name="proofreading-scope" value="ot" bind:group={scope} /> Old Testament</label>
        <label><input type="radio" name="proofreading-scope" value="nt" bind:group={scope} /> New Testament</label>
        <label><input type="radio" name="proofreading-scope" value="chosen" bind:group={scope} /> Choose books</label>
      </div>
      {#if scope === "chosen"}
        <div class="books" role="group" aria-label="Books">
          {#each readable as book (book.bookId)}
            <label title={book.previous?.completedAt ? `Last proofread ${new Date(book.previous.completedAt).toLocaleString()}` : "Not proofread yet"}>
              <input type="checkbox" checked={chosen.has(book.bookId)} on:change={(event) => setChosen(book.bookId, event.currentTarget.checked)} />
              <span class="book-name">{book.bookName || book.bookId.toUpperCase()}</span>
              {#if book.previous}<span class="read" aria-label="proofread before">✓</span>{/if}
            </label>
          {/each}
        </div>
      {/if}
      {#if unsupported}<p class="muted small-note">{unsupported} book{unsupported === 1 ? " is" : "s are"} outside the 66 the proofreading toolkit knows and cannot be read.</p>{/if}

      <label class="recheck">
        <input type="checkbox" bind:checked={force} />
        Also read books unchanged since they were last proofread
      </label>

      <p class="estimate" aria-live="polite">
        <strong>{selected.length} {selected.length === 1 ? "book" : "books"}</strong>
        <span>about {total.requests.toLocaleString()} requests</span>
        <span>~{compactCount(total.tokens)} tokens</span>
        <span class="cost" class:plan={preflight.planUsage}>{preflight.planUsage ? "uses your ChatGPT plan allowance" : cost(total.usd)}</span>
        <span class="muted">estimate{#if alreadyRead && !force}; {alreadyRead} already read {alreadyRead === 1 ? "is" : "are"} skipped if unchanged{/if}</span>
      </p>
      <p class="note">
        Each book's text and the reference are sent to the AI provider, a few chapters at a time. Every finding is a
        proposal for a person to review: no Scripture is changed. Editing and switching books wait until the run ends;
        Pause stops after the current book, and a book that was read is never paid for twice.
      </p>
    {/if}
    <div class="buttons">
      {#if blocked && !loading}<span class="blocked" role="status">{blocked}</span>{/if}
      <button type="button" class="ui-btn" on:click={onClose}>Cancel</button>
      <button type="button" class="ui-btn primary" disabled={Boolean(blocked)} on:click={start}>Start</button>
    </div>
  </div>
</div>

<style>
  .overlay { position: fixed; inset: 0; background: rgba(15, 20, 26, 0.45); display: flex; align-items: center; justify-content: center; z-index: var(--z-dialog); }
  .dialog { width: min(560px, calc(100% - 32px)); max-height: 88vh; overflow: auto; display: flex; flex-direction: column; gap: 12px; padding: 20px 24px; border-radius: 14px; background: var(--surface); box-shadow: 0 16px 40px rgba(25, 35, 55, .25); }
  h2 { margin: 0; font-size: var(--fs-lg); color: var(--text); }
  .facts { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 8px 14px; margin: 0; font-size: var(--fs-xs); }
  dt { color: var(--text-2); font-weight: 600; }
  dd { margin: 0; min-width: 0; color: var(--text); display: flex; flex-direction: column; gap: 4px; overflow-wrap: anywhere; }
  dd.bad { color: var(--danger); }
  .reference { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 8px; }
  .reference-name { font-weight: 600; }
  .why { color: var(--text-2); font-size: var(--fs-2xs); }
  .muted { color: var(--text-2); font-size: var(--fs-2xs); }
  .small-note { margin: 0; }
  .scope { display: flex; flex-wrap: wrap; gap: 8px 16px; padding-top: 10px; border-top: 1px solid var(--border); }
  label { display: flex; align-items: center; gap: 8px; font-size: var(--fs-xs); color: var(--text); cursor: pointer; }
  input { width: 16px; height: 16px; margin: 0; accent-color: var(--accent); flex-shrink: 0; }
  .books { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 6px 12px; max-height: 190px; overflow: auto; padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-2); }
  .book-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .read { color: var(--pass); font-size: var(--fs-2xs); }
  .recheck { padding-top: 10px; border-top: 1px solid var(--border); }
  .estimate { margin: 0; display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 12px; padding: 10px 12px; border-radius: 8px; background: var(--accent-bg); color: var(--text); font-size: var(--fs-2xs); }
  .cost { font-weight: 650; }
  .cost.plan { color: var(--accent); }
  .note { margin: 0; padding-top: 10px; border-top: 1px solid var(--border); color: var(--text-2); font-size: var(--fs-2xs); line-height: 1.5; }
  .note.first { border-top: 0; padding-top: 0; }
  .error { margin: 0; color: var(--danger); font-size: var(--fs-2xs); }
  .buttons { display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
  .blocked { margin-right: auto; color: var(--text-2); font-size: var(--fs-2xs); }
</style>
