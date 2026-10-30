<script context="module" lang="ts">
  export type ConflictChoice = "skip" | "replace";

  /** Which books would be written for the current choices: every new book,
   *  plus each existing one marked Replace. Pure, so the test can pin it. */
  export function booksToWrite(books: AddBooksBook[], choices: Record<string, ConflictChoice>): AddBooksBook[] {
    return books.filter((book) => !book.exists || choices[book.bookId] === "replace");
  }
</script>

<script lang="ts">
  import { onDestroy, tick } from "svelte";
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";
  import { bridge } from "../api/bridgeClient";
  import type { AddBooksBook, AddBooksPreview, AddBooksResult, ImportJobSnapshot, RegisteredProject } from "../types/finding";

  // Project Home > Add books. One dialog, five steps:
  //   choose    - files or a folder (the same native pickers as Import a file /
  //               Import a folder, and the same engine inspection behind them)
  //   inspect   - project.inspectAddBooks is running
  //   review    - the books found; an existing book is asked about one at a
  //               time, Skip or Replace, with "do this for all" like a file
  //               copy; then the list with each book's outcome and the button
  //   running   - project.addBooks.start, polled like an import
  //   done      - what was added, replaced and skipped
  // Nothing is written before the Add button; a replace is said in plain
  // words before it, because it takes that book's review data with it.

  export let project: RegisteredProject;
  export let onClose: () => void;
  export let onAdded: (result: AddBooksResult) => void;

  const POLL_MS = 250;
  const TERMINAL = new Set<ImportJobSnapshot["state"]>(["succeeded", "failed", "cancelled"]);

  type Step = "choose" | "inspect" | "review" | "running" | "done";
  let step: Step = "choose";
  let error: string | null = null;
  let preview: AddBooksPreview | null = null;
  let choices: Record<string, ConflictChoice> = {};
  // The conflicts not yet answered, asked in order; applyToAll answers the rest.
  let pending: AddBooksBook[] = [];
  let applyToAll = false;
  let job: ImportJobSnapshot | null = null;
  let result: AddBooksResult | null = null;
  let generation = 0;
  let pollTimer: ReturnType<typeof setTimeout> | undefined;
  let dialogElement: HTMLDialogElement | undefined;

  onDestroy(() => { generation += 1; clearTimeout(pollTimer); });

  $: name = project.displayName || project.projectName || project.bookName || "this project";
  $: conflicts = preview?.books.filter((book) => book.exists) ?? [];
  $: newBooks = preview?.books.filter((book) => !book.exists) ?? [];
  $: current = pending[0] ?? null;
  $: writing = preview ? booksToWrite(preview.books, choices) : [];
  $: replacing = conflicts.filter((book) => choices[book.bookId] === "replace");
  $: skipping = conflicts.filter((book) => choices[book.bookId] !== "replace");
  $: busy = step === "inspect" || step === "running";

  function modal(node: HTMLDialogElement) {
    const previousFocus = document.activeElement;
    if (typeof node.showModal === "function") node.showModal();
    else node.setAttribute("open", "");
    node.querySelector<HTMLElement>("h2")?.focus();
    // Escape is Cancel while nothing is being written; never while it is.
    const onCancel = (event: Event) => { event.preventDefault(); if (!busy) close(); };
    node.addEventListener("cancel", onCancel);
    return { destroy() {
      node.removeEventListener("cancel", onCancel);
      if (typeof node.close === "function" && node.open) node.close();
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    } };
  }

  function message(value: unknown): string {
    return value instanceof Error ? value.message : String(value);
  }

  function close() {
    if (busy) return;
    if (step === "done" && result) onAdded(result);
    onClose();
  }

  async function chooseFiles() {
    const paths = await bridge.pickImportFiles();
    if (paths.length) await inspect(paths);
  }

  async function chooseFolder() {
    const path = await bridge.pickProjectFolder();
    if (path) await inspect([path]);
  }

  async function inspect(paths: string[]) {
    step = "inspect";
    error = null;
    try {
      preview = await bridge.inspectAddBooks(project.projectId, paths);
      choices = {};
      pending = preview.books.filter((book) => book.exists);
      applyToAll = false;
      step = "review";
      await tick();
      dialogElement?.querySelector<HTMLElement>("h2")?.focus();
    } catch (value) {
      error = message(value);
      preview = null;
      step = "choose";
    }
  }

  function answer(choice: ConflictChoice) {
    if (!current) return;
    const answered = applyToAll ? pending : [current];
    const next = { ...choices };
    for (const book of answered) next[book.bookId] = choice;
    choices = next;
    pending = pending.slice(answered.length);
    applyToAll = false;
  }

  function setChoice(book: AddBooksBook, choice: ConflictChoice) {
    choices = { ...choices, [book.bookId]: choice };
  }

  async function run() {
    if (!preview || writing.length === 0 || busy) return;
    step = "running";
    error = null;
    job = null;
    try {
      const snapshot = await bridge.addBooksStart(
        project.projectId, preview.sourcePaths, replacing.map((book) => book.bookId),
      );
      job = snapshot;
      void poll(snapshot.jobId, ++generation);
    } catch (value) {
      error = message(value);
      step = "review";
    }
  }

  async function poll(jobId: string, mine: number) {
    try {
      while (mine === generation) {
        const snapshot = await bridge.importStatus(jobId);
        if (mine !== generation) return;
        job = snapshot;
        if (TERMINAL.has(snapshot.state)) {
          if (snapshot.state === "succeeded" && snapshot.result) {
            result = snapshot.result as unknown as AddBooksResult;
            step = "done";
          } else {
            error = snapshot.state === "cancelled"
              ? "Adding books was cancelled. Nothing was changed."
              : snapshot.error || "Adding books failed.";
            step = "review";
          }
          return;
        }
        await new Promise<void>((resolve) => { pollTimer = setTimeout(resolve, POLL_MS); });
      }
    } catch (value) {
      if (mine !== generation) return;
      error = message(value);
      step = "review";
    }
  }

  async function cancelRun() {
    if (!job) return;
    try {
      job = await bridge.importCancel(job.jobId);
    } catch (value) {
      error = message(value);
    }
  }

  function fileName(path: string): string {
    return path.split(/[\\/]/).pop() || path;
  }

  function jobLabel(snapshot: ImportJobSnapshot): string {
    const lead = snapshot.state === "cancelling" ? "Cancelling" : snapshot.phaseLabel;
    const book = snapshot.totalBooks > 1 && snapshot.currentBook
      ? ` (book ${Math.min(snapshot.completedBooks + 1, snapshot.totalBooks)} of ${snapshot.totalBooks})`
      : "";
    return `${lead}${book}`;
  }

  function bookList(books: { bookId: string }[]): string {
    return books.map((book) => book.bookId.toUpperCase()).join(", ");
  }

  function countOf(count: number, noun: string): string {
    return `${count} ${count === 1 ? noun : `${noun}s`}`;
  }
