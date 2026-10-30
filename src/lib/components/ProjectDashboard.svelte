<script lang="ts">
  import type { BookProgressEntry, ProjectReport, CoverageState, ExceptionQueueRow } from "../types/finding";
  import type { CollectionQaBook } from "../types/collectionQa";
  import ParatextLinkStatus from "./ParatextLinkStatus.svelte";
  import CollectionQaPanel from "./CollectionQaPanel.svelte";
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";
  import { collectionQa } from "../collectionQa";
  import { checkingProgress } from "../stores";
  import { onDestroy } from "svelte";
  import { formatDuration } from "../collectionQa";

  // The project dashboard (restyled 2026-10-28/29, third pass 2026-10-30).
  // One header card: the project, its language and book count, the Paratext
  // link, and for a collection the Collection QA bar. Below it two cards:
  // the books and the QA report. A row is not clickable; its three icons
  // carry everything. The first is the book's QA state: Run QA (play) on a
  // book nothing has checked, which runs the checks and then shows the
  // report; View QA report once something has; a spinner while its own job
  // runs. Then Assign and Open. The report card shows that job's progress
  // (not the top strip), the build spinner, or the report. Every control is
  // a shared .ui-* class from index.css, the same shapes as Project Home.

  export let projectName: string;
  export let subtitle = "";
  export let books: BookProgressEntry[];
  export let loading: boolean;
  export let error: string;
  export let onSelectBook: (path: string) => void;
  /** The row's View QA report: shows the book's report (kept for the
   *  session, else built). Never runs a check. */
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
  /** The open book, for the wording of the explicit "build it" action, and
   *  its path, so the row of the book the engine has open is known. */
  export let openBookName = "";
  export let openBookPath = "";
  /** When the shown report was built (App keeps one per book for the
   *  session); empty when it was just built or none is shown. */
  export let reportBuiltAt = "";
  /** How long the build in progress is expected to take (reportEstimate.ts):
   *  the card shows elapsed time against it. An estimate, labelled as one. */
  export let reportEstimateSeconds = 0;
  export let onLoadReport: () => void = () => {};
  export let onNavigateToFinding: (chapter: string, verse: string) => void = () => {};
  /** The row's Run QA: the whole book as one check job, then its report.
   *  Disabled while any job (chapter, book or collection) runs or a book is
   *  being opened. `qaRunningPath` is the book whose job this dashboard
   *  started and is still running or just ended: its row spins and the
   *  report card shows the job (checkingProgress) instead of a report. */
  export let onRunBookQa: (path: string) => void = () => {};
  export let qaBusy = false;
  export let qaRunningPath = "";
  export let onCancelQa: () => void = () => {};
  /** The book a row icon is opening in the engine, and the prepare detail
   *  ("preparing chapter 3 of 50") while a never-opened one is prepared. */
  export let openingPath = "";
  export let openingDetail = "";
  /** #240: the signed-in user, to filter to "My work"; whether they may
   *  assign (a project_admin); and the row's Assign… action. */
  export let myUserId = "";
  export let canAssign = false;
  export let onAssign: (path: string) => void = () => {};
  /** The whole-project QA report (the report screen): lives in the header
   *  row beside the project's facts, not in the top bar. */
  export let onGenerateReport: () => void = () => {};

  let bookSearch = "";
  let myWorkOnly = false;
  // Rows whose progress meters are unfolded, by path; folded by default so
  // a checked book is no taller than an unopened one.
  let expandedProgress = new Set<string>();

  $: isCollection = books.length > 1;
  $: subtitleParts = subtitle.split(" · ").map((part) => part.trim()).filter(Boolean);
  // The job the dashboard started, as the report card shows it.
  $: job = qaRunningPath ? $checkingProgress : null;
  $: jobRunning = Boolean(job?.running);
  $: jobEnded = Boolean(job) && !jobRunning && (job?.state === "failed" || job?.state === "cancelled");
  $: openBookRow = openBookPath ? books.find((book) => book.path === openBookPath) : undefined;
  $: openingRow = openingPath ? books.find((book) => book.path === openingPath) : undefined;

  // The build's clock: ticks once a second while a report builds. The bar
  // fills by elapsed/estimate and holds at 95% past it -- the sidecar says
  // nothing during a build, so the end is only known when it arrives.
  let buildStarted = 0;
  let buildElapsed = 0;
  let buildTimer: ReturnType<typeof setInterval> | null = null;
  $: if (reportLoading && !buildTimer) {
    buildStarted = Date.now();
    buildElapsed = 0;
    buildTimer = setInterval(() => { buildElapsed = Math.round((Date.now() - buildStarted) / 1000); }, 1000);
  } else if (!reportLoading && buildTimer) {
    clearInterval(buildTimer);
    buildTimer = null;
  }
  onDestroy(() => { if (buildTimer) clearInterval(buildTimer); });
  $: buildPercent = reportEstimateSeconds > 0 ? Math.min(95, Math.round((buildElapsed / reportEstimateSeconds) * 100)) : 0;
  $: buildLeft = reportEstimateSeconds > 0 ? Math.max(0, reportEstimateSeconds - buildElapsed) : 0;

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

  /** 18705 → "18.7k", 4921 → "4.9k", 985 → "985". */
  function compact(n: number): string {
    if (n < 1000) return String(n);
    const k = n / 1000;
    return `${k >= 100 ? Math.round(k) : k.toFixed(1).replace(/\.0$/, "")}k`;
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

  function bookLabel(book: BookProgressEntry): string {
    return book.bookName || book.bookId?.toUpperCase() || "book";
  }

  function unopened(book: BookProgressEntry): boolean {
    return Boolean(book.lazy) || book.progress === null;
  }

  /** Something has checked this book: its progress counts a checked chapter,
   *  or a Collection QA run finished it. Its first icon is then View QA
   *  report; before that it is Run QA. */
  function checked(book: BookProgressEntry): boolean {
    if ((book.progress?.checkedChapterCount ?? 0) > 0) return true;
    const qa = qaByBook.get((book.bookId ?? "").toLowerCase());
    return qa?.state === "done" || qa?.state === "skipped";
  }

  function toggleProgress(path: string): void {
    const next = new Set(expandedProgress);
    if (next.has(path)) next.delete(path);
    else next.add(path);
    expandedProgress = next;
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
  // itself. A filter change starts from the first page too.
  $: if (report) { shownExceptions = EXCEPTION_PAGE; queueFilter = ""; chapterFilter = ""; chapterOpen = false; }

  // The queue's chapter filter: a dropdown of the chapters the queue has
  // rows in, with a search box once there are many (a 150-chapter Psalms
  // must not be a list to scroll through), and a clear icon on the button.
  let chapterFilter = "";
  let chapterOpen = false;
  let chapterSearch = "";
  $: queueChapters = [...new Set((report?.exceptionQueue ?? []).map((row) => String(row.chapter)))]
    .sort((a, b) => (Number(a) || 0) - (Number(b) || 0) || a.localeCompare(b));
  $: chapterChoices = chapterSearch.trim()
    ? queueChapters.filter((chapter) => chapter.startsWith(chapterSearch.trim()))
    : queueChapters;
  function chooseChapter(chapter: string): void {
    chapterFilter = chapter;
    chapterOpen = false;
    chapterSearch = "";
    shownExceptions = EXCEPTION_PAGE;
  }
  function clearChapter(): void {
    chapterFilter = "";
    shownExceptions = EXCEPTION_PAGE;
  }
  function closeChapterMenu(event: FocusEvent): void {
    const container = event.currentTarget as HTMLElement;
    if (!(event.relatedTarget instanceof Node) || !container.contains(event.relatedTarget)) chapterOpen = false;
  }

  // The queue's filters: one at a time, over what a row carries.
  type QueueFilter = "" | "critical" | "high" | "tn" | "tw" | "alignment" | "discussion";
  let queueFilter: QueueFilter = "";
  const FILTERS: { id: QueueFilter; label: string }[] = [
    { id: "critical", label: "critical" }, { id: "high", label: "high" }, { id: "tn", label: "tN" },
    { id: "tw", label: "tW" }, { id: "alignment", label: "alignment" }, { id: "discussion", label: "discussion" },
  ];
  function helpsOf(row: ExceptionQueueRow, tool: string): number {
    return (row.helpsFindings ?? []).filter((f) => f.tool === tool).length;
  }
  function matches(row: ExceptionQueueRow, filter: QueueFilter): boolean {
    switch (filter) {
      case "critical": return row.critical > 0;
      case "high": return row.high > 0;
      case "tn": return helpsOf(row, "translationNotes") > 0;
      case "tw": return helpsOf(row, "translationWords") > 0;
      case "alignment": return row.wordAlignment === "invalid";
      case "discussion": return row.discussions > 0;
      default: return true;
    }
  }
  $: chapterRows = (report?.exceptionQueue ?? []).filter((row) => !chapterFilter || String(row.chapter) === chapterFilter);
  $: filterCounts = Object.fromEntries(FILTERS.map((f) => [f.id, chapterRows.filter((row) => matches(row, f.id)).length])) as Record<QueueFilter, number>;
  $: queueRows = chapterRows.filter((row) => matches(row, queueFilter));
  function setFilter(id: QueueFilter): void {
    queueFilter = queueFilter === id ? "" : id;
    shownExceptions = EXCEPTION_PAGE;
  }

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

  function builtAtLabel(iso: string): string {
    const when = new Date(iso);
    return Number.isNaN(when.getTime()) ? iso : when.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }

  $: gate = report?.publicationGate;
  $: tiles = gate ? [
    { label: "Check findings", hint: "Open high or critical findings from any check engine", value: (gate.checkCriticalFindings ?? 0) + (gate.checkHighFindings ?? 0), tone: ((gate.checkCriticalFindings ?? 0) + (gate.checkHighFindings ?? 0)) > 0 ? "danger" : "" },
    { label: "AI findings", hint: "Open critical and high AI review findings", value: gate.criticalFindings + gate.highFindings, tone: gate.criticalFindings + gate.highFindings > 0 ? "danger" : "" },
    { label: "Language QA", hint: "Open high Language QA findings", value: gate.languageQaBlocking ?? 0, tone: (gate.languageQaBlocking ?? 0) > 0 ? "warning" : "" },
    { label: "Discussions", hint: "Open discussions", value: gate.openDiscussions, tone: gate.openDiscussions > 0 ? "accent" : "" },
    { label: "Stale AI reviews", hint: "AI reviews older than the verse they reviewed", value: gate.staleAIReviews, tone: gate.staleAIReviews > 0 ? "warning" : "" },
    { label: "Unchecked verses", hint: "Verses no check has run on", value: gate.uncheckedVerses ?? 0, tone: (gate.uncheckedVerses ?? 0) > 0 ? "warning" : "" },
  ] : [];
</script>

<div class="screen">
  <header class="header ui-card">
    <div class="header-row">
      <div class="identity">
        <h1>{projectName}</h1>
        <div class="facts">
          {#each subtitleParts as part}<span class="ui-chip accent">{part}</span>{/each}
          <ParatextLinkStatus projectKey={`${projectName}:${openBookName}`} />
        </div>
      </div>
      <button type="button" class="project-report-btn" use:tooltip={"Generate the QA report for the whole project"} on:click={onGenerateReport}>
        <span class="report-badge" aria-hidden="true"><UiIcon name="report" /></span>
        <span class="report-text">Project report</span>
      </button>
    </div>
    {#if isCollection}
      <div class="qa-bar"><CollectionQaPanel bookCount={books.length} /></div>
    {/if}
  </header>

  <div class="panels">
    <aside class="books-card ui-card" aria-label="Books in this project">
      <div class="card-head">
        <h2>Books <span class="ui-chip accent">{books.length}</span></h2>
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
            <span class="shown" role="status"><strong>{filteredBooks.length}</strong> of <strong>{books.length}</strong></span>
          </div>
        {/if}
      </div>
      <div class="card-body">
        {#if loading && books.length === 0}
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
              {@const previewed = (!openingPath && (book.bookId ?? "").toLowerCase() === previewedId) || (jobRunning && qaRunningPath === book.path) || openingPath === book.path}
              {@const qa = qaByBook.get((book.bookId ?? "").toLowerCase())}
              {@const open = expandedProgress.has(book.path)}
              {@const running = (jobRunning && qaRunningPath === book.path) || openingPath === book.path}
              <div class:missing={book.missing} class:previewed class="book-row" aria-current={previewed ? "true" : undefined}>
                <div class="book-badge">{book.bookId?.toUpperCase() || "?"}</div>
                <div class="book-copy">
                  <div class="book-title">
                    <strong>{book.bookName || book.bookId || "Unnamed book"}</strong>
                    {#if qa && qa.state !== "pending"}
                      <span class="ui-chip {QA_STATE[qa.state]?.tone ?? ''}" use:tooltip={qaTooltip(qa)}>
                        {#if qa.state === "done" || qa.state === "skipped"}<UiIcon name="check" />{:else if qa.state === "failed"}<UiIcon name="warning" />{/if}
                        {QA_STATE[qa.state]?.label ?? qa.state}{#if qa.state !== "running" && qa.state !== "failed"}{` · ${compact(qaFindings(qa))} ${qaFindings(qa) === 1 ? "finding" : "findings"}`}{/if}
                      </span>
                    {/if}
                  </div>
                  {#if book.missing}
                    <span class="note danger">Project folder is missing</span>
                  {:else if unopened(book)}
                    <span class="note">Not yet opened</span>
                  {:else if book.progress && book.progress.checkedChapterCount === 0}
                    <span class="note">Not yet checked</span>
                  {:else if book.progress}
                    <div class="progress-line">
                      <button type="button" class="progress-toggle" aria-expanded={open} aria-label={open ? `Hide progress of ${bookLabel(book)}` : `Show progress of ${bookLabel(book)}`}
                        on:click={() => toggleProgress(book.path)}>
                        {open ? "Hide progress" : "Progress"}<span class="chevron" class:open><UiIcon name="chevronDown" /></span>
                      </button>
                    </div>
                    {#if open}
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
                  {/if}
                  {#if assigneeLine(book)}
                    <small class="assignees" class:mine={isMine(book)}>{assigneeLine(book)}</small>
                  {/if}
                </div>
                <div class="book-actions">
                  {#if running}
                    <span class="ui-icon-btn running" role="status" aria-label={`${openingPath === book.path ? "Opening" : "Checking"} ${bookLabel(book)}`} use:tooltip={`${openingPath === book.path ? "Opening" : "Checking"} ${bookLabel(book)}…`}><span class="spin small" aria-hidden="true"></span></span>
                  {:else if !book.missing && checked(book)}
                    <button class="ui-icon-btn primary" aria-label="View QA report" use:tooltip={`View the QA report of ${bookLabel(book)}`}
                      disabled={qaBusy} on:click={() => onPreviewBook(book.path)}><UiIcon name="viewReport" /></button>
                  {:else if !book.missing}
                    <button class="ui-icon-btn success" aria-label="Run QA" use:tooltip={qaBusy ? "A check is already running" : `Run QA on ${bookLabel(book)}: every chapter, with the Collection QA checks, then show its report`}
                      disabled={qaBusy} on:click={() => onRunBookQa(book.path)}><UiIcon name="play" /></button>
                  {/if}
                  {#if canAssign && !book.missing}
                    <button class="ui-icon-btn assign" aria-label="Assign…" use:tooltip={`Assign ${bookLabel(book)}`} on:click={() => onAssign(book.path)}><UiIcon name="assign" /></button>
                  {/if}
                  <button class="ui-icon-btn primary" aria-label="Open" use:tooltip={`Open ${bookLabel(book)}`}
                    on:click={() => onSelectBook(book.path)} disabled={book.missing}><UiIcon name="open" /></button>
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
        <div class="report-title">
          <h2>QA Report</h2>
          {#if report && !job && !openingPath}
            <span class="title-dot" aria-hidden="true">•</span>
            <span class="report-book" title={openBook?.bookName || report.bookId?.toUpperCase()}>
              {openBook?.bookName || report.bookId?.toUpperCase()}{#if openBook?.bookName} <span class="book-code">{report.bookId?.toUpperCase()}</span>{/if}
            </span>
            {#if reportBuiltAt}<span class="built-at">built {builtAtLabel(reportBuiltAt)}</span>{/if}
          {:else if job && qaRunningPath}
            <span class="title-dot" aria-hidden="true">•</span>
            <span class="report-book">{books.find((b) => b.path === qaRunningPath)?.bookName || openBookName}</span>
          {/if}
        </div>
        {#if report && !job && !openingPath}
            <div class="report-actions">
              <button type="button" class="ui-icon-btn success" aria-label="Run QA again" disabled={qaBusy || reportLoading}
                use:tooltip={qaBusy ? "A check is already running" : `Run QA again on ${openBook?.bookName || report.bookId?.toUpperCase()}, then show the fresh report`}
                on:click={() => onRunBookQa(openBook?.path ?? openBookPath)}><UiIcon name="play" /></button>
              <button type="button" class="ui-icon-btn rebuild" aria-label="Rebuild" disabled={reportLoading}
                use:tooltip={"Rebuild this report from the findings on disk, without running checks"}
                on:click={onLoadReport}><UiIcon name="rebuild" /></button>
            </div>
        {/if}
      </div>
      <div class="card-body">
      {#if openingPath}
        <div class="report-state job" aria-live="polite">
          <div class="job-head">
            <div class="spin" aria-hidden="true"></div>
            <div class="job-copy">
              <p class="state-title">Opening {openingRow ? bookLabel(openingRow) : "book"}…</p>
              <p class="state-hint">{openingDetail || (openingRow && unopened(openingRow) ? "Preparing the book for its first open" : "Loading the book")}</p>
            </div>
          </div>
          <div class="job-track" aria-hidden="true"><div class="job-fill indeterminate"></div></div>
        </div>
      {:else if job && jobRunning}
        {@const jobBook = books.find((b) => b.path === qaRunningPath)}
        <div class="report-state job" aria-live="polite">
          <div class="job-head">
            <div class="spin" aria-hidden="true"></div>
            <div class="job-copy">
              <p class="state-title">Checking {jobBook ? bookLabel(jobBook) : openBookName}…</p>
              <p class="state-hint">{job.label || "Starting"} · {job.percent}%</p>
            </div>
          </div>
          <div class="job-track" aria-hidden="true"><div class="job-fill" style="width:{job.percent}%"></div></div>
          <p class="state-hint">Every chapter is checked in turn, then the QA report is built from the results. Editing waits until it ends.</p>
          <button type="button" class="ui-btn danger" on:click={onCancelQa} disabled={job.state === "cancelling" || job.state === "finalizing"}>
            <UiIcon name="close" />{job.state === "cancelling" ? "Cancelling…" : "Cancel"}</button>
        </div>
      {:else if job && jobEnded}
        <div class="report-state">
          <p class="state-title danger">{job.error || (job.state === "cancelled" ? "Checking was cancelled." : "Checking failed.")}</p>
          <div class="state-actions">
            <button type="button" class="ui-btn" disabled={qaBusy} on:click={() => onRunBookQa(qaRunningPath)}><UiIcon name="play" />Run QA again</button>
          </div>
        </div>
      {:else if reportLoading}
        <div class="report-state job" aria-live="polite">
          <div class="job-head">
            <div class="spin" aria-hidden="true"></div>
            <div class="job-copy">
              <p class="state-title">Building the QA report for {openBookName || "this book"}…</p>
              <p class="state-hint">
                {formatDuration(buildElapsed)} elapsed{#if reportEstimateSeconds > 0}{buildLeft > 0 ? ` · about ${formatDuration(buildLeft)} left` : " · nearly there"}{/if}
              </p>
            </div>
          </div>
          <div class="job-track" aria-hidden="true"><div class="job-fill" style="width:{buildPercent}%"></div></div>
          <p class="state-hint">
            The time is an estimate from the book's length{#if reportEstimateSeconds > 0}{` (about ${formatDuration(reportEstimateSeconds)} in all)`}{/if}. The build reads every verse of the book, so the rest of the app waits for it.
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

          <div class="tiles" aria-label="What is open in this book">
            {#each tiles as tile}
              <div class="tile {tile.tone}" use:tooltip={tile.hint}>
                <span class="tile-value">{compact(tile.value)}</span>
                <span class="tile-label">{tile.label}</span>
              </div>
            {/each}
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
            <span class="count">{queueFilter || chapterFilter ? `${queueRows.length} of ${report.exceptionQueue.length}` : report.exceptionQueue.length}</span>
            {#if queueChapters.length > 1}
              <div class="chapter-control" on:focusout={closeChapterMenu}>
                <div class="chapter-button" class:chosen={Boolean(chapterFilter)}>
                  <button type="button" class="chapter-pick" aria-haspopup="listbox" aria-expanded={chapterOpen} aria-controls="queue-chapter-menu"
                    on:click={() => (chapterOpen = !chapterOpen)}>
                    {chapterFilter ? `Chapter ${chapterFilter}` : "All chapters"}<UiIcon name="chevronDown" />
                  </button>
                  {#if chapterFilter}
                    <button type="button" class="chapter-clear" aria-label="Clear chapter filter" use:tooltip={"Show every chapter"} on:click={clearChapter}><UiIcon name="close" /></button>
                  {/if}
                </div>
                {#if chapterOpen}
                  <div class="chapter-menu" id="queue-chapter-menu">
                    {#if queueChapters.length > 12}
                      <!-- svelte-ignore a11y-autofocus -->
                      <input type="search" class="chapter-search" placeholder="Chapter number" aria-label="Find a chapter" bind:value={chapterSearch} autofocus />
                    {/if}
                    <div class="chapter-grid" role="listbox" aria-label="Chapter">
                      {#each chapterChoices as chapter (chapter)}
                        <button type="button" role="option" aria-selected={chapterFilter === chapter} class="chapter-option" on:click={() => chooseChapter(chapter)}>{chapter}</button>
                      {:else}
                        <span class="chapter-none">No chapter matches</span>
                      {/each}
                    </div>
                  </div>
                {/if}
              </div>
            {/if}
            {#if report.exceptionQueue.length > 0}
              <div class="filters" role="group" aria-label="Filter verses">
                {#each FILTERS as filter}
                  {#if filterCounts[filter.id] > 0}
                    <button type="button" class="filter pill {filter.id}" aria-pressed={queueFilter === filter.id} on:click={() => setFilter(filter.id)}>
                      {filter.label} {filterCounts[filter.id]}
                    </button>
                  {/if}
                {/each}
              </div>
            {/if}
          </div>
          {#if report.exceptionQueue.length > 0}
            <div class="exceptions" aria-label="Verses needing attention">
              {#each queueRows.slice(0, shownExceptions) as row (row.chapter + ':' + row.verse)}
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
              {:else}
                <p class="empty">No verses match this filter.</p>
              {/each}
              {#if queueRows.length > shownExceptions}
                <div class="more">
                  <button type="button" class="ui-btn small" on:click={showMoreExceptions}>
                    Show {Math.min(EXCEPTION_PAGE, queueRows.length - shownExceptions)} more
                  </button>
                  <span>showing {shownExceptions} of {queueRows.length}</span>
                </div>
              {/if}
            </div>
          {:else}
            <p class="empty">No verses currently need attention in this book.</p>
          {/if}
        </div>
      {:else if openBookName && openBookRow && !checked(openBookRow)}
        <div class="report-state">
          <span class="state-icon" aria-hidden="true"><UiIcon name="play" /></span>
          <p class="state-title">{openBookName} has not been checked yet.</p>
          <p class="state-hint">Nothing has been checked in it, so there is no report. Run QA on it to check every chapter and build its report.</p>
          <button type="button" class="ui-btn primary" disabled={qaBusy} on:click={() => onRunBookQa(openBookRow?.path ?? openBookPath)}>
            <UiIcon name="play" />Run QA on {openBookName}
          </button>
        </div>
      {:else}
        <div class="report-state">
          <span class="state-icon" aria-hidden="true"><UiIcon name="report" /></span>
          <p class="state-title">Pick a book on the left to see its QA report.</p>
          <ul class="legend" aria-label="What the book icons do">
            <li><span class="legend-icon success"><UiIcon name="play" /></span><span><strong>Run QA</strong> checks the book, then builds its report.</span></li>
            <li><span class="legend-icon accent"><UiIcon name="viewReport" /></span><span><strong>View QA report</strong> shows a checked book's report.</span></li>
            <li><span class="legend-icon accent"><UiIcon name="open" /></span><span><strong>Open</strong> reads and edits the book.</span></li>
          </ul>
          <p class="state-hint">Building a report reads every verse, so it takes a couple of minutes on a full-length book.</p>
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
  .project-report-btn { display: inline-flex; align-items: center; gap: 10px; height: 36px; padding: 0 18px 0 6px; flex-shrink: 0; border: 0; border-radius: 999px; background: linear-gradient(135deg, #3B82F6 0%, var(--accent) 55%, #2458C7 100%); color: #fff; font: inherit; font-size: var(--fs-sm); font-weight: 600; letter-spacing: .01em; line-height: 1; cursor: pointer; box-shadow: 0 1px 2px rgba(15, 23, 42, .12), 0 4px 12px rgba(47, 111, 237, .28), inset 0 1px 0 rgba(255, 255, 255, .18); transition: transform .15s ease, box-shadow .15s ease, filter .15s ease; }
  .report-badge { display: grid; place-items: center; width: 26px; height: 26px; border-radius: 50%; background: rgba(255, 255, 255, .18); box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .22); }
  .report-badge :global(svg) { width: 15px; height: 15px; }
  .report-text { padding-top: 1px; }
  .project-report-btn:hover, .project-report-btn:focus-visible { transform: translateY(-1px); filter: brightness(1.05); box-shadow: 0 2px 4px rgba(15, 23, 42, .12), 0 8px 18px rgba(47, 111, 237, .34), inset 0 1px 0 rgba(255, 255, 255, .22); }
  .project-report-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .project-report-btn:active { transform: translateY(0); filter: brightness(.97); box-shadow: 0 1px 2px rgba(15, 23, 42, .14), 0 2px 6px rgba(47, 111, 237, .25); }
  .qa-bar { padding-top: 12px; border-top: 1px solid var(--border); }

  .panels { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(360px, 5fr) minmax(0, 7fr); gap: 14px; }
  .books-card, .report-card { display: flex; flex-direction: column; min-height: 0; min-width: 0; overflow: hidden; }
  .card-head { flex-shrink: 0; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 14px; padding: 14px 18px 12px; border-bottom: 1px solid var(--border); }
  h2 { display: flex; align-items: center; gap: 8px; margin: 0; font-size: var(--fs-md); font-weight: 650; color: var(--text); }
  .count { display: grid; place-items: center; min-width: 24px; height: 22px; padding: 0 6px; box-sizing: border-box; border: 1px solid var(--border); border-radius: 7px; color: var(--text-2); background: var(--surface); font-size: var(--fs-3xs); font-weight: 600; white-space: nowrap; }
  h2 .ui-chip { font-size: var(--fs-2xs); }
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
  .shown { color: var(--text-2); font-size: var(--fs-3xs); white-space: nowrap; }
  .shown strong { color: var(--accent); font-weight: 700; font-size: var(--fs-2xs); }
  .books { display: flex; flex-direction: column; gap: 8px; }
  .book-row { display: flex; align-items: center; gap: 12px; padding: 10px 10px 10px 12px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); transition: border-color .15s, background .15s; }
  .book-row:hover { border-color: var(--border-strong); }
  .book-row.previewed { border-color: var(--accent); background: var(--accent-bg); }
  .book-row.missing { background: var(--warning-bg); }
  .book-badge { width: 40px; height: 40px; display: grid; place-items: center; border-radius: 10px; background: var(--accent-bg); color: var(--accent); font-size: var(--fs-2xs); font-weight: 800; flex-shrink: 0; }
  .book-copy { display: flex; flex-direction: column; min-width: 0; flex: 1; gap: 3px; }
  .book-title { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 10px; min-height: 22px; }
  .book-title strong { font-size: var(--fs-sm); color: var(--text); overflow-wrap: anywhere; }
  .note { color: var(--text-2); font-size: var(--fs-2xs); }
  .note.danger { color: var(--danger); }
  .book-copy small { color: var(--text-3); font-size: var(--fs-3xs); }
  .assignees { color: var(--text-2); }
  .assignees.mine { color: var(--accent); font-weight: 650; }
  .progress-line { display: flex; align-items: center; min-width: 0; }
  .progress-toggle { display: inline-flex; align-items: center; gap: 2px; margin-left: -4px; padding: 1px 4px; border: 0; border-radius: 5px; background: transparent; color: var(--accent); font: inherit; font-size: var(--fs-3xs); font-weight: 600; cursor: pointer; white-space: nowrap; }
  .progress-toggle:hover, .progress-toggle:focus-visible { background: var(--accent-bg); }
  .progress-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
  .chevron { display: inline-grid; place-items: center; transition: transform .15s; }
  .chevron :global(svg) { width: 14px; height: 14px; }
  .chevron.open { transform: rotate(180deg); }
  .book-actions { display: flex; align-items: center; gap: 2px; flex-shrink: 0; }
  .ui-icon-btn.running { cursor: default; }
  .spin.small { width: 16px; height: 16px; border-width: 2px; }
  .meters { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px 14px; margin-top: 4px; }
  .meter { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
  .meter-label { color: var(--text-2); font-size: var(--fs-3xs); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .track { width: 100%; height: 5px; background: var(--border); border-radius: 3px; overflow: hidden; }
  .fill { height: 100%; background: var(--accent); }
  .fill.checked { background: var(--pass); }
  .fill.reviewed { background: var(--accent); }
  .fill.aligned { background: var(--align); }
  .fill.language-qa { background: var(--lqa); }

  /* Report */
  .report-title { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 8px; min-width: 0; }
  .title-dot { color: var(--text-3); font-size: var(--fs-sm); }
  .report-book { display: flex; align-items: baseline; gap: 6px; min-width: 0; font-weight: 650; color: var(--text); font-size: var(--fs-sm); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .book-code { color: var(--text-2); font-size: var(--fs-3xs); font-weight: 600; }
  .built-at { color: var(--text-3); font-size: var(--fs-3xs); white-space: nowrap; }
  .report-actions { display: flex; align-items: center; gap: 4px; }
  .ui-icon-btn.rebuild { color: var(--accent); }
  .report-state.job { max-width: 640px; width: 100%; }
  .job-head { display: flex; align-items: center; gap: 12px; }
  .job-copy { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .job-copy .state-hint { margin: 0; }
  .job-track { width: 100%; height: 8px; border-radius: 4px; background: var(--border); overflow: hidden; }
  .job-fill { height: 100%; background: var(--accent); transition: width .3s linear; }
  .job-fill.indeterminate { width: 40%; animation: slide 1.2s ease-in-out infinite; }
  @keyframes slide { from { transform: translateX(-100%); } to { transform: translateX(250%); } }
  .report-state { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; max-width: 560px; padding: 14px 6px; }
  .state-icon { display: grid; place-items: center; width: 40px; height: 40px; border-radius: 12px; background: var(--accent-bg); color: var(--accent); margin-bottom: 4px; }
  .state-title { margin: 0; font-size: var(--fs-sm); font-weight: 600; color: var(--text); overflow-wrap: anywhere; }
  .state-title.danger { color: var(--danger); }
  .state-hint { margin: 0 0 6px; color: var(--text-2); font-size: var(--fs-2xs); line-height: 1.55; }
  .state-actions { display: flex; flex-wrap: wrap; gap: 8px; }
  .legend { display: flex; flex-direction: column; gap: 8px; margin: 2px 0 6px; padding: 0; list-style: none; }
  .legend li { display: flex; align-items: center; gap: 10px; font-size: var(--fs-2xs); color: var(--text-2); }
  .legend strong { color: var(--text); font-weight: 650; }
  .legend-icon { display: grid; place-items: center; flex-shrink: 0; width: 30px; height: 30px; border-radius: 8px; }
  .legend-icon.success { background: var(--success-bg); color: var(--success); }
  .legend-icon.accent { background: var(--accent-bg); color: var(--accent); }
  .spin { width: 22px; height: 22px; border: 3px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin .9s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .report-area { max-width: 960px; }
  .gate { display: flex; align-items: center; gap: 8px; border-radius: 10px; padding: 10px 14px; font-size: var(--fs-xs); font-weight: 600; line-height: 1.45; background: var(--danger-bg); color: var(--danger); margin-bottom: 12px; }
  .gate.ready { background: var(--pass-bg); color: var(--pass); }
  .gate.unchecked { background: var(--surface-2); color: var(--text-2); border: 1px solid var(--border); }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(118px, 1fr)); gap: 8px; margin-bottom: 12px; }
  .tile { display: flex; flex-direction: column; gap: 2px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }
  .tile-value { font-size: var(--fs-xl); font-weight: 700; color: var(--text); line-height: 1.2; font-variant-numeric: tabular-nums; }
  .tile-label { color: var(--text-2); font-size: var(--fs-3xs); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .tile.danger .tile-value { color: var(--danger); }
  .tile.warning .tile-value { color: var(--warning); }
  .tile.accent .tile-value { color: var(--accent); }
  .coverage { padding: 12px 14px; border: 1px solid var(--border); border-radius: 10px; margin-bottom: 12px; }
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
  /* Stays at the top of the card while a long queue scrolls under it. */
  .queue-head { position: sticky; top: -12px; z-index: 1; display: flex; flex-wrap: wrap; align-items: center; gap: 8px 10px; margin: 0 -2px 8px; padding: 10px 2px 8px; background: var(--surface); }
  h3 { margin: 0; font-size: var(--fs-sm); font-weight: 650; color: var(--text); }
  .filters { display: flex; flex-wrap: wrap; gap: 4px; margin-left: auto; }
  .chapter-control { position: relative; }
  .chapter-button { display: inline-flex; align-items: center; height: 28px; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface); overflow: hidden; }
  .chapter-button.chosen { border-color: var(--accent); background: var(--accent-bg); }
  .chapter-pick { display: inline-flex; align-items: center; gap: 4px; height: 100%; padding: 0 6px 0 10px; border: 0; background: transparent; color: var(--text); font: inherit; font-size: var(--fs-3xs); font-weight: 600; cursor: pointer; white-space: nowrap; }
  .chosen .chapter-pick { color: var(--accent); }
  .chapter-pick :global(svg) { width: 14px; height: 14px; }
  .chapter-clear { display: grid; place-items: center; width: 26px; height: 100%; padding: 0; border: 0; border-left: 1px solid var(--accent-bg); background: transparent; color: var(--accent); cursor: pointer; }
  .chapter-clear :global(svg) { width: 13px; height: 13px; }
  .chapter-clear:hover, .chapter-clear:focus-visible { background: var(--accent); color: #fff; }
  .chapter-pick:focus-visible, .chapter-clear:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .chapter-menu { position: absolute; z-index: var(--z-dropdown); left: 0; top: calc(100% + 6px); width: 232px; display: flex; flex-direction: column; gap: 8px; padding: 10px; border: 1px solid var(--border-strong); border-radius: 10px; background: var(--surface); box-shadow: 0 10px 25px rgba(25, 35, 55, .16); }
  .chapter-search { height: 30px; padding: 0 10px; box-sizing: border-box; border: 1px solid var(--border-strong); border-radius: 7px; background: var(--surface); font: inherit; font-size: var(--fs-3xs); color: var(--text); outline: none; }
  .chapter-search:focus { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-bg); }
  .chapter-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 4px; max-height: 176px; overflow-y: auto; overscroll-behavior: contain; }
  .chapter-option { height: 30px; border: 1px solid var(--border); border-radius: 7px; background: var(--surface); color: var(--text); font: inherit; font-size: var(--fs-3xs); font-weight: 600; cursor: pointer; }
  .chapter-option:hover { border-color: var(--accent); color: var(--accent); }
  .chapter-option[aria-selected="true"] { border-color: var(--accent); background: var(--accent); color: #fff; }
  .chapter-option:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
  .chapter-none { grid-column: 1 / -1; padding: 6px 2px; color: var(--text-3); font-size: var(--fs-3xs); }
  .filter { border: 1px solid transparent; cursor: pointer; font: inherit; font-size: var(--fs-3xs); font-weight: 700; opacity: .75; }
  .filter:hover, .filter[aria-pressed="true"] { opacity: 1; }
  .filter[aria-pressed="true"] { border-color: currentColor; }
  .filter:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
  .exceptions { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
  .exceptions .empty { border-radius: 0; }
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
  .pill.invalid, .pill.alignment { background: var(--align-bg); color: var(--align); }
  .pill.engine { background: var(--accent-bg); color: var(--accent); text-transform: capitalize; }
  /* Same finding-source legend as the verse underlines and the review panel
     (index.css mark.m-*): Greek Room red, tN green, tW teal. */
  .pill.tn { background: var(--tn-bg); color: var(--tn); }
  .pill.tw { background: var(--tw-bg); color: var(--tw); }
  .expand-toggle { display: inline-flex; align-items: center; gap: 4px; flex-shrink: 0; align-self: center; margin-right: 10px; padding: 2px 6px 2px 9px; border-radius: 999px; border: 0; background: var(--accent-bg); color: var(--accent); font: inherit; font-size: var(--fs-3xs); font-weight: 700; cursor: pointer; }
  .expand-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
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
    .queue-head { position: static; }
  }
  @media (max-width: 640px) {
    .screen { padding: 12px; gap: 10px; }
    .header { padding: 12px 14px; }
    .card-head, .card-body { padding-left: 12px; padding-right: 12px; }
    .book-row { flex-wrap: wrap; }
    .book-actions { width: 100%; justify-content: flex-end; padding-top: 6px; border-top: 1px solid var(--border); }
    .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
  @media (max-height: 700px) {
    .screen { padding-top: 10px; gap: 10px; }
    .header { padding: 10px 18px; gap: 8px; }
    .qa-bar { padding-top: 8px; }
    h1 { font-size: var(--fs-xl); }
  }
  @media (prefers-reduced-motion: reduce) {
    .project-report-btn { transition: none; }
    .project-report-btn:hover, .project-report-btn:focus-visible, .project-report-btn:active { transform: none; }
    .book-row, .chevron { transition: none; }
    .spin { animation: none; }
    .job-fill { transition: none; animation: none; width: 100%; }
  }
</style>
