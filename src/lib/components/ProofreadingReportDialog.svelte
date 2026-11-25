<script lang="ts">
  /** The proofreading report (#505): what the run found, book by book. The
   *  summary comes from proofreading.report, which reads only each book's
   *  recorded run and so answers at once for a whole Bible; a book's rows are
   *  fetched when it is picked. Reading only: nothing here applies a finding
   *  or writes anything but the export file the reviewer asks for. */
  import { onMount } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";
  import { compactCount } from "../proofreading";
  import type {
    ProofreadingReport, ProofreadingReportBook, ProofreadingRow, ProofreadingRows,
  } from "../types/proofreading";

  export let projectName = "";
  export let onClose: () => void;

  const SEVERITIES = ["High", "Medium", "Low"] as const;

  let report: ProofreadingReport | null = null;
  let error = "";
  let loading = true;
  let selected = "";
  let rows: ProofreadingRows | null = null;
  let rowsLoading = false;
  let rowsFor = 0;
  let severity = "";
  let issueType = "";
  let search = "";
  let notice = "";
  let exporting = false;

  let openedFrom: Element | null = null;
  onMount(() => {
    openedFrom = document.activeElement;
    void load();
    return () => { if (openedFrom instanceof HTMLElement && openedFrom.isConnected) openedFrom.focus(); };
  });

  async function load(): Promise<void> {
    try {
      report = await bridge.proofreadingReport();
      const first = report.books.find((book) => book.state === "done" && (book.findings ?? 0) > 0)
        ?? report.books.find((book) => book.state === "done");
      if (first) void pick(first.bookId);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  async function pick(bookId: string): Promise<void> {
    selected = bookId;
    rows = null;
    severity = "";
    issueType = "";
    search = "";
    rowsLoading = true;
    const ticket = ++rowsFor;
    try {
      const loaded = await bridge.proofreadingRows(bookId);
      if (ticket === rowsFor) rows = loaded;
    } catch (e) {
      if (ticket === rowsFor) error = e instanceof Error ? e.message : String(e);
    } finally {
      if (ticket === rowsFor) rowsLoading = false;
    }
  }

  function onWindowKeydown(event: KeyboardEvent): void {
    if (event.key === "Escape" && !event.defaultPrevented) { event.preventDefault(); onClose(); }
  }

  $: readBooks = (report?.books ?? []).filter((book) => book.state === "done");
  $: book = readBooks.find((b) => b.bookId === selected) ?? null;
  $: issueTypes = Array.from(new Set((rows?.rows ?? []).map((row) => row.issueType))).sort();
  $: needle = search.trim().toLowerCase();
  $: shown = (rows?.rows ?? []).filter((row) =>
    (!severity || row.severity === severity)
    && (!issueType || row.issueType === issueType)
    && (!needle || [row.original, row.suggested, row.explanation, row.referenceNote, `${row.chapter}:${row.verse}`]
      .some((text) => text.toLowerCase().includes(needle))));

  function count(of: ProofreadingReportBook, name: (typeof SEVERITIES)[number]): number {
    return of.bySeverity?.[name] ?? 0;
  }

  function place(row: ProofreadingRow): string {
    return row.chapter.toLowerCase() === "intro" ? "Intro" : `${row.chapter}:${row.verse}`;
  }

  function tone(name: string): string {
    return name === "High" ? "danger" : name === "Medium" ? "warning" : "";
  }

  function usageLine(): string {
    const usage = report?.usage ?? {};
    if (!usage.calls) return "";
    const parts = [`${usage.calls.toLocaleString()} requests`, `${compactCount(usage.totalTokens)} tokens`];
    if (usage.estimatedCostUSD) parts.push(`about $${usage.estimatedCostUSD.toFixed(2)} (estimate)`);
    return parts.join(" · ");
  }

  async function exportCsv(onlyThisBook: boolean): Promise<void> {
    if (exporting) return;
    exporting = true;
    notice = "";
    try {
      const stem = (projectName || "project").replace(/[^\p{L}\p{N}_-]+/gu, "-");
      const name = onlyThisBook && selected ? `${stem}-${selected.toUpperCase()}-proofreading.csv` : `${stem}-proofreading.csv`;
      const path = await bridge.pickSavePath(name);
      if (!path) return;
      const format = path.toLowerCase().endsWith(".tsv") ? "tsv" : "csv";
      const written = await bridge.proofreadingExport(path, format, onlyThisBook && selected ? [selected] : null);
      notice = `Exported ${written.rows.toLocaleString()} findings to ${written.path}`;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      exporting = false;
    }
  }

  async function open(path: string | undefined): Promise<void> {
    if (!path) return;
    try {
      await bridge.openPath(path);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  }
</script>

<svelte:window on:keydown={onWindowKeydown} />

<div class="overlay">
  <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="proofreading-report-title">
    <header class="top">
      <div class="heading">
        <h2 id="proofreading-report-title">Proofreading report{projectName ? ` · ${projectName}` : ""}</h2>
        {#if report}<p class="note">{report.note}</p>{/if}
      </div>
      <div class="top-actions">
        {#if report?.files.runReport}
          <button type="button" class="ui-btn quiet" use:tooltip={"Open the toolkit's run workbook: by book, chapter, verse and issue type"}
            on:click={() => open(report?.files.runReport)}><UiIcon name="viewReport" />Excel report</button>
        {/if}
        <button type="button" class="ui-btn quiet" disabled={exporting || !readBooks.length}
          use:tooltip={"Save every book's findings as one CSV file"} on:click={() => exportCsv(false)}>
          <UiIcon name="export" />Export CSV</button>
        <button type="button" class="ui-icon-btn" aria-label="Close" on:click={onClose}><UiIcon name="close" /></button>
      </div>
    </header>

    {#if error}<p class="error" role="alert">{error}</p>{/if}
    {#if notice}<p class="notice" role="status">{notice}</p>{/if}

    {#if loading}
      <p class="empty">Loading the report…</p>
    {:else if report}
      <div class="tiles">
        <div class="tile"><span class="value">{report.booksRead}<small> / {report.totalBooks}</small></span><span class="label">books proofread</span></div>
        <div class="tile"><span class="value">{report.findings.toLocaleString()}</span><span class="label">findings</span></div>
        {#each SEVERITIES as name}
          <div class="tile {tone(name)}"><span class="value">{(report.bySeverity[name] ?? 0).toLocaleString()}</span><span class="label">{name}</span></div>
        {/each}
        {#if usageLine()}<div class="tile wide"><span class="value small">{usageLine()}</span><span class="label">AI use, all books read</span></div>{/if}
      </div>

      <div class="body">
        <nav class="books" aria-label="Books proofread">
          {#each report.books as item (item.bookId)}
            {#if item.state === "done"}
              <button type="button" class="book" class:current={item.bookId === selected} aria-current={item.bookId === selected ? "true" : undefined}
                on:click={() => pick(item.bookId)}>
                <span class="book-name">{item.bookName || item.bookId.toUpperCase()}</span>
                <span class="book-counts">
                  {#if count(item, "High")}<span class="pill danger">{count(item, "High")}</span>{/if}
                  {#if count(item, "Medium")}<span class="pill warning">{count(item, "Medium")}</span>{/if}
                  <span class="pill">{(item.findings ?? 0).toLocaleString()}</span>
                </span>
              </button>
            {:else}
              <div class="book not-run"><span class="book-name">{item.bookName || item.bookId.toUpperCase()}</span><span class="muted">not read</span></div>
            {/if}
          {/each}
        </nav>

        <section class="rows" aria-label="Findings">
          {#if !book}
            <p class="empty">{readBooks.length ? "Pick a book on the left to see its findings." : "No book has been proofread yet."}</p>
          {:else}
            <div class="book-head">
              <div>
                <h3>{book.bookName || book.bookId.toUpperCase()}</h3>
                <p class="muted">
                  {(book.findings ?? 0).toLocaleString()} findings{#if book.completedAt} · read {new Date(book.completedAt).toLocaleString()}{/if}{#if book.reference} · against {book.reference}{/if}{#if book.model} · {book.model}{/if}
                </p>
                <p class="muted">
                  The reader reported {book.reported ?? 0}; {book.unplaced ?? 0} could not be found in the text and {book.overlapping ?? 0} overlapped another, so they were not kept.
                  {#if book.hasReference === false}No reference text was available for this book.{/if}
                  {#each book.notes ?? [] as line}{" "}{line}{/each}
                </p>
              </div>
              <div class="book-actions">
                {#if rows?.files.workbook}
                  <button type="button" class="ui-btn small" on:click={() => open(rows?.files.workbook)}>Open workbook</button>
                {/if}
                <button type="button" class="ui-btn small" disabled={exporting} on:click={() => exportCsv(true)}>Export this book</button>
              </div>
            </div>
            <div class="filters">
              <select bind:value={severity} aria-label="Severity">
                <option value="">Every severity</option>
                {#each SEVERITIES as name}<option value={name}>{name}</option>{/each}
              </select>
              <select bind:value={issueType} aria-label="Issue type">
                <option value="">Every issue type</option>
                {#each issueTypes as name}<option value={name}>{name}</option>{/each}
              </select>
              <input type="search" bind:value={search} placeholder="Find in the findings" aria-label="Find in the findings" />
              <span class="muted shown">{shown.length.toLocaleString()} of {(rows?.rows.length ?? 0).toLocaleString()}</span>
            </div>
            {#if rowsLoading}
              <p class="empty">Loading the findings…</p>
            {:else if !shown.length}
              <p class="empty">{rows?.rows.length ? "No finding matches these filters." : "The run found nothing to report in this book."}</p>
            {:else}
              <div class="table-wrap">
                <table>
                  <thead><tr><th>Where</th><th>Severity</th><th>Issue</th><th>Text and proposal</th><th>Why</th></tr></thead>
                  <tbody>
                    {#each shown as row (row.id)}
                      <tr>
                        <td class="where">{place(row)}{#if row.location && row.location !== "Verse text"}<span class="muted block">{row.location}</span>{/if}</td>
                        <td><span class="pill {tone(row.severity)}">{row.severity}</span><span class="muted block">{row.confidence}</span></td>
                        <td>{row.issueType}{#if row.decisionNeeded && row.decisionNeeded !== "No"}<span class="muted block">decision: {row.decisionNeeded}</span>{/if}</td>
                        <td class="text">
                          <span class="original">{row.original}</span>
                          {#if row.suggested}<span class="suggested"><span class="arrow" aria-hidden="true">→</span>{row.suggested}</span>{/if}
                        </td>
                        <td class="why">{row.explanation}{#if row.referenceNote}<span class="muted block">{row.referenceNote}</span>{/if}</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {/if}
          {/if}
        </section>
      </div>
    {/if}
  </div>
</div>

<style>
  .overlay { position: fixed; inset: 0; background: rgba(15, 20, 26, 0.45); display: flex; align-items: center; justify-content: center; z-index: var(--z-dialog); }
  .dialog { width: min(1180px, calc(100% - 32px)); height: min(820px, calc(100% - 32px)); display: flex; flex-direction: column; gap: 12px; padding: 18px 22px; border-radius: 14px; background: var(--surface); box-shadow: 0 16px 40px rgba(25, 35, 55, .25); }
  .top { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; flex-shrink: 0; }
  .heading { min-width: 0; }
  h2 { margin: 0; font-size: var(--fs-lg); color: var(--text); overflow-wrap: anywhere; }
  h3 { margin: 0; font-size: var(--fs-md); color: var(--text); }
  .note, .muted { margin: 2px 0 0; color: var(--text-2); font-size: var(--fs-3xs); line-height: 1.45; }
  .block { display: block; margin-top: 2px; }
  .top-actions { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
  .ui-btn.quiet { color: var(--accent); }
  .ui-btn.quiet:hover:not(:disabled) { border-color: transparent; }
  .error { margin: 0; color: var(--danger); font-size: var(--fs-2xs); }
  .notice { margin: 0; color: var(--pass); font-size: var(--fs-2xs); overflow-wrap: anywhere; }
  .empty { margin: 24px 0; text-align: center; color: var(--text-2); font-size: var(--fs-xs); }
  .tiles { display: flex; flex-wrap: wrap; gap: 8px; flex-shrink: 0; }
  .tile { min-width: 96px; padding: 8px 12px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-2); display: flex; flex-direction: column; gap: 2px; }
  .tile.wide { flex: 1 1 220px; }
  .tile .value { font-size: var(--fs-xl); font-weight: 650; color: var(--text); line-height: 1.2; }
  .tile .value small { font-size: var(--fs-2xs); font-weight: 500; color: var(--text-2); }
  .tile .value.small { font-size: var(--fs-xs); font-weight: 600; }
  .tile .label { font-size: var(--fs-3xs); color: var(--text-2); }
  .tile.danger .value { color: var(--danger); }
  .tile.warning .value { color: var(--warning); }
  .body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(200px, 250px) minmax(0, 1fr); gap: 14px; }
  .books { min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 2px; padding-right: 4px; border-right: 1px solid var(--border); }
  .book { display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; padding: 7px 10px; border: 0; border-radius: 8px; background: transparent; color: var(--text); font: inherit; font-size: var(--fs-2xs); text-align: left; cursor: pointer; }
  .book:hover { background: var(--accent-bg); }
  .book.current { background: var(--accent-bg); color: var(--accent); font-weight: 650; }
  .book.not-run { cursor: default; color: var(--text-3); }
  .book.not-run:hover { background: transparent; }
  .book-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .book-counts { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
  .pill { display: inline-block; padding: 1px 7px; border-radius: 999px; background: var(--border); color: var(--text-2); font-size: var(--fs-3xs); font-weight: 600; white-space: nowrap; }
  .pill.danger { background: var(--danger-bg); color: var(--danger); }
  .pill.warning { background: var(--warning-bg); color: var(--warning); }
  .rows { min-width: 0; min-height: 0; display: flex; flex-direction: column; gap: 10px; }
  .book-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-shrink: 0; }
  .book-actions { display: flex; gap: 6px; flex-shrink: 0; }
  .filters { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; flex-shrink: 0; }
  select, input[type="search"] { height: 32px; padding: 0 10px; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface); color: var(--text); font: inherit; font-size: var(--fs-2xs); }
  input[type="search"] { flex: 1 1 180px; min-width: 0; }
  .shown { margin: 0 0 0 auto; white-space: nowrap; }
  .table-wrap { flex: 1; min-height: 0; overflow: auto; border: 1px solid var(--border); border-radius: 10px; }
  table { width: 100%; border-collapse: collapse; font-size: var(--fs-2xs); }
  th { position: sticky; top: 0; z-index: 1; padding: 8px 10px; background: var(--surface-2); border-bottom: 1px solid var(--border); color: var(--text-2); font-size: var(--fs-3xs); font-weight: 650; text-align: left; white-space: nowrap; }
  td { padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: top; color: var(--text); line-height: 1.45; }
  tr:last-child td { border-bottom: 0; }
  .where { white-space: nowrap; font-weight: 650; }
  .text { min-width: 180px; max-width: 320px; overflow-wrap: anywhere; }
  .original { display: block; }
  .suggested { display: block; margin-top: 3px; color: var(--pass); }
  .arrow { margin-right: 5px; color: var(--text-3); }
  .why { min-width: 220px; overflow-wrap: anywhere; }
  @media (max-width: 900px) { .body { grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(90px, 30%) minmax(0, 1fr); } .books { border-right: 0; border-bottom: 1px solid var(--border); } }
</style>