</script>

<dialog class="add-books" bind:this={dialogElement} aria-modal="true" aria-labelledby="add-books-title" aria-describedby="add-books-description" use:modal>
  <header>
    <span class="dialog-icon" aria-hidden="true"><UiIcon name="addBooks" /></span>
    <div class="heading">
      <h2 id="add-books-title" tabindex="-1">
        {#if step === "done"}Books added{:else if step === "running"}Adding books{:else if step === "review" && current}Book already in project{:else}Add books to {name}{/if}
      </h2>
      <p id="add-books-description">
        {#if step === "choose" || step === "inspect"}
          Choose Scripture files or a folder. Each book becomes part of this project{project.bibleName ? ` (${project.bibleName})` : ""}.
        {:else if step === "review" && current}
          Choose what to do with a book this project already has.
        {:else if step === "review"}
          {preview?.books.length === 1 ? "One book was found." : `${preview?.books.length ?? 0} books were found.`} Nothing is written until you add them.
        {:else if step === "running"}
          Copying the chosen books into the project. Source files stay unchanged.
        {:else}
          The project now has {countOf(result?.projects.length ?? 0, "book")}.
        {/if}
      </p>
    </div>
    <button class="icon-button close" aria-label="Close" use:tooltip={"Close"} on:click={close} disabled={busy}><UiIcon name="close" /></button>
  </header>

  <div class="body">
    {#if step === "choose" || step === "inspect"}
      <div class="choice-grid">
        <button class="choice" on:click={chooseFiles} disabled={busy} use:tooltip={"Add one or more files: USFM, SFM or TXT"}>
          <span class="choice-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5M12 17v-6m-3 3 3-3 3 3"/></svg></span>
          <span class="choice-copy"><span class="choice-title">Add files</span><span>USFM, SFM or TXT · one or several</span></span>
          <span class="choice-arrow" aria-hidden="true">→</span>
        </button>
        <button class="choice" on:click={chooseFolder} disabled={busy} use:tooltip={"Add every book in a folder: multi-book USFM or Paratext"}>
          <span class="choice-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3 7V5a1 1 0 0 1 1-1h5l2 3h9a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7Z"/><path d="M3 10h18"/></svg></span>
          <span class="choice-copy"><span class="choice-title">Add a folder</span><span>Multi-book USFM or Paratext</span></span>
          <span class="choice-arrow" aria-hidden="true">→</span>
        </button>
      </div>
      {#if step === "inspect"}<p class="working" role="status">Reading the chosen source…</p>{/if}
      <p class="note">A translationCore project or archive is a project of its own: import it from Projects instead.</p>

    {:else if step === "review" && preview && current}
      <div class="conflict" role="group" aria-label={`Book ${current.bookId.toUpperCase()} already in project`}>
        <div class="conflict-book">
          <span class="book-badge">{current.bookId.toUpperCase()}</span>
          <div class="conflict-copy">
            <strong>{current.bookName || current.bookId.toUpperCase()}</strong>
            <small>From <span class="path" title={current.sourceFile}>{fileName(current.sourceFile)}</span>{current.verseCount !== null ? ` · ${current.verseCount} verses` : ""}</small>
            <small>In project: <span class="path" title={current.existingPath}>{fileName(current.existingPath)}</span></small>
          </div>
        </div>
        <div class="conflict-options">
          <button class="option" on:click={() => answer("skip")}>
            <strong>Skip this book</strong>
            <span>Keep the book the project has. The chosen file is not used.</span>
          </button>
          <button class="option danger" on:click={() => answer("replace")}>
            <strong>Replace it</strong>
            <span>Use the chosen file. The current text and Bridge's review data for this book are removed.</span>
          </button>
        </div>
        {#if pending.length > 1}
          <label class="apply-all">
            <input type="checkbox" bind:checked={applyToAll} />
            Do this for all {pending.length} books already in the project
          </label>
        {/if}
        <p class="conflict-progress">{conflicts.length - pending.length + 1} of {conflicts.length} already in the project</p>
      </div>

    {:else if step === "review" && preview}
      <div class="list-heading">
        <h3>Books</h3>
        <span class="summary" aria-live="polite">
          {newBooks.length} new{conflicts.length ? ` · ${replacing.length} replace · ${skipping.length} skip` : ""}
        </span>
      </div>
      <div class="book-list" role="group" aria-label="Books found">
        {#each preview.books as book (book.bookId)}
          <div class="book-row" class:book-skipped={book.exists && choices[book.bookId] !== "replace"}>
            <span class="book-badge">{book.bookId.toUpperCase()}</span>
            <div class="book-copy">
              <strong>{book.bookName || book.bookId.toUpperCase()}</strong>
              <small><span class="path" title={book.sourceFile}>{fileName(book.sourceFile)}</span>{book.verseCount !== null ? ` · ${book.verseCount} verses` : ""}{book.hasAlignments ? " · aligned" : ""}</small>
            </div>
            {#if book.exists}
              <div class="segmented" role="group" aria-label={`${book.bookId.toUpperCase()} is already in the project`}>
                <button type="button" aria-pressed={choices[book.bookId] !== "replace"} on:click={() => setChoice(book, "skip")}>Skip</button>
                <button type="button" class="replace" aria-pressed={choices[book.bookId] === "replace"} on:click={() => setChoice(book, "replace")}>Replace</button>
              </div>
            {:else}
              <span class="chip new">New</span>
            {/if}
          </div>
        {/each}
      </div>
      {#if replacing.length > 0}
        <p class="warning" role="note">Replacing {bookList(replacing)} removes the current text and Bridge's review data for {replacing.length === 1 ? "that book" : "those books"}: decisions, alignment links and check results. Source files stay unchanged.</p>
      {/if}
      {#if preview.warnings.length > 0}
        <details class="source-notes"><summary>Source notes</summary>
          {#each preview.warnings as warning}<p class="note">{warning}</p>{/each}
        </details>
      {/if}

    {:else if step === "running" && job}
      <div class="progress" role="status" aria-live="polite">
        <span class="progress-label">{jobLabel(job)} — {job.percent}%</span>
        <div class="track"><div class="fill" style="width:{job.percent}%"></div></div>
      </div>
      <div class="book-list" aria-label="Books being added">
        {#each writing as book (book.bookId)}
          <div class="book-row">
            <span class="book-badge">{book.bookId.toUpperCase()}</span>
            <div class="book-copy"><strong>{book.bookName || book.bookId.toUpperCase()}</strong></div>
            <span class="chip" class:new={!book.exists} class:replace={book.exists}>{book.exists ? "Replace" : "New"}</span>
          </div>
        {/each}
      </div>

    {:else if step === "done" && result}
      <dl class="outcome">
        <div><dt>Added</dt><dd>{result.added.length ? bookList(result.added) : "—"}</dd></div>
        <div><dt>Replaced</dt><dd>{result.replaced.length ? bookList(result.replaced) : "—"}</dd></div>
        <div><dt>Skipped</dt><dd>{result.skipped.length ? result.skipped.map((id) => id.toUpperCase()).join(", ") : "—"}</dd></div>
      </dl>
      <p class="note">A new book is prepared the first time it is opened, like any book of an imported collection.</p>
    {/if}

    {#if error}<p class="error" role="alert">{error}</p>{/if}
  </div>

  <footer>
    {#if step === "review" && !current}
      <span class="spacer"></span>
      <button class="secondary" on:click={close}>Cancel</button>
      <button class="primary" on:click={run} disabled={writing.length === 0}>
        {writing.length === 0 ? "Nothing to add" : `Add ${countOf(writing.length, "book")}`}
      </button>
    {:else if step === "running"}
      <span class="spacer"></span>
      <button class="secondary" on:click={cancelRun} disabled={!job || job.state === "cancelling"}>{job?.state === "cancelling" ? "Cancelling…" : "Cancel"}</button>
    {:else if step === "done"}
      <span class="spacer"></span>
      <button class="primary" on:click={close}>Done</button>
    {:else}
      <span class="spacer"></span>
      <button class="secondary" on:click={close} disabled={busy}>Cancel</button>
    {/if}
  </footer>
</dialog>

<style>
  .add-books { width: min(680px, calc(100% - 32px)); max-height: min(760px, calc(100dvh - 40px)); padding: 0; border: 1px solid var(--border); border-radius: 18px; background: var(--surface); color: var(--text); box-shadow: 0 24px 80px rgb(0 0 0 / 20%); overflow: hidden; }
  .add-books[open] { display: flex; flex-direction: column; }
  .add-books::backdrop { background: rgb(15 23 42 / 38%); backdrop-filter: blur(3px); }
  header { display: flex; align-items: flex-start; gap: 14px; padding: 24px 24px 18px; flex-shrink: 0; }
  .heading { min-width: 0; flex: 1; }
  .dialog-icon { display: grid; place-items: center; width: 40px; height: 40px; flex-shrink: 0; border-radius: 12px; color: var(--accent); background: var(--accent-bg); }
  h2 { margin: 0; font-size: var(--fs-2xl); line-height: 1.4; overflow-wrap: anywhere; }
  h2:focus { outline: none; }
  header p { margin: 6px 0 0; color: var(--text-2); font-size: var(--fs-xs); line-height: 1.6; }
  .icon-button { display: grid; place-items: center; width: 34px; height: 34px; min-height: 34px; padding: 0; flex-shrink: 0; border: 0; border-radius: 8px; background: transparent; color: var(--text-2); cursor: pointer; transition: color .15s, background .15s; }
  .icon-button:hover:not(:disabled), .icon-button:focus-visible { background: var(--danger-bg); color: var(--danger); }
  .body { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; scrollbar-gutter: stable; padding: 0 24px 8px; }
  button { font: inherit; cursor: pointer; }
  button:disabled { cursor: not-allowed; opacity: .55; }
  button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

  .choice-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  .choice { display: flex; align-items: center; gap: 14px; min-width: 0; min-height: 88px; text-align: left; padding: 16px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); color: var(--text-2); font-size: var(--fs-2xs); line-height: 1.45; transition: background .15s, border-color .15s; }
  .choice:hover:not(:disabled) { border-color: var(--accent); background: var(--accent-bg); }
  .choice:hover:not(:disabled) .choice-arrow { color: var(--accent); }
  .choice-icon { display: grid; place-items: center; flex: 0 0 40px; height: 40px; border-radius: 10px; background: var(--accent-bg); color: var(--accent); }
  .choice-icon svg { width: 22px; height: 22px; }
  .choice-copy { flex: 1; min-width: 0; }
  .choice-title { display: block; color: var(--text); font-size: var(--fs-sm); font-weight: 700; margin-bottom: 3px; }
  .choice-arrow { color: var(--text-2); font-size: 20px; }

  .book-badge { width: 38px; height: 38px; display: grid; place-items: center; border-radius: 9px; background: var(--accent-bg); color: var(--accent); font-size: var(--fs-2xs); font-weight: 800; flex-shrink: 0; }
  .conflict { display: flex; flex-direction: column; gap: 14px; }
  .conflict-book { display: flex; align-items: center; gap: 12px; padding: 12px; border: 1px solid var(--border); border-radius: 11px; background: var(--surface-2); }
  .conflict-copy, .book-copy { display: flex; flex-direction: column; min-width: 0; flex: 1; gap: 2px; }
  .conflict-copy strong, .book-copy strong { font-size: var(--fs-sm); overflow-wrap: anywhere; }
  small { color: var(--text-2); font-size: var(--fs-3xs); line-height: 1.4; overflow-wrap: anywhere; }
  .path { color: var(--text); }
  .conflict-options { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .option { display: flex; flex-direction: column; gap: 5px; text-align: left; padding: 14px; border: 1px solid var(--border-strong); border-radius: 12px; background: var(--surface); color: var(--text-2); font-size: var(--fs-3xs); line-height: 1.5; }
  .option strong { color: var(--text); font-size: var(--fs-sm); }
  .option:hover { border-color: var(--accent); background: var(--accent-bg); }
  .option.danger:hover { border-color: var(--danger); background: var(--danger-bg); }
  .option.danger strong { color: var(--danger); }
  .apply-all { display: flex; align-items: center; gap: 8px; font-size: var(--fs-2xs); color: var(--text); cursor: pointer; }
  .apply-all input { width: 17px; height: 17px; margin: 0; accent-color: var(--accent); cursor: pointer; }
  .conflict-progress { margin: 0; color: var(--text-2); font-size: var(--fs-3xs); }

  .list-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding-bottom: 10px; }
  h3 { margin: 0; font-size: var(--fs-sm); font-weight: 600; }
  .summary { color: var(--text-2); background: var(--surface-2); border: 1px solid var(--border); border-radius: 6px; padding: 2px 8px; font-size: var(--fs-3xs); white-space: nowrap; }
  .book-list { border: 1px solid var(--border); border-radius: 11px; overflow: hidden; }
  .book-row { display: flex; align-items: center; gap: 12px; min-height: 52px; padding: 8px 12px; border-bottom: 1px solid var(--border); }
  .book-row:last-child { border-bottom: 0; }
  .book-skipped { background: var(--surface-2); }
  .book-skipped .book-copy strong { color: var(--text-2); }
  .chip { flex-shrink: 0; border-radius: 6px; padding: 3px 8px; font-size: var(--fs-3xs); font-weight: 650; border: 1px solid var(--border); color: var(--text-2); background: var(--surface-2); }
  .chip.new { color: var(--accent); background: var(--accent-bg); border-color: transparent; }
  .chip.replace { color: var(--danger); background: var(--danger-bg); border-color: transparent; }
  .segmented { display: inline-flex; flex-shrink: 0; gap: 3px; padding: 3px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-2); }
  .segmented button { min-height: 28px; padding: 0 10px; border: 1px solid transparent; border-radius: 6px; background: transparent; color: var(--text-2); font-size: var(--fs-3xs); font-weight: 600; }
  .segmented button[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: white; box-shadow: 0 1px 3px rgb(0 0 0 / 8%); }
  .segmented button.replace[aria-pressed="true"] { background: var(--danger); border-color: var(--danger); }
  .segmented button:hover:not([aria-pressed="true"]) { color: var(--accent); }
  .warning, .note { border-radius: 7px; padding: 9px 10px; font-size: var(--fs-2xs); line-height: 1.5; margin: 12px 0 0; }
  .warning { background: #fff7e6; color: #8a5a00; }
  .note { background: var(--surface-2); color: var(--text-2); }
  .source-notes { margin-top: 10px; font-size: var(--fs-2xs); color: var(--text-2); }
  .source-notes summary { cursor: pointer; padding: 4px 0; }
  .source-notes .note { margin-top: 6px; }
  .working { margin: 12px 0 0; color: var(--text-2); font-size: var(--fs-2xs); }
  .error { color: var(--danger); font-size: var(--fs-2xs); line-height: 1.45; margin: 12px 0 0; }

  .progress { display: flex; flex-direction: column; gap: 8px; margin-bottom: 14px; }
  .progress-label { font-size: var(--fs-xs); color: var(--text); }
  .track { height: 6px; border-radius: 3px; background: var(--border); overflow: hidden; }
  .fill { height: 100%; background: var(--accent); transition: width .2s linear; }
  .outcome { display: grid; gap: 8px; margin: 0; }
  .outcome > div { display: grid; grid-template-columns: 90px minmax(0, 1fr); gap: 12px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 10px; font-size: var(--fs-xs); }
  dt { font-weight: 600; color: var(--text); }
  dd { margin: 0; color: var(--text-2); overflow-wrap: anywhere; }

  footer { flex-shrink: 0; display: flex; align-items: center; gap: 10px; padding: 16px 24px 20px; border-top: 1px solid var(--border); }
  .spacer { flex: 1; }
  footer button { display: inline-flex; align-items: center; justify-content: center; min-height: 38px; padding: 8px 14px; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface); color: var(--text); font-size: var(--fs-2xs); font-weight: 600; }
  footer .primary { background: var(--accent); color: white; border-color: var(--accent); }
  footer .primary:hover:not(:disabled) { filter: brightness(.95); }
  footer .secondary:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
  @media (max-width: 560px) {
    header { padding: 18px 16px 14px; gap: 10px; }
    h2 { font-size: var(--fs-lg); }
    .body { padding-left: 16px; padding-right: 16px; }
    .choice-grid, .conflict-options { grid-template-columns: 1fr; }
    footer { padding: 14px 16px; flex-wrap: wrap; }
    .book-row { flex-wrap: wrap; }
  }
  @media (prefers-reduced-motion: reduce) {
    .icon-button, .choice, .fill { transition: none; }
  }
</style>
