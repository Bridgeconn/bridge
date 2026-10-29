<script lang="ts">
  import type { BookProgressEntry, ProjectReport, CoverageState } from "../types/finding";
  import type { CollectionQaBook } from "../types/collectionQa";
  import ParatextLinkStatus from "./ParatextLinkStatus.svelte";
  import CollectionQaPanel from "./CollectionQaPanel.svelte";
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";
  import { collectionQa } from "../collectionQa";

  // The project dashboard (restyled 2026-10-28). One header card: the
  // project, its language and book count, the Paratext link, and for a
  // collection the Collection QA bar. Below it two cards: the books, each
  // row carrying its progress and its last Collection QA result, and the QA
  // report of the previewed book. Every control is a shared .ui-* class
  // from index.css, the same shapes as Project Home.

  export let projectName: string;
  export let subtitle = "";
  export let books: BookProgressEntry[];
  export let loading: boolean;
  export let error: string;
  export let onSelectBook: (path: string) => void;
  export let onPreviewBook: (path: string) => void = () => {};
  export let onRetry: () => void;

  // Project-level QA report for whichever book is currently open — see
  // BridgeEngine.build_project_report(). It is NOT built when the project
  // opens: measured at ~130 s on Genesis of a real Bible, during which the
  // single-threaded sidecar answers nothing else, so it used to blow the
  // 30 s client timeout and freeze the app. null now means "not asked for
  // yet", and the panel prompts for a book instead of showing an empty shell.
  export let report: ProjectReport | null = null;
  export let reportLoading = false;
  export let reportError = "";
  /** The open book, for the wording of the explicit "build it" action. */
  export let openBookName = "";
  export let onLoadReport: () => void = () => {};
  export let onNavigateToFinding: (chapter: string, verse: string) => void = () => {};
  /** #240: the signed-in user, to filter to "My work"; whether they may
   *  assign (a project_admin); and the row's Assign… action. */
  export let myUserId = "";
  export let canAssign = false;
  export let onAssign: (path: string) => void = () => {};

  let bookSearch = "";
  let myWorkOnly = false;

  $: isCollection = books.length > 1;
  $: subtitleParts = subtitle.split(" · ").map((part) => part.trim()).filter(Boolean);

  // Each book's last Collection QA result, by book id, from the one store
  // the Collection QA bar also reads. Nothing is shown for a book no run
  // has recorded.
  $: qaByBook = new Map<string, CollectionQaBook>(
    ($collectionQa?.books ?? []).map((book) => [book.bookId.toLowerCase(), book]),
  );

  const QA_STATE: Record<string, { label: string; tone: string }> = {
    pending: { label: "QA pending", tone: "" },
    running: { label: "Checking…", tone: "accent" },
    done: { label: "QA done", tone: "pass" },
    skipped: { label: "QA unchanged", tone: "pass" },
    failed: { label: "QA failed", tone: "danger" },
  };

  function qaFindings(book: CollectionQaBook): number {
    return Object.values(book.findingsByCategory).reduce((n, v) => n + v, 0);
  }

  function qaTooltip(book: CollectionQaBook): string {
    const parts = [`Collection QA: ${QA_STATE[book.state]?.label ?? book.state}`];
    if (book.checkedVerses) parts.push(`${book.checkedVerses} verses checked`);
    const findings = Object.entries(book.findingsByCategory).filter(([, n]) => n > 0);
    parts.push(findings.length ? `open findings: ${findings.map(([k, n]) => `${k} ${n}`).join(", ")}` : "no open findings");
    if (book.completedAt) parts.push(`last run ${new Date(book.completedAt).toLocaleString()}`);
    if (book.error) parts.push(book.error);
    return parts.join(" · ");
  }

  function isMine(book: BookProgressEntry): boolean {
    return Boolean(myUserId) && (book.assignments ?? []).some((a) => a.assigneeId === myUserId);
  }

  /** "Genesis: Revant · ch 3: Rina" -- the book's assignee first, then chapters. */
  function assigneeLine(book: BookProgressEntry): string {
    const items = book.assignments ?? [];
    if (items.length === 0) return "";
    const whole = items.find((a) => a.chapter === "");
    const chapters = items.filter((a) => a.chapter !== "");
    const parts = [];
    if (whole) parts.push(`book: ${whole.assigneeName || whole.assigneeId}`);
    if (chapters.length > 0) {
      const shown = chapters.slice(0, 3).map((a) => `ch ${a.chapter}: ${a.assigneeName || a.assigneeId}`);
      parts.push(shown.join(", ") + (chapters.length > 3 ? ` +${chapters.length - 3}` : ""));
    }
    return parts.join(" · ");
  }

  $: normalizedBookSearch = bookSearch.trim().toLocaleLowerCase();
  $: myWorkCount = books.filter(isMine).length;
  $: filteredBooks = books.filter((book) => {
    if (myWorkOnly && !isMine(book)) return false;
    if (!normalizedBookSearch) return true;
    return `${book.bookId ?? ""} ${book.bookName ?? ""}`
      .toLocaleLowerCase()
      .includes(normalizedBookSearch);
  });

  /** #322: Enter or Space on the row previews the book. A key pressed on the
   *  row's own Open or Assign… button bubbles here too; it is left alone so
   *  the button's own activation (open, assign) still happens. */
  function onBookRowKeydown(event: KeyboardEvent, book: BookProgressEntry): void {
    if (event.target !== event.currentTarget) return;
    if (book.missing || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    onPreviewBook(book.path);
  }

  function percent(part: number, total: number): number {
    if (total <= 0) return 0;
    return Math.round((part / total) * 100);
  }

  /** The four progress stages of a checked book, each over what has been
   *  counted, never over the whole book (#239), so an unvisited chapter is
   *  not read as unaligned. */
  function meters(progress: NonNullable<BookProgressEntry["progress"]>): { label: string; value: number; tone: string }[] {
    const rows = [
      { label: `Checked ${progress.checkedChapterCount}/${progress.chapterCount} chapters`, value: percent(progress.checkedChapterCount, progress.chapterCount), tone: "checked" },
      { label: `Reviewed ${progress.reviewedVerseCount}/${progress.verseCount}`, value: percent(progress.reviewedVerseCount, progress.verseCount), tone: "reviewed" },
    ];
    if ((progress.alignedKnownVerseCount ?? 0) > 0) {
      rows.push({ label: `Aligned ${progress.alignedVerseCount ?? 0}/${progress.alignedKnownVerseCount}`, value: percent(progress.alignedVerseCount ?? 0, progress.alignedKnownVerseCount ?? 0), tone: "aligned" });
    }
    if ((progress.languageQaCheckedVerseCount ?? 0) > 0) {
      rows.push({ label: `Language QA clean ${progress.languageQaCleanVerseCount ?? 0}/${progress.languageQaCheckedVerseCount}`, value: percent(progress.languageQaCleanVerseCount ?? 0, progress.languageQaCheckedVerseCount ?? 0), tone: "language-qa" });
    }
    return rows;
  }

  const COVERAGE_ORDER: CoverageState[] = ["ISSUE", "REVIEW_REQUIRED", "NOT_CHECKED", "PASS"];
  const COVERAGE_LABEL: Record<CoverageState, string> = {
    PASS: "Pass", ISSUE: "Issue", REVIEW_REQUIRED: "Review required", NOT_CHECKED: "Not checked",
  };
  const COVERAGE_CLASS: Record<CoverageState, string> = {
    PASS: "pass", ISSUE: "issue", REVIEW_REQUIRED: "review", NOT_CHECKED: "not-checked",
  };

  // The queue was capped at 25 with a dead "+ N more" paragraph under it (#144):
  // it named the hidden rows and gave no way to reach any of them.
  const EXCEPTION_PAGE = 25;
  let shownExceptions = EXCEPTION_PAGE;

  function showMoreExceptions(): void {
    shownExceptions += EXCEPTION_PAGE;
  }

  // A new report is a new list, so the page position must not carry over from
  // the last one -- otherwise rebuilding it for another book keeps showing
  // however many rows were expanded before. Reading `report` is what makes
  // this re-run; `shownExceptions` is only written, so paging does not reset
  // itself.
  $: if (report) shownExceptions = EXCEPTION_PAGE;

  let expandedRows = new Set<string>();

  function toggleExpanded(key: string): void {
    const next = new Set(expandedRows);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    expandedRows = next;
  }

  // The report only carries the open book's code; its localized name (as
  // parsed from the source USFM's \h/\toc2 line at import — see
  // project_import.py) lives on the matching row in `books`.
  $: openBook = report
    ? books.find((book) => (book.bookId ?? "").toLowerCase() === (report!.bookId ?? "").toLowerCase())
    : undefined;
  $: previewedId = (report?.bookId ?? "").toLowerCase();
</script>

<div class="screen">
  <header class="header ui-card">
    <div class="header-row">
      <div class="identity">
        <h1>{projectName}</h1>
        <div class="facts">
          {#each subtitleParts as part}<span class="ui-chip">{part}</span>{/each}
          <ParatextLinkStatus projectKey={`${projectName}:${openBookName}`} />
        </div>
      </div>
    </div>
    {#if isCollection}
      <div class="qa-bar"><CollectionQaPanel bookCount={books.length} /></div>
    {/if}
  </header>

  <div class="panels">
    <aside class="books-card ui-card" aria-label="Books in this project">
      <div class="card-head">
        <h2>Books <span class="count">{books.length}</span></h2>
        {#if books.length > 0}
          <div class="book-tools">
            <label class="search" for="book-search">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg>
              <input id="book-search" type="search" bind:value={bookSearch} placeholder="Find a book: name or code, e.g. Luke or LUK" aria-label="Find a book" />
            </label>
            {#if myUserId}
              <label class="my-work">
                <input type="checkbox" bind:checked={myWorkOnly} />
                My work ({myWorkCount})
              </label>
            {/if}
            <span class="shown" role="status">{filteredBooks.length} of {books.length}</span>
          </div>
        {/if}
      </div>
      <div class="card-body">
        {#if loading}
          <p class="empty">Loading book progress…</p>
        {:else if error}
          <div class="error-row">
            <span>Could not load book progress: {error}</span>
            <button class="ui-btn small" on:click={onRetry}>Retry</button>
          </div>
        {:else if books.length === 0}
          <p class="empty">No books found in this project.</p>
        {:else}
          <section class="books">
            {#each filteredBooks as book (book.path)}
              {@const previewed = (book.bookId ?? "").toLowerCase() === previewedId}
              {@const qa = qaByBook.get((book.bookId ?? "").toLowerCase())}
              <div
                class:missing={book.missing}
                class:previewed
                class="book-row"
                role="button"
                tabindex={book.missing ? -1 : 0}
                aria-disabled={book.missing}
                aria-current={previewed ? "true" : undefined}
                on:click={() => !book.missing && onPreviewBook(book.path)}
                on:keydown={(e) => onBookRowKeydown(e, book)}
              >
                <div class="book-badge">{book.bookId?.toUpperCase() || "?"}</div>
                <div class="book-copy">
                  <div class="book-title">
                    <strong>{book.bookName || book.bookId || "Unnamed book"}</strong>
                    {#if qa && qa.state !== "pending"}
                      <span class="ui-chip {QA_STATE[qa.state]?.tone ?? ''}" use:tooltip={qaTooltip(qa)}>
                        {#if qa.state === "done" || qa.state === "skipped"}<UiIcon name="check" />{:else if qa.state === "failed"}<UiIcon name="warning" />{/if}
                        {QA_STATE[qa.state]?.label ?? qa.state}{#if qa.state !== "running" && qa.state !== "failed"}{` · ${qaFindings(qa)} ${qaFindings(qa) === 1 ? "finding" : "findings"}`}{/if}
                      </span>
                    {/if}
                  </div>
                  {#if book.missing}
                    <span class="note danger">Project folder is missing</span>
                  {:else if book.lazy || book.progress === null}
                    <span class="note">Not yet opened</span>
                  {:else if book.progress.checkedChapterCount === 0}
                    <span class="note">Not yet checked</span>
                  {:else}
                    <div class="meters">
                      {#each meters(book.progress) as meter}
                        <div class="meter" use:tooltip={`${meter.label} (${meter.value}%)`}>
                          <span class="meter-label">{meter.label}</span>
                          <div class="track"><div class="fill {meter.tone}" style="width:{meter.value}%"></div></div>
                        </div>
                      {/each}
                    </div>
                    {#if book.progress.updatedAt}
                      <small>Updated {new Date(book.progress.updatedAt).toLocaleString()}</small>
                    {/if}
                  {/if}
                  {#if assigneeLine(book)}
                    <small class="assignees" class:mine={isMine(book)}>{assigneeLine(book)}</small>
                  {/if}
                </div>
                <div class="book-actions">
                  {#if canAssign && !book.missing}
                    <button class="ui-icon-btn" aria-label="Assign…" use:tooltip={`Assign ${book.bookName || book.bookId?.toUpperCase() || "book"}`} on:click|stopPropagation={() => onAssign(book.path)}><UiIcon name="assign" /></button>
                  {/if}
                  <button class="ui-icon-btn primary" aria-label="Open" use:tooltip={`Open ${book.bookName || book.bookId?.toUpperCase() || "book"}`}
                    on:click|stopPropagation={() => onSelectBook(book.path)} disabled={book.missing}><UiIcon name="open" /></button>
                </div>
              </div>
            {:else}
              <p class="empty">No books match “{bookSearch}”.</p>
            {/each}
          </section>
        {/if}
      </div>
    </aside>

    <main class="report-card ui-card" aria-label="QA report">
      <div class="card-head">
        <h2>QA report</h2>
        {#if report}
          <span class="report-book" title={openBook?.bookName || report.bookId?.toUpperCase()}>
            {openBook?.bookName || report.bookId?.toUpperCase()}{#if openBook?.bookName} <span class="book-code">{report.bookId?.toUpperCase()}</span>{/if}
          </span>
        {/if}
      </div>
      <div class="card-body">
      {#if reportLoading}
        <div class="report-state">
          <div class="spin" aria-hidden="true"></div>
          <p class="state-title">Building the QA report…</p>
          <p class="state-hint">
            It reads every verse of the open book, so on a full-length book this takes
            a couple of minutes, and the rest of the app waits for it.
          </p>
        </div>
      {:else if reportError}
        <div class="report-state">
          <p class="state-title danger">Could not load report: {reportError}</p>
          <button type="button" class="ui-btn" on:click={onLoadReport}>Try again</button>
        </div>
      {:else if report}
        <div class="report-area" aria-label="Current book QA report">
          <!-- #337: a tick means every verse checked and nothing blocking open.
               Unchecked verses are named with their count, never folded into
               "No blocking issues"; an open high or critical check finding from
               any engine blocks like an open high Language QA finding. Advisory. -->
          <div
            class="gate"
            class:ready={report.publicationGate.readyForHumanPublicationSignoff}
            class:unchecked={(report.publicationGate.uncheckedVerses ?? 0) > 0}
          >
            {#if (report.publicationGate.uncheckedVerses ?? 0) > 0}
              Not checked ({report.publicationGate.uncheckedVerses} of {report.publicationGate.totalVerses} verses) in
              {report.bookId?.toUpperCase()} — run checks on every verse before this gate can clear.
            {:else if report.publicationGate.readyForHumanPublicationSignoff}
              ✓ Every verse checked, no blocking issues open in {report.bookId?.toUpperCase()} — advisory only, not a translation-quality signoff.
            {:else}
              {(report.publicationGate.checkCriticalFindings ?? 0) + (report.publicationGate.checkHighFindings ?? 0)} high/critical check finding(s) ·
              {report.publicationGate.criticalFindings} critical · {report.publicationGate.highFindings} high AI ·
              {report.publicationGate.languageQaBlocking ?? 0} Language QA ·
              {report.publicationGate.staleAIReviews} stale · {report.publicationGate.openDiscussions} discussion(s) open in {report.bookId?.toUpperCase()}
            {/if}
          </div>

          <div class="coverage">
            <div class="coverage-head"><span>Verse coverage</span><strong>{report.coverage.verses.checkedPercent}% checked</strong></div>
            <div class="coverage-bar" role="img" aria-label="Verse checking coverage">
              {#each COVERAGE_ORDER as state (state)}
                {#if report.coverage.verses.counts[state] > 0}
                  <div
                    class="coverage-seg {COVERAGE_CLASS[state]}"
                    style="width:{percent(report.coverage.verses.counts[state], report.coverage.verses.totalVerses)}%"
                    title="{COVERAGE_LABEL[state]}: {report.coverage.verses.counts[state]}"
                  />
                {/if}
              {/each}
            </div>
            <div class="coverage-legend">
              {#each COVERAGE_ORDER as state (state)}
                <span class="legend-item"><i class={COVERAGE_CLASS[state]} />{COVERAGE_LABEL[state]} {report.coverage.verses.counts[state]}</span>
              {/each}
            </div>
          </div>

          <div class="queue-head">
            <h3>Verses needing attention</h3>
            <span class="count">{report.exceptionQueue.length}</span>
          </div>
          {#if report.exceptionQueue.length > 0}
            <div class="exceptions" aria-label="Verses needing attention">
              {#each report.exceptionQueue.slice(0, shownExceptions) as row (row.chapter + ':' + row.verse)}
                {@const key = row.chapter + ":" + row.verse}
                {@const helps = row.helpsFindings ?? []}
                {@const tnCount = helps.filter((f) => f.tool === "translationNotes").length}
                {@const twCount = helps.filter((f) => f.tool === "translationWords").length}
                {@const detailCount = row.localFindings.length + helps.length}
                {@const hasDetail = detailCount > 0}
                <div class="exception-item">
                  <div class="exception-row-wrap">
                    <button class="exception-row" on:click={() => onNavigateToFinding(row.chapter, row.verse)}>
                      <span class="ref">{report.bookId?.toUpperCase()} {row.chapter}:{row.verse}</span>
                      {#if row.critical}<span class="pill critical">{row.critical} critical</span>{/if}
                      {#if row.high}<span class="pill high">{row.high} high</span>{/if}
                      {#if tnCount}<span class="pill tn">{tnCount} tN</span>{/if}
                      {#if twCount}<span class="pill tw">{twCount} tW</span>{/if}
                      {#if row.discussions}<span class="pill discussion">{row.discussions} discussion</span>{/if}
                      {#if row.wordAlignment === "invalid"}<span class="pill invalid">alignment invalid</span>{/if}
                      {#if row.summary}<span class="summary">{row.summary}</span>{/if}
                    </button>
                    {#if hasDetail}
                      <button
                        type="button"
                        class="expand-toggle"
                        aria-label={expandedRows.has(key) ? "Collapse findings" : `Show ${detailCount} finding(s)`}
                        aria-expanded={expandedRows.has(key)}
                        on:click={() => toggleExpanded(key)}
                      >{detailCount} finding{detailCount === 1 ? "" : "s"} <span class="chevron" class:open={expandedRows.has(key)}><UiIcon name="chevronDown" /></span></button>
                    {/if}
                  </div>
                  {#if hasDetail && expandedRows.has(key)}
                    <div class="local-findings">
                      {#each row.localFindings as finding}
                        <div class="local-finding-row source-gr">
                          <span class="pill engine">{finding.engine}</span>
                          <span class="pill {finding.severity}">{finding.severity}</span>
                          <span class="local-explain">{finding.explanation}</span>
                        </div>
                      {/each}
                      {#each helps as finding}
                        <div class="local-finding-row source-{finding.tool === 'translationNotes' ? 'tn' : 'tw'}">
                          <span class="pill engine">{finding.tool === "translationNotes" ? "tN" : "tW"}</span>
                          <span class="pill {finding.severity}">{finding.severity}</span>
                          <span class="local-explain">{finding.explanation}</span>
                        </div>
                      {/each}
                    </div>
                  {/if}
                </div>
              {/each}
              {#if report.exceptionQueue.length > shownExceptions}
                <div class="more">
                  <button type="button" class="ui-btn small" on:click={showMoreExceptions}>
                    Show {Math.min(EXCEPTION_PAGE, report.exceptionQueue.length - shownExceptions)} more
                  </button>
                  <span>showing {shownExceptions} of {report.exceptionQueue.length}</span>
                </div>
              {/if}
            </div>
          {:else}
            <p class="empty">No verses currently need attention in this book.</p>
          {/if}
        </div>
      {:else}
        <div class="report-state">
          <span class="state-icon" aria-hidden="true"><UiIcon name="report" /></span>
          <p class="state-title">Select a book on the left to check it for errors.</p>
          <p class="state-hint">
            The report reads every verse of the open book and takes a couple of minutes on a full-length one, so it is built only when you ask.
          </p>
          {#if openBookName}
            <button type="button" class="ui-btn primary" on:click={onLoadReport}>
              Build the QA report for {openBookName}
            </button>
          {/if}
        </div>
      {/if}
      </div>
    </main>
  </div>
</div>

<style>
  /* The header card and the two content cards are the only scroll owners'
     parents: each card body scrolls on its own, the screen never does. */
  .screen { flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 14px; padding: 16px 24px 18px; box-sizing: border-box; overflow: hidden; background: var(--bg); }
  .header { flex-shrink: 0; display: flex; flex-direction: column; gap: 12px; padding: 14px 20px; }
  .header-row { display: flex; align-items: center; justify-content: space-between; gap: 14px; min-width: 0; }
  .identity { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; min-width: 0; }
  h1 { margin: 0; font-size: var(--fs-2xl); line-height: 1.25; color: var(--text); overflow-wrap: anywhere; }
  .facts { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; min-width: 0; }
  .qa-bar { padding-top: 12px; border-top: 1px solid var(--border); }

  .panels { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(360px, 5fr) minmax(0, 7fr); gap: 14px; }
  .books-card, .report-card { display: flex; flex-direction: column; min-height: 0; min-width: 0; overflow: hidden; }
  .card-head { flex-shrink: 0; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 14px; padding: 14px 18px 12px; border-bottom: 1px solid var(--border); }
  h2 { display: flex; align-items: center; gap: 8px; margin: 0; font-size: var(--fs-md); font-weight: 650; color: var(--text); }
  .count { display: grid; place-items: center; min-width: 24px; height: 22px; padding: 0 6px; box-sizing: border-box; border: 1px solid var(--border); border-radius: 7px; color: var(--text-2); background: var(--surface); font-size: var(--fs-3xs); font-weight: 600; }
  .card-body { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; scrollbar-gutter: stable; padding: 12px 14px 16px; }
  .empty { background: var(--surface-2); color: var(--text-2); border-radius: 8px; padding: 14px; font-size: var(--fs-xs); margin: 0; }
  .error-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; background: var(--danger-bg); color: var(--danger); border-radius: 8px; padding: 12px 14px; font-size: var(--fs-xs); }

  /* Book list */
  .book-tools { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; flex: 1 1 320px; min-width: 0; }
  .search { display: flex; align-items: center; gap: 8px; flex: 1 1 220px; min-width: 0; height: 34px; padding: 0 10px; box-sizing: border-box; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface); }
  .search:focus-within { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-bg); }
  .search svg { width: 16px; height: 16px; flex-shrink: 0; color: var(--text-2); }
  .search input { flex: 1; min-width: 0; border: 0; background: transparent; padding: 0; font: inherit; font-size: var(--fs-2xs); color: var(--text); outline: none; }
  .search input::placeholder { color: var(--text-3); }
  .my-work { display: inline-flex; align-items: center; gap: 6px; font-size: var(--fs-2xs); color: var(--text-2); white-space: nowrap; cursor: pointer; }
  .my-work input { width: 16px; height: 16px; margin: 0; accent-color: var(--accent); }
  .shown { color: var(--text-3); font-size: var(--fs-3xs); white-space: nowrap; }
  .books { display: flex; flex-direction: column; gap: 8px; }
  .book-row { display: flex; align-items: center; gap: 12px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); cursor: pointer; transition: border-color .15s, background .15s; }
  .book-row:hover { border-color: var(--border-strong); background: var(--surface-2); }
  .book-row:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
  .book-row.previewed { border-color: var(--accent); background: var(--accent-bg); }
  .book-row.missing { background: var(--warning-bg); cursor: default; }
  .book-badge { width: 40px; height: 40px; display: grid; place-items: center; border-radius: 10px; background: var(--accent-bg); color: var(--accent); font-size: var(--fs-2xs); font-weight: 800; flex-shrink: 0; align-self: flex-start; }
  .book-copy { display: flex; flex-direction: column; min-width: 0; flex: 1; gap: 4px; }
  .book-title { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; min-height: 22px; }
  .book-title strong { font-size: var(--fs-sm); color: var(--text); overflow-wrap: anywhere; }
  .note { color: var(--text-2); font-size: var(--fs-2xs); }
  .note.danger { color: var(--danger); }
  .book-copy small { color: var(--text-3); font-size: var(--fs-3xs); }
  .assignees { color: var(--text-2); }
  .assignees.mine { color: var(--accent); font-weight: 650; }
  .book-actions { display: flex; align-items: center; gap: 2px; flex-shrink: 0; align-self: center; }
  .meters { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px 14px; margin-top: 2px; }
  .meter { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
  .meter-label { color: var(--text-2); font-size: var(--fs-3xs); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .track { width: 100%; height: 5px; background: var(--border); border-radius: 3px; overflow: hidden; }
  .fill { height: 100%; background: var(--accent); }
  .fill.checked { background: var(--pass); }
  .fill.reviewed { background: var(--accent); }
  .fill.aligned { background: var(--align); }
  .fill.language-qa { background: var(--lqa); }

  /* Report */
  .report-book { display: flex; align-items: baseline; gap: 6px; min-width: 0; font-weight: 650; color: var(--text); font-size: var(--fs-sm); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .book-code { color: var(--text-2); font-size: var(--fs-3xs); font-weight: 600; }
  .report-state { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; max-width: 520px; padding: 14px 6px; }
  .state-icon { display: grid; place-items: center; width: 40px; height: 40px; border-radius: 12px; background: var(--accent-bg); color: var(--accent); margin-bottom: 4px; }
  .state-title { margin: 0; font-size: var(--fs-sm); font-weight: 600; color: var(--text); }
  .state-title.danger { color: var(--danger); }
  .state-hint { margin: 0 0 6px; color: var(--text-2); font-size: var(--fs-2xs); line-height: 1.55; }
  .spin { width: 22px; height: 22px; border: 3px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin .9s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .report-area { max-width: 900px; }
  .gate { display: flex; align-items: center; gap: 8px; border-radius: 10px; padding: 10px 14px; font-size: var(--fs-xs); font-weight: 600; line-height: 1.45; background: var(--danger-bg); color: var(--danger); margin-bottom: 14px; }
  .gate.ready { background: var(--pass-bg); color: var(--pass); }
  .gate.unchecked { background: var(--surface-2); color: var(--text-2); border: 1px solid var(--border); }
  .coverage { padding: 12px 14px; border: 1px solid var(--border); border-radius: 10px; margin-bottom: 16px; }
  .coverage-head { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; margin-bottom: 8px; font-size: var(--fs-2xs); color: var(--text-2); }
  .coverage-head strong { color: var(--text); font-size: var(--fs-sm); }
  .coverage-bar { display: flex; width: 100%; height: 10px; border-radius: 5px; overflow: hidden; background: var(--surface-2); }
  .coverage-seg { height: 100%; }
  .coverage-seg.pass { background: var(--pass); }
  .coverage-seg.issue { background: var(--danger); }
  .coverage-seg.review { background: var(--warning); }
  .coverage-seg.not-checked { background: var(--border-strong); }
  .coverage-legend { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px; margin-top: 8px; font-size: var(--fs-3xs); color: var(--text-2); }
  .legend-item { display: inline-flex; align-items: center; gap: 5px; }
  .legend-item i { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .legend-item i.pass { background: var(--pass); }
  .legend-item i.issue { background: var(--danger); }
  .legend-item i.review { background: var(--warning); }
  .legend-item i.not-checked { background: var(--border-strong); }
  .queue-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  h3 { margin: 0; font-size: var(--fs-sm); font-weight: 650; color: var(--text); }
  .exceptions { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
  .exception-item { border-bottom: 1px solid var(--border); }
  .exception-item:last-child { border-bottom: 0; }
  .exception-row-wrap { display: flex; align-items: stretch; background: var(--surface); }
  .exception-row { flex: 1; min-width: 0; text-align: left; display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 9px 12px; border: 0; background: none; cursor: pointer; font: inherit; }
  .exception-row:hover { background: var(--surface-2); }
  .exception-row:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .exception-row .ref { font-weight: 700; font-size: var(--fs-xs); color: var(--text); flex-shrink: 0; }
  .exception-row .summary { color: var(--text-2); font-size: var(--fs-2xs); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pill { font-size: var(--fs-3xs); font-weight: 700; padding: 2px 7px; border-radius: 999px; flex-shrink: 0; }
  .pill.critical { background: var(--danger-bg); color: var(--danger); }
  .pill.high { background: var(--warning-bg); color: var(--warning); }
  .pill.medium { background: var(--warning-bg); color: var(--warning); }
  .pill.low { background: var(--surface-2); color: var(--text-2); }
  .pill.discussion { background: var(--accent-bg); color: var(--accent); }
  .pill.invalid { background: var(--surface-2); color: var(--text-2); }
  .pill.engine { background: var(--accent-bg); color: var(--accent); text-transform: capitalize; }
  /* Same finding-source legend as the verse underlines and the review panel
     (index.css mark.m-*): Greek Room red, tN green, tW teal. */
  .pill.tn { background: var(--tn-bg); color: var(--tn); }
  .pill.tw { background: var(--tw-bg); color: var(--tw); }
  .expand-toggle { display: inline-flex; align-items: center; gap: 4px; flex-shrink: 0; align-self: center; margin-right: 10px; padding: 2px 6px 2px 9px; border-radius: 999px; border: 0; background: var(--accent-bg); color: var(--accent); font: inherit; font-size: var(--fs-3xs); font-weight: 700; cursor: pointer; }
  .expand-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .chevron { display: inline-grid; place-items: center; transition: transform .15s; }
  .chevron :global(svg) { width: 14px; height: 14px; }
  .chevron.open { transform: rotate(180deg); }
  .local-findings { background: var(--surface-2); padding: 6px 12px 10px 32px; display: flex; flex-direction: column; gap: 6px; }
  .local-finding-row { display: flex; align-items: center; gap: 7px; font-size: var(--fs-2xs); border-left: 3px solid transparent; padding-left: 6px; }
  .local-finding-row.source-gr { border-left-color: var(--gr); }
  .local-finding-row.source-tn { border-left-color: var(--tn); }
  .local-finding-row.source-tw { border-left-color: var(--tw); }
  .local-explain { color: var(--text-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .more { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-top: 1px solid var(--border); color: var(--text-2); font-size: var(--fs-3xs); }

  @media (max-width: 1100px) {
    .meters { grid-template-columns: minmax(0, 1fr); }
  }
  @media (max-width: 900px) {
    .screen { overflow-y: auto; }
    .panels { grid-template-columns: minmax(0, 1fr); }
    .books-card, .report-card { overflow: visible; }
    .card-body { overflow: visible; }
    .books-card .card-body { max-height: 50vh; overflow-y: auto; }
  }
  @media (max-width: 640px) {
    .screen { padding: 12px; gap: 10px; }
    .header { padding: 12px 14px; }
    .card-head, .card-body { padding-left: 12px; padding-right: 12px; }
  }
  @media (max-height: 700px) {
    .screen { padding-top: 10px; gap: 10px; }
    .header { padding: 10px 18px; gap: 8px; }
    .qa-bar { padding-top: 8px; }
    h1 { font-size: var(--fs-xl); }
  }
  @media (prefers-reduced-motion: reduce) {
    .book-row, .chevron { transition: none; }
    .spin { animation: none; }
  }
</style>
