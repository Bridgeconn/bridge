<script lang="ts">
  import PanelHeader from "./PanelHeader.svelte";
  import { onDestroy } from "svelte";
  import { revealFinding } from "../findingFocus";
  import { bridge } from "../api/bridgeClient";
  import { languageQaChannel, nudgeLanguageQa } from "../languageQaInline";
  import { languageQaPanelToggle } from "../languageQaPanelUi";
  import { SIDE_PANEL_LIMITS, setSidePanel, toggleSidePanel } from "../editorPrefs";
  import PanelResizeHandle from "./PanelResizeHandle.svelte";
  import type { BookWordRow, LanguageQaFlag, LanguageQaStatus, LanguageQaView, LearnedFix } from "../types/languageQa";
  import type { HouseStyleEntry } from "../types/houseStyle";
  import { addProjectWords } from "../projectWords";
  import { deleteFlag, setFlagStatus, publishBookFlags, recordFlagCheck } from "../flags";
  import type { AiReviewImportPreview } from "../types/languageQa";
  import LanguageQaHistoryList from "./LanguageQaHistoryList.svelte";
  import type { VerseHistoryEntry } from "../types/finding";
  import { graphemeDiff } from "../utils/unicodeDiff";
  import { LANGUAGE_QA_CATEGORY_LABELS, LANGUAGE_QA_CATEGORY_MARKS } from "../utils/highlight";
  import {
    focusedFindingId, chapterVerseNums, currentChapter, languageQaFindingsByVerse, project, selectedVerse, targetLang,
    verseKey,
  } from "../stores";
  import { editingChapter } from "../verseEditor";
  import type { LanguageQaCategory, LanguageQaFinding } from "../types/languageQa";

  export let projectPath: string;
  export let onNavigate: (book: string, chapter: string, verse: string) => void | Promise<void>;
  /** The editor screen has a status-bar button that opens this panel, so
   * there the launcher may step aside: it hides itself a few seconds after
   * a pass completes, or at once from its close button, and comes back when
   * the next pass starts. Elsewhere it is the only way in and always shows. */
  export let launcherHides = false;
  /** In the editor's side-panel column (SidePanel "languageQa", Benz
   * 2026-10-09): always open, no launcher, no floating box; Close closes
   * the column. Elsewhere (dashboard, report) it floats as before. */
  export let docked = false;
  $: if (docked) expanded = true;

  // #389 step 1: the floating box (dashboard, report) closes by its left
  // edge exactly as a docked column does, through the same handle. Its width
  // is this session's; the column's saved width is the column's.
  const FLOAT_LIMITS = SIDE_PANEL_LIMITS.languageQa;
  let floatWidth = 560;
  let floatPreview: number | null = null;
  let floatClosing = false;
  let floatWindowWidth = typeof window === "undefined" ? 1366 : window.innerWidth;
  $: floatMax = Math.max(FLOAT_LIMITS.min, Math.min(FLOAT_LIMITS.max, floatWindowWidth - 32));
  $: shownFloatWidth = Math.min(floatPreview ?? floatWidth, floatMax);

  let expanded = false;
  const LAUNCHER_HIDE_MS = 6000;
  let launcherHidden = false;
  let launcherTimer: ReturnType<typeof setTimeout> | undefined;
  let launcherKey = "";
  // Each poll publishes a fresh status object, so the reactive call below
  // runs on every poll; only a change of these four restarts the clock.
  let launcherGeneration: number | null = null;
  function trackLauncher(hides: boolean, state: string, open: boolean, failed: boolean,
                        generation: number | null = null): void {
    const key = `${hides}|${state}|${open}|${failed}|${generation}`;
    if (key === launcherKey) return;
    launcherKey = key;
    stopLauncherTimer();
    if (generation !== launcherGeneration) {
      // A pass the launcher has not shown yet, however quickly it finished.
      launcherGeneration = generation;
      launcherHidden = false;
    }
    if (!hides || failed || state !== "completed") {
      launcherHidden = false;
      return;
    }
    if (!open && !launcherHidden) launcherTimer = setTimeout(() => (launcherHidden = true), LAUNCHER_HIDE_MS);
  }
  function stopLauncherTimer(): void {
    if (launcherTimer) clearTimeout(launcherTimer);
    launcherTimer = undefined;
  }
  function hideLauncher(): void {
    stopLauncherTimer();
    launcherHidden = true;
  }
  // The status bar's button: every press after mount toggles the panel.
  let seenToggle: number | null = null;
  const stopToggle = languageQaPanelToggle.subscribe((count) => {
    if (seenToggle !== null && count !== seenToggle) {
      if (docked) toggleSidePanel("languageQa");
      else toggle();
    }
    seenToggle = count;
  });
  // Which list is paged: every open finding; those shown again because the
  // rule changed since they were ignored; or those marked as false positives.
  let view: LanguageQaView = "findings";
  // Which part of the book the list covers, and which kinds it shows (the
  // legend; none ticked = every kind).
  type ListScope = "verse" | "chapter" | "book";
  let listScope: ListScope = "book";
  let shownCategories: string[] = [];
  let verseList: LanguageQaFinding[] = [];
  // F8 / Shift+F8: where the walk stands, said for screen readers.
  let walkStatus = "";
  let pendingStep: { chapter: string; step: 1 | -1 } | null = null;
  // The panel's own tabs. "findings" holds the three engine lists above; the
  // others are the reviewer's own data (learned fixes in Dictionary).
  type PanelTab = "findings" | "bookWords" | "flags" | "edits" | "dictionary";
  let panelTab: PanelTab = "findings";
  let learned: LearnedFix[] = [];
  let learnedOn = true;
  let learnedLoaded = false;
  let learnedBusy = false;
  let learnedError = "";
  // Book words: the book's words outside the dictionary (last pass).
  // #385: the tab is named for the open book ("Words in Genesis") so it says
  // which book it lists as the reviewer moves between books. The engine fills
  // bookName from the USFM \h or \toc2 header, else the English table; the
  // fallback here is the dashboard's: the code, upper-cased.
  $: bookLabel = $project?.bookName || ($project?.bookId ?? status?.book ?? "").toUpperCase() || "this book";
  let bookWords: BookWordRow[] = [];
  let bookWordsReason = "";
  let bookWordsLoaded = false;
  let bookWordsBusy = false;
  let bookWordsNotice = "";
  let ticked = new Set<string>();
  let tickAtLeast = 5;
  let wordScope: "book" | "project" = "book";
  // Dictionary: the project's own words (the pack's dictionary is never written).
  let projectWords: HouseStyleEntry[] = [];
  let flags: LanguageQaFlag[] = [];
  let flagsLoaded = false;
  let reviewImport: AiReviewImportPreview | null = null;
  let reviewFile = "";
  let reviewProject = "";
  let reviewBusy = false;
  let reviewNotice = "";
  let checkingFlag = "";
  let checkConclusion = "";
  let checkProject = "";
  let flagsError = "";
  let showResolved = false;
  $: listedFlags = showResolved ? flags : flags.filter((f) => f.status === "open");
  // Edits: the book's recorded Scripture edits, newest first, by day.
  let edits: VerseHistoryEntry[] = [];
  let editsTotal = 0;
  let editsLoaded = false;
  let editsError = "";
  $: editDays = groupByDay(edits);
  // Finding ids whose decision history is expanded.
  let historyOpen = new Set<string>();
  let offset = 0;
  let sequence = 0;
  let disposed = false;
  let busy = false;
  let localError = "";
  // The page on show while expanded, fetched on demand (see below).
  let page: LanguageQaStatus | null = null;
  // The coverage headings are bilingual only when the statement itself is
  // (Tamil); a profile pack's statement is English.
  $: tamilCoverage = Boolean(status?.coverage?.inScope?.some((row) => row.labelTa));
  const detectionLabels: Record<string, string> = {
    metadata: "Language supplied by the project.",
    "script-suggestion": "Language suggested from the script; the project has no declared language.",
    "metadata-conflict": "The project language and detected script disagree. Only common checks are enabled.",
    "mixed-script": "The sample contains mixed scripts. Only common checks are enabled.",
    undetermined: "The language could not be determined. Only common checks are enabled.",
  };

  // The panel does not poll. Its state and totals come from the one Language
  // QA status channel (languageQaInline.ts), which backs off when idle. It
  // fetches rows only while expanded, and only when there is something new to
  // show: it is opened, paged, switched to another list, or a new pass lands
  // (a changed generation or state). It never feeds the verse marks; those
  // come from languageQa.inline, unpaged.
  $: channel = $languageQaChannel.projectPath === projectPath ? $languageQaChannel : null;
  $: live = channel?.status ?? null;
  $: error = localError || channel?.error || "";
  $: trackLauncher(launcherHides, live?.state ?? "", expanded, Boolean(error), live?.generation ?? null);
  $: status = expanded ? (page ?? live) : live;
  $: scopeChapter = listScope === "book" ? "" : $currentChapter;
  $: pageKey = expanded && live && listScope !== "verse"
    ? `${view}|${offset}|${live.generation}|${live.state}|${scopeChapter}|${shownCategories.join(",")}` : "";
  // The state is part of the key: a pass publishes its findings under the
  // generation it started with, so the list read while it was queued (the
  // previous pass's findings) must be read again once it completes (#237).
  $: verseKeyNow = expanded && live && listScope === "verse" && $selectedVerse
    ? `${live.generation}|${live.state}|${$currentChapter}|${$selectedVerse}` : "";
  $: if (verseKeyNow) void loadVerseList(verseKeyNow, $currentChapter, $selectedVerse ?? "");
  // The verse scope reads languageQa.verse; its kinds are counted here.
  $: verseCounts = verseList.reduce<Record<string, number>>((counts, f) => {
    if (f.category) counts[f.category] = (counts[f.category] ?? 0) + 1;
    return counts;
  }, {});
  $: legendCounts = listScope === "verse" ? verseCounts : (status?.categoryCounts ?? {});
  $: listed = listScope === "verse"
    ? verseList.filter((f) => !shownCategories.length || shownCategories.includes(f.category ?? ""))
    : (status?.findings ?? []);
  $: if (pageKey) void loadPage(pageKey);
  $: if (!expanded) page = null;

  async function loadPage(key: string): Promise<void> {
    const ticket = ++sequence;
    const path = projectPath;
    busy = true;
    try {
      const filters: { chapter?: string; categories?: string[] } = {};
      if (scopeChapter) filters.chapter = scopeChapter;
      if (shownCategories.length) filters.categories = shownCategories;
      const next = Object.keys(filters).length
        ? await bridge.languageQaStatus(path, offset, 50, view, filters)
        : await bridge.languageQaStatus(path, offset, 50, view);
      if (disposed || ticket !== sequence || key !== pageKey || next.projectPath !== path) return;
      if (page && next.generation !== page.generation && offset !== 0) {
        offset = 0;  // a new pass: start again from page one
        return;
      }
      page = next;
      localError = "";
    } catch (cause) {
      if (!disposed && ticket === sequence) localError = cause instanceof Error ? cause.message : String(cause);
    } finally {
      if (ticket === sequence) busy = false;
    }
  }

  async function togglePause(): Promise<void> {
    if (busy || !live) return;
    busy = true;
    const path = projectPath;
    try {
      const next = await bridge.languageQaPause(path, live.state !== "paused");
      if (disposed || projectPath !== path || next.projectPath !== path) return;
      languageQaChannel.set({ projectPath: path, status: { ...next, findings: [] }, error: "" });
      offset = 0;
      localError = "";
    } catch (cause) {
      localError = cause instanceof Error ? cause.message : String(cause);
    } finally {
      busy = false;
      nudgeLanguageQa();
    }
  }

  function toggle(): void {
    if (docked) {
      setSidePanel("languageQa", { open: false });
      return;
    }
    expanded = !expanded;
    offset = 0;
  }

  function turnPage(delta: number): void {
    offset = Math.max(0, offset + delta);
  }

  async function loadVerseList(key: string, chapter: string, verse: string): Promise<void> {
    try {
      const result = await bridge.languageQaVerse(projectPath, chapter, verse);
      if (!disposed && key === verseKeyNow) verseList = result.findings;
    } catch (cause) {
      if (!disposed) localError = cause instanceof Error ? cause.message : String(cause);
    }
  }

  function showScope(next: ListScope): void {
    listScope = next;
    offset = 0;
  }

  const markClass = (category: string): string =>
    LANGUAGE_QA_CATEGORY_MARKS[category as LanguageQaCategory] ?? "m-lqa-typo";
  const categoryLabel = (category: string): string =>
    LANGUAGE_QA_CATEGORY_LABELS[category as LanguageQaCategory] ?? category;

  function clearCategories(): void {
    shownCategories = [];
    offset = 0;
  }

  // The (i): what the checks cover and what they never do (DECISIONS
  // 2026-10-09). Closed by the (i) again, Escape, or a click elsewhere.
  let aboutOpen = false;
  let infoButton: HTMLButtonElement | null = null;
  let aboutBox: HTMLDivElement | null = null;
  let headHeight = 0;
  let tabsHeight = 0;
  // #376: the Kinds dropdown in the filter row, closed the same three ways.
  let kindsOpen = false;
  let kindsButton: HTMLButtonElement | null = null;
  let kindsBox: HTMLDivElement | null = null;

  // #376: the title's state word: "completed", "paused", "checking 12/50".
  $: stateWord = !status ? (error ? "unavailable" : "starting")
    : `${status.state}${(status.completedChapters ?? 0) < (status.totalChapters ?? 0)
      ? ` ${status.completedChapters ?? 0}/${status.totalChapters ?? 0}` : ""}`;

  function closeAbout(): void {
    aboutOpen = false;
    infoButton?.focus();
  }

  function onWindowPointerdown(event: PointerEvent): void {
    const target = event.target instanceof Node ? event.target : null;
    if (aboutOpen && !(target && (aboutBox?.contains(target) || infoButton?.contains(target)))) aboutOpen = false;
    if (kindsOpen && !(target && (kindsBox?.contains(target) || kindsButton?.contains(target)))) kindsOpen = false;
  }

  function toggleCategory(category: string): void {
    shownCategories = shownCategories.includes(category)
      ? shownCategories.filter((c) => c !== category) : [...shownCategories, category];
    offset = 0;
  }

  /** The marks of one chapter in reading order (the ones drawn in the text),
   * narrowed to the legend's kinds when any are ticked. */
  function chapterMarks(chapter: string): LanguageQaFinding[] {
    const marks: LanguageQaFinding[] = [];
    for (const verse of $chapterVerseNums[chapter] ?? []) {
      const found = ($languageQaFindingsByVerse[verseKey(chapter, verse)] ?? [])
        .filter((f) => !shownCategories.length || shownCategories.includes(f.category ?? ""));
      marks.push(...[...found].sort((a, b) => a.start - b.start || a.id.localeCompare(b.id)));
    }
    return marks;
  }

  async function goToMark(finding: LanguageQaFinding, index: number, total: number): Promise<void> {
    walkStatus = `Finding ${index + 1} of ${total} in chapter ${finding.chapter}: ${finding.originalText}`;
    // The one reveal route (#402): ring first, then select the verse, then
    // scroll the mark to the middle of the reader and flash it.
    await revealFinding(finding.id, { navigate: () => selectedVerse.set(finding.verse) });
  }

  /** A row's reference (#402): the verse opens, then the finding's mark is
   * ringed and scrolled into view. A heading, introduction or footnote
   * finding has no mark in the verse text, so the verse is simply opened. */
  async function openFinding(finding: LanguageQaFinding): Promise<void> {
    const navigate = () => onNavigate(finding.book, finding.chapter, finding.verse);
    if (finding.context) {
      await navigate();
      return;
    }
    await revealFinding(finding.id, { navigate });
  }

  /** F8: the next mark in reading order; Shift+F8: the previous. Past the end
   * of the chapter it opens the next (or previous) chapter, and lands on its
   * first (or last) mark when they arrive. */
  function step(direction: 1 | -1): void {
    const chapter = $currentChapter;
    const marks = chapterMarks(chapter);
    const at = marks.findIndex((f) => f.id === $focusedFindingId);
    const next = at === -1 ? (direction === 1 ? 0 : marks.length - 1) : at + direction;
    if (next >= 0 && next < marks.length) {
      pendingStep = null;
      void goToMark(marks[next], next, marks.length);
      return;
    }
    const chapters = $project?.chapters ?? [];
    const target = chapters[chapters.indexOf(chapter) + direction];
    if (!target) {
      walkStatus = direction === 1 ? "No more findings: this is the end of the book." : "No earlier findings: this is the start of the book.";
      return;
    }
    focusedFindingId.set(null);
    pendingStep = { chapter: target, step: direction };
    walkStatus = `Chapter ${target}…`;
    onNavigate(status?.book ?? $project?.bookId ?? "", target, "");
  }

  // A chapter F8 moved to: land on its first (or last) mark once they arrive.
  $: if (pendingStep && $currentChapter === pendingStep.chapter && $languageQaFindingsByVerse) {
    const marks = chapterMarks(pendingStep.chapter);
    if (marks.length) {
      const index = pendingStep.step === 1 ? 0 : marks.length - 1;
      pendingStep = null;
      void goToMark(marks[index], index, marks.length);
    }
  }

  function onWindowKeydown(event: KeyboardEvent): void {
    if (aboutOpen && event.key === "Escape") {
      closeAbout();
      return;
    }
    if (kindsOpen && event.key === "Escape") {
      kindsOpen = false;
      kindsButton?.focus();
      return;
    }
    if (event.key !== "F8" || event.ctrlKey || event.altKey || event.metaKey || !$project) return;
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest("input, textarea, select, [contenteditable='true']")) return;
    if ($editingChapter || document.querySelector("[role='dialog']")) return;
    event.preventDefault();
    step(event.shiftKey ? -1 : 1);
  }

  function showView(next: LanguageQaView): void {
    if (view === next) return;
    view = next;
    offset = 0;
  }

  function showPanelTab(next: PanelTab): void {
    panelTab = next;
    if (next === "dictionary") {
      void loadLearned();
      void loadProjectWords();
    }
    if (next === "bookWords") void loadBookWords();
    if (next === "flags") void loadFlags();
    if (next === "edits") void loadEdits();
  }

  async function loadEdits(): Promise<void> {
    editsError = "";
    try {
      const result = await bridge.verseHistory();
      edits = result.entries;
      editsTotal = result.total;
    } catch (cause) {
      editsError = cause instanceof Error ? cause.message : String(cause);
    } finally {
      editsLoaded = true;
    }
  }

  /** Entries are newest first already; each day keeps that order. */
  function groupByDay(entries: VerseHistoryEntry[]): { day: string; entries: VerseHistoryEntry[] }[] {
    const days: { day: string; entries: VerseHistoryEntry[] }[] = [];
    for (const entry of entries) {
      const day = new Date(entry.timestamp).toLocaleDateString();
      if (days.length && days[days.length - 1].day === day) days[days.length - 1].entries.push(entry);
      else days.push({ day, entries: [entry] });
    }
    return days;
  }

  async function loadBookWords(): Promise<void> {
    try {
      const result = await bridge.languageQaBookWords(projectPath);
      bookWords = result.words;
      bookWordsReason = result.ready ? "" : result.reason ?? "";
    } catch (cause) {
      bookWordsReason = cause instanceof Error ? cause.message : String(cause);
    } finally {
      bookWordsLoaded = true;
    }
  }

  /** indic-qa's "tick words used at least N times in the IRV". */
  function tickFrequent(): void {
    ticked = new Set(bookWords.filter((w) => w.status !== "added" && (w.countIrv ?? 0) >= tickAtLeast).map((w) => w.word));
  }

  function toggleTick(word: string): void {
    const next = new Set(ticked);
    if (!next.delete(word)) next.add(word);
    ticked = next;
  }

  async function addTicked(): Promise<void> {
    if (!ticked.size || bookWordsBusy) return;
    bookWordsBusy = true;
    const words = [...ticked];
    const error = await addProjectWords(words, wordScope, projectPath);
    bookWordsBusy = false;
    if (error) {
      bookWordsNotice = error;
      return;
    }
    bookWords = bookWords.map((w) => (ticked.has(w.word) ? { ...w, status: "added" } : w));
    bookWordsNotice = `${words.length} word${words.length === 1 ? "" : "s"} added to the dictionary.`;
    ticked = new Set();
  }

  async function loadProjectWords(): Promise<void> {
    try {
      projectWords = (await bridge.languageQaWordsList(projectPath)).added;
    } catch {
      projectWords = [];
    }
  }

  async function removeProjectWord(entry: HouseStyleEntry): Promise<void> {
    try {
      await bridge.housestyleSetState(entry.key, "removed");
      projectWords = projectWords.filter((e) => e.key !== entry.key);
      nudgeLanguageQa();
    } catch (cause) {
      learnedError = cause instanceof Error ? cause.message : String(cause);
    }
  }

  /** The whole book's flags, fetched when the tab opens. */
  async function loadFlags(): Promise<void> {
    const requestedPath = projectPath;
    flagsError = "";
    try {
      const result = await bridge.languageQaFlagsList(requestedPath);
      if (requestedPath !== projectPath) return;
      flags = result.flags;
      publishBookFlags(flags);
    } catch (cause) {
      flagsError = cause instanceof Error ? cause.message : String(cause);
    } finally {
      if (requestedPath === projectPath) flagsLoaded = true;
    }
  }

  async function previewReview(): Promise<void> {
    const requestedPath = projectPath;
    reviewImport = null;
    reviewNotice = "";
    flagsError = "";
    reviewBusy = true;
    try {
      const file = await bridge.pickJsonFile();
      if (!file || requestedPath !== projectPath) return;
      const preview = await bridge.languageQaReviewPreview(requestedPath, file);
      if (requestedPath !== projectPath) return;
      reviewFile = file;
      reviewProject = requestedPath;
      reviewImport = preview;
    } catch (cause) {
      if (requestedPath === projectPath) flagsError = cause instanceof Error ? cause.message : String(cause);
    } finally { reviewBusy = false; }
  }

  async function importReview(): Promise<void> {
    if (!reviewImport || reviewProject !== projectPath) return;
    const requestedPath = projectPath;
    reviewBusy = true;
    flagsError = "";
    try {
      const result = await bridge.languageQaReviewImport(requestedPath, reviewFile, reviewImport.sha256);
      if (requestedPath !== projectPath) return;
      reviewNotice = `Imported ${result.imported ?? 0} open questions. ${result.stale} changed verses skipped; ${result.existing} already imported.`;
      reviewImport = null;
      await loadFlags();
    } catch (cause) {
      if (requestedPath === projectPath) flagsError = cause instanceof Error ? cause.message : String(cause);
    } finally { reviewBusy = false; }
  }

  async function saveFlagCheck(flag: LanguageQaFlag, resolve = true): Promise<void> {
    if (checkProject !== projectPath) return;
    const error = await recordFlagCheck(projectPath, flag, checkConclusion, resolve);
    if (error) { flagsError = error; return; }
    checkingFlag = "";
    checkConclusion = "";
    await loadFlags();
  }

  async function flagAction(flag: LanguageQaFlag, action: "resolved" | "open" | "delete"): Promise<void> {
    const error = action === "delete" ? await deleteFlag(projectPath, flag) : await setFlagStatus(projectPath, flag, action);
    if (error) {
      flagsError = error;
      return;
    }
    flags = action === "delete" ? flags.filter((f) => f.flagId !== flag.flagId)
      : flags.map((f) => (f.flagId === flag.flagId ? { ...f, status: action } : f));
  }

  /** Fetched when the Dictionary tab opens, never polled. */
  async function loadLearned(): Promise<void> {
    learnedError = "";
    try {
      const result = await bridge.languageQaLearnedList(projectPath);
      learned = result.fixes;
      learnedOn = result.enabled;
    } catch (cause) {
      learnedError = cause instanceof Error ? cause.message : String(cause);
    } finally {
      learnedLoaded = true;
    }
  }

  async function setLearned(fix: LearnedFix, enabled: boolean): Promise<void> {
    if (learnedBusy) return;
    learnedBusy = true;
    learnedError = "";
    try {
      const { fix: updated } = enabled
        ? await bridge.languageQaLearnedRestore(projectPath, fix.old, fix.new)
        : await bridge.languageQaLearnedForget(projectPath, fix.old, fix.new);
      learned = learned.map((f) => (f.old === fix.old && f.new === fix.new ? updated : f));
      nudgeLanguageQa();
    } catch (cause) {
      learnedError = cause instanceof Error ? cause.message : String(cause);
    } finally {
      learnedBusy = false;
    }
  }

  function toggleHistory(id: string): void {
    const next = new Set(historyOpen);
    if (!next.delete(id)) next.add(id);
    historyOpen = next;
  }

  onDestroy(() => {
    disposed = true;
    ++sequence;
    stopLauncherTimer();
    stopToggle();
  });
</script>

<svelte:window on:keydown={onWindowKeydown} on:pointerdown={onWindowPointerdown} bind:innerWidth={floatWindowWidth} />

<aside class="language-qa" class:docked aria-label="Language QA">
  <p class="walk-status" role="status" aria-live="polite">{walkStatus}</p>
  {#if expanded}
    <div class="float-frame" class:closing={floatClosing}>
    {#if !docked}
      <PanelResizeHandle label="Language QA" width={shownFloatWidth} min={FLOAT_LIMITS.min} max={floatMax} initial={560}
        onPreview={(next, closing) => { floatPreview = next; floatClosing = closing; }}
        onCommit={(next) => (floatWidth = next)} onClose={toggle} />
    {/if}
    <section id="language-qa-results" aria-label="Language QA results" style:--head-h="{headHeight}px" style:--tabs-h="{tabsHeight}px"
      style:width={docked ? null : `${shownFloatWidth}px`}>
      <!-- The header stays put while the panel scrolls: title, the (i), Pause and
           Close, then one status line and, when a pass left text out, the warning. -->
      <div class="panel-head" bind:clientHeight={headHeight}>
        <!-- #379: the shared header bar; the (i) and Pause are this panel's
             actions, and Close does what the rail does (or folds the floating
             box). #376: the title carries the state word; everything else
             that used to be always visible is behind the (i), a popover that
             never changes the header's height. Errors and the one-line
             coverage warning stay in view. -->
        <PanelHeader id="languageQa" title={`Language QA · ${stateWord}`} label="Language QA" onClose={toggle} layout={docked}>
          <button type="button" class="info-btn" bind:this={infoButton} aria-label="About these checks"
            aria-expanded={aboutOpen} aria-controls="language-qa-about"
            title="What Language QA checks, and what it does not" on:click={() => (aboutOpen = !aboutOpen)}>i</button>
          {#if status}
            <button type="button" on:click={togglePause} disabled={busy || status.state === "failed"}
              aria-label={status.state === "paused" ? "Resume checks" : "Pause checks"}
              title={status.state === "paused" ? "Resume the checks" : "Pause the checks"}>
              {status.state === "paused" ? "Resume" : "Pause"}
            </button>
          {/if}
        </PanelHeader>
        <div class="head-meta">
        {#if error}<p class="alert" role="alert">{error}</p>{/if}
        {#if status?.error}<p class="alert" role="alert">{status.error}</p>{/if}
        {#if status?.incomplete}
          <p class="coverage-warn"><span class="notice">Coverage incomplete. Omitted text has not passed QA.</span>
            {#if status.limitations.length}<button type="button" class="link" on:click={() => (aboutOpen = true)}>details ({status.limitations.length})</button>{/if}</p>
        {/if}
        </div>
      {#if aboutOpen}
        <!-- Behind the (i) at Benz's request (DECISIONS 2026-10-09, superseding
             2026-09-24): what the checks cover, and what they never do; since
             #376 also the full status line, the list and key hints and the
             tabs' explanations. A popover anchored to the (i): it scrolls
             inside itself and never resizes the header. -->
        <div id="language-qa-about" class="about" role="dialog" aria-label="What Language QA checks"
          tabindex="-1" bind:this={aboutBox}>
          <div class="about-head">
            <h3>About Language QA</h3>
            <button type="button" class="about-close" aria-label="Close this note" on:click={closeAbout}>✕</button>
          </div>
          <p>Checks run offline, on this computer, automatically for the open book and after edits.</p>
          {#if status}
            <p class="status-line">
              {status.language?.name || status.language?.language || "Detecting language"}
              {#if status.language} · {status.language.script.toLowerCase()} script{/if}
              {#if status.language && status.language.pack !== "common"} · {status.language.pack} rules{/if}
              · {status.state} · {status.completedChapters ?? 0}/{status.totalChapters ?? 0} chapters
              · {status.totalFindings} review candidates
            </p>
          {/if}
          {#if status?.language}<p>{detectionLabels[status.language.basis] ?? ""}</p>{/if}
          {#if status}
            <p>{status.language?.message ?? (status.state === "paused" ? "Checks paused. Resume when ready." : "Preparing language checks…")}</p>
          {/if}
          {#if status?.coverage?.inScope}
          <div class="scope">
            <div>
              <h3>Checks{#if tamilCoverage} · <span lang="ta">சரிபார்ப்பவை</span>{/if}</h3>
              <ul>
                {#each status.coverage.inScope as row (row.category)}
                  <li>{row.label}{#if row.labelTa} · <span lang="ta">{row.labelTa}</span>{/if}</li>
                {/each}
              </ul>
            </div>
            <div>
              <h3>Does not check{#if tamilCoverage} · <span lang="ta">சரிபார்க்காதவை</span>{/if}</h3>
              <ul>
                {#each status.coverage.outOfScope as row (row.category)}
                  <li title={row.reason}>
                    {row.label}{#if row.labelTa} · <span lang="ta">{row.labelTa}</span>{/if}
                    <span class="reason">{row.reason}{#if row.reasonTa} <span lang="ta">{row.reasonTa}</span>{/if}</span>
                  </li>
                {/each}
              </ul>
            </div>
            <p class="muted">Who checks these before publication: {status.coverage.handOff}</p>
          </div>
          {/if}
          {#if status}<p class="muted">{status.coverage?.summary ?? ""} {status.storage}</p>{/if}
          <p class="muted">No candidates from the enabled checks is not publication approval.</p>
          {#if status?.limitations.length}
            <h3>Coverage details ({status.limitations.length})</h3>
            <ul class="limitations">{#each status.limitations as limitation}<li>{limitation}</li>{/each}</ul>
          {/if}
          <h3>Lists</h3>
          <ul>
            <li><b>Findings:</b> what the enabled checks found; Verse, Chapter or Book narrows the list.</li>
            <li><b>Re-check:</b> ignored before, under an older version of the rule. Check each one again.</li>
            <li><b>False positives:</b> marked as false positives and hidden from the verse text.</li>
          </ul>
          <p class="muted" aria-keyshortcuts="F8 Shift+F8">F8 / Shift+F8: next / previous mark in the text.</p>
          <h3>Tabs</h3>
          <ul>
            <li><b>Words in {bookLabel}:</b> words in the book that are not in the dictionary, most used first. Add the
              ones that are right to the dictionary; they stop being reported as spelling problems. Nothing here changes the text.</li>
            <li><b>Flags:</b> questions reviewers raised on the text (⚑). A flag never changes the verse.</li>
            <li><b>Edits:</b> every recorded change to this book's text, newest first. Open a verse's ↺ to restore an earlier wording.</li>
            <li><b>Dictionary:</b> words this project accepts, and fixes it learned: a word you replaced is offered again
              where it recurs, in this book and the project's other books (blue dotted); Forget applies to every book.
              The language pack's own dictionary is read-only.</li>
          </ul>
        </div>
      {/if}
      </div>
      {#if status}
        <div class="panel-tabs" role="tablist" aria-label="Language QA panel" bind:clientHeight={tabsHeight}>
          <button role="tab" aria-selected={panelTab === "findings"} on:click={() => showPanelTab("findings")}>Issues</button>
          <button role="tab" class="book-tab" aria-selected={panelTab === "bookWords"} title={`Words in ${bookLabel}`}
            on:click={() => showPanelTab("bookWords")}>Words in {bookLabel}</button>
          <button role="tab" aria-selected={panelTab === "flags"} on:click={() => showPanelTab("flags")}>Flags</button>
          <button role="tab" aria-selected={panelTab === "edits"} on:click={() => showPanelTab("edits")}>Edits</button>
          <button role="tab" aria-selected={panelTab === "dictionary"} on:click={() => showPanelTab("dictionary")}>Dictionary</button>
        </div>
        {#if panelTab === "findings"}
          <!-- #376: one filter row, pinned with the header and tabs (#178): the
               list switch, the scope, and Kinds as one dropdown. It wraps to a
               second line at the panel's minimum width, never a third. -->
          <div class="filter-bar list-row">
            <div class="views segmented" role="tablist" aria-label="Language QA lists">
              <button role="tab" aria-selected={view === "findings"} on:click={() => showView("findings")}>
                Findings ({live?.totalFindings ?? status.totalFindings})
              </button>
              <button role="tab" aria-selected={view === "recheck"} on:click={() => showView("recheck")}>
                Re-check ({status.recheckCount ?? 0})
              </button>
              <button role="tab" aria-selected={view === "falsePositives"} on:click={() => showView("falsePositives")}>
                False positives ({status.falsePositiveCount ?? 0})
              </button>
            </div>
            <div class="scope-row segmented" role="radiogroup" aria-label="Show findings for">
              {#each [["verse", "Verse"], ["chapter", "Chapter"], ["book", "Book"]] as [value, label]}
                <button role="radio" aria-checked={listScope === value} disabled={value === "verse" && view !== "findings"}
                  on:click={() => showScope(value === "verse" ? "verse" : value === "chapter" ? "chapter" : "book")}>{label}</button>
              {/each}
            </div>
            {#if Object.keys(legendCounts).length}
              <div class="kinds">
                <button type="button" class="kinds-btn" bind:this={kindsButton} aria-expanded={kindsOpen}
                  aria-controls="language-qa-kinds" aria-haspopup="true"
                  title={shownCategories.length ? "Narrowed to the kinds ticked" : "Every kind is shown; tick kinds to narrow the list"}
                  on:click={() => (kindsOpen = !kindsOpen)}>
                  Kinds · {shownCategories.length ? `${shownCategories.length} of ${Object.keys(legendCounts).length}` : Object.keys(legendCounts).length} ▾
                </button>
                {#if kindsOpen}
                  <div id="language-qa-kinds" class="legend" role="group" aria-label="Kinds of finding" bind:this={kindsBox}>
                    {#each Object.entries(legendCounts) as [category, count] (category)}
                      <button aria-pressed={shownCategories.includes(category)} on:click={() => toggleCategory(category)}
                        title={shownCategories.includes(category) ? "Shown; click to stop narrowing to it" : "Show only this kind (and any others ticked)"}>
                        <mark class="swatch {markClass(category)}">ab</mark>
                        {categoryLabel(category)}
                        <span class="n">{count}</span>
                      </button>
                    {/each}
                    {#if shownCategories.length}
                      <button type="button" class="link clear" on:click={clearCategories}>Clear</button>
                    {/if}
                  </div>
                {/if}
              </div>
            {/if}
          </div>
        {/if}
        <div class="panel-body">
        {#if panelTab === "findings"}
        {#if listScope === "verse" && !$selectedVerse}
          <p class="muted">Select a verse to list its findings.</p>
        {:else if listScope === "verse" && !listed.length}
          <p class="muted">No findings in this verse{shownCategories.length ? " of the kinds ticked" : ""}.</p>
        {/if}
        {#if listScope !== "verse" && view === "findings" && status.state === "completed" && !status.totalFindings}
          <p class="muted">No candidates found by the enabled checks.</p>
        {/if}
        <ol aria-label={view === "findings" ? "Language QA findings" : view === "recheck" ? "Findings to re-check" : "False positives"} start={listScope === "verse" ? 1 : status.offset + 1}>
          {#each listed as finding (finding.id)}
            <li>
              <button on:click={() => void openFinding(finding)}>
                {finding.book.toUpperCase()} {finding.chapter}:{finding.verse}
              </button>
              <span class="severity">{finding.severity}</span>
              {#if finding.category}<span class="category">{finding.category}</span>{/if}
              {#if finding.previouslyIgnored}<span class="recheck">Re-check</span>{/if}
              {#if finding.context}<span class="where">in {finding.context}</span>{/if}
              <p class="evidence" lang={$targetLang}>{finding.originalText}</p>
              {#if finding.context === "heading" && finding.contextText}<p class="muted">Heading: {finding.contextText}</p>{/if}
              {#if finding.context === "introduction" && finding.contextText}<p class="muted">Book introduction: {finding.contextText}</p>{/if}
              <p>{finding.message}</p>
              {#if finding.reference}
                <p class="reference"><b>{finding.reference.label} {finding.reference.ref}:</b> {finding.reference.text}</p>
              {/if}
              <button class="history-toggle" aria-expanded={historyOpen.has(finding.id)} on:click={() => toggleHistory(finding.id)}>
                History
              </button>
              {#if historyOpen.has(finding.id)}
                <LanguageQaHistoryList {projectPath} chapter={finding.chapter} verse={finding.verse} findingId={finding.id} />
              {/if}
            </li>
          {/each}
        </ol>
        {#if listScope !== "verse" && status.totalFindings > 50}
          <div class="paging">
            <button on:click={() => turnPage(-50)} disabled={busy || offset === 0}>Previous</button>
            <span>{status.offset + 1}–{Math.min(status.offset + 50, status.totalFindings)} of {status.totalFindings}</span>
            <button on:click={() => turnPage(50)} disabled={busy || offset + 50 >= status.totalFindings}>Next</button>
          </div>
        {/if}
        {:else if panelTab === "bookWords"}
          <section aria-label="Book words" class="book-words">
            <p class="muted">Words in {bookLabel} that are not in the dictionary, most used first.</p>
            {#if !bookWordsLoaded}
              <p class="muted">Loading…</p>
            {:else if bookWordsReason}
              <p class="muted">{bookWordsReason}</p>
            {:else if !bookWords.length}
              <p class="muted">No words outside the dictionary in this check.</p>
            {:else}
              <div class="tick-row">
                {#if bookWords.some((w) => w.countIrv !== null)}
                <label>Tick words used at least
                  <input type="number" min="1" bind:value={tickAtLeast} aria-label="Minimum uses in the IRV" /> times in the IRV</label>
                <button on:click={tickFrequent}>Tick</button>
                {/if}
                <button on:click={() => (ticked = new Set())}>Untick all</button>
              </div>
              <div class="table-box">
                <table>
                  <thead><tr><th></th><th>Word</th><th>In book</th><th>IRV</th><th>OV</th><th>Status</th></tr></thead>
                  <tbody>
                    {#each bookWords as row (row.word)}
                      <tr class:added={row.status === "added"}>
                        <td><input type="checkbox" aria-label={`Tick ${row.word}`} checked={ticked.has(row.word)}
                          disabled={row.status === "added"} on:change={() => toggleTick(row.word)} /></td>
                        <td class="word" lang={$targetLang}>
                          <button class="link" on:click={() => onNavigate(status?.book ?? "", row.firstRef.chapter, row.firstRef.verse)}
                            title="Open its first verse">{row.word}</button>
                        </td>
                        <td>{row.countBook}</td><td>{row.countIrv ?? "—"}</td><td>{row.countOv ?? "—"}</td>
                        <td>{row.status === "added" ? "in dictionary" : row.status === "irv_ok" ? "IRV word" : row.status}</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
              <div class="tick-row">
                <span class="muted">{ticked.size} ticked</span>
                <select bind:value={wordScope} aria-label="Where the words apply">
                  <option value="book">this book</option>
                  <option value="project">every book of the project</option>
                </select>
                <button on:click={addTicked} disabled={!ticked.size || bookWordsBusy}>Add to dictionary ({wordScope === "project" ? "every book" : "this book"})</button>
              </div>
              {#if bookWordsNotice}<p class="muted" role="status">{bookWordsNotice}</p>{/if}
            {/if}
          </section>
        {:else if panelTab === "flags"}
          <section aria-label="Flags" class="flags">
            <p class="muted">Reviewers' questions on the text (⚑).</p>
            <button on:click={previewReview} disabled={reviewBusy}>Import AI review…</button>
            {#if reviewBusy}<p role="status">Preparing review questions…</p>{/if}
            {#if reviewNotice}<p role="status">{reviewNotice}</p>{/if}
            {#if reviewImport && reviewProject === projectPath}
              <div role="region" aria-label="AI review import preview">
                <p>AI-assisted review — native confirmation pending.</p>
                <p>{reviewImport.ready} questions match this book. {reviewImport.existing} already imported;
                  {reviewImport.stale} have changed text; {reviewImport.otherScope} belong to other books or languages.</p>
                <p class="muted">Import creates open flags for checking in context. Proposed corrections stay in the notes.</p>
                <ul>{#each reviewImport.examples as example (example.id)}
                  <li>{example.chapter}:{example.verse} — {example.text}</li>
                {/each}</ul>
                <button on:click={importReview} disabled={reviewBusy || !reviewImport.ready}>Import {reviewImport.ready} questions</button>
                <button on:click={() => (reviewImport = null)} disabled={reviewBusy}>Cancel</button>
              </div>
            {/if}
            <label class="toggle"><input type="checkbox" bind:checked={showResolved} /> Show resolved</label>
            {#if flagsError}<p role="alert">{flagsError}</p>{/if}
            {#if !flagsLoaded}
              <p class="muted">Loading…</p>
            {:else if !listedFlags.length}
              <p class="muted">No {showResolved ? "" : "open "}flags in this book. Right-click a word or a verse to flag it.</p>
            {:else}
              <ol>
                {#each listedFlags as flag (flag.flagId)}
                  <li class:resolved={flag.status === "resolved"}>
                    <button on:click={() => onNavigate(status?.book ?? "", flag.chapter, flag.verse)}>
                      {(status?.book ?? "").toUpperCase()} {flag.chapter}:{flag.verse}{flag.verseEnd ? `–${flag.verseEnd}` : ""}
                    </button>
                    <span class="category">⚑ {flag.type}</span>
                    <span class="severity">{flag.status}</span>
                    <p class="evidence" lang={$targetLang}>{flag.text}</p>
                    {#if flag.note}<p>{flag.note}</p>{/if}
                    {#if flag.suggested}<p>Suggested: <b>{flag.suggested}</b></p>{/if}
                    <p class="muted">{flag.reviewer} · {new Date(flag.createdAt).toLocaleDateString()}</p>
                    {#if flag.status === "open"}
                      {#if flag.aiReview}
                        <p class="muted">AI-assisted proposal. Check the text and record your conclusion.</p>
                        {#if checkingFlag === flag.flagId && checkProject === projectPath}
                          <label>Human check
                            <textarea maxlength="500" bind:value={checkConclusion} placeholder="Issue confirmed, acceptable wording, style choice, or still uncertain — explain what you checked." /></label>
                          <button on:click={() => saveFlagCheck(flag)} disabled={!checkConclusion.trim()}>Save and resolve</button>
                          <button on:click={() => saveFlagCheck(flag, false)} disabled={!checkConclusion.trim()}>Save and keep open</button>
                          <button on:click={() => (checkingFlag = "")}>Cancel check</button>
                        {:else}
                          <button on:click={() => { checkingFlag = flag.flagId; checkConclusion = ""; checkProject = projectPath; }}>Record check…</button>
                        {/if}
                      {:else}
                        <button on:click={() => flagAction(flag, "resolved")}>Resolve</button>
                      {/if}
                    {:else}
                      <button on:click={() => flagAction(flag, "open")}>Reopen</button>
                    {/if}
                    <button on:click={() => flagAction(flag, "delete")}>Delete</button>
                  </li>
                {/each}
              </ol>
            {/if}
          </section>
        {:else if panelTab === "edits"}
          <section aria-label="Edits" class="edits">
            <p class="muted">Changes to this book's text, newest first.</p>
            {#if editsError}<p role="alert">{editsError}</p>{/if}
            {#if !editsLoaded}
              <p class="muted">Loading…</p>
            {:else if !edits.length}
              <p class="muted">No edits recorded in this book.</p>
            {:else}
              {#if editsTotal > edits.length}<p class="muted">The newest {edits.length} of {editsTotal}.</p>{/if}
              {#each editDays as day (day.day)}
                <h3>{day.day}</h3>
                <ol>
                  {#each day.entries as entry, index (entry.timestamp + entry.chapter + entry.verse + index)}
                    <li>
                      <button on:click={() => onNavigate(status?.book ?? "", entry.chapter, entry.verse)}>
                        {(status?.book ?? "").toUpperCase()} {entry.chapter}:{entry.verse}
                      </button>
                      <span class="category">{entry.username || "unknown"}</span>
                      <span class="severity">{new Date(entry.timestamp).toLocaleTimeString()}</span>
                      {#if entry.batchId}<span class="severity">{entry.undoes ? "undo of a change set" : "change set"}</span>{/if}
                      <p class="evidence" lang={$targetLang}>{#each graphemeDiff(entry.plainBefore, entry.plainAfter) as part}{#if part.kind === "removed"}<del>{part.text}</del>{:else if part.kind === "inserted"}<ins>{part.text}</ins>{:else}{part.text}{/if}{/each}</p>
                    </li>
                  {/each}
                </ol>
              {/each}
            {/if}
          </section>
        {:else if panelTab === "dictionary"}
          <!-- #384: the tab says what it holds. The pack's own dictionary is read-only
               by contract (NOTICE.md, contract 2); the rows here are the project's additions. -->
          <p class="muted dictionary-intro">Words this project accepts, and fixes it learned. The language pack's own dictionary is read-only.</p>
          <section aria-label="Project words" class="dictionary">
            <h3>Project words</h3>
            {#if !projectWords.length}
              <p class="muted">None yet. Add words from “Words in {bookLabel}” or a word's menu.</p>
            {:else}
              <ul class="words">
                {#each projectWords as entry (entry.key)}
                  <li><span class="word" lang={$targetLang}>{entry.word}</span> <span class="muted">{entry.scope === "word-in-project" ? "every book" : "this book"}</span>
                    <button on:click={() => removeProjectWord(entry)}>Remove</button></li>
                {/each}
              </ul>
            {/if}
          </section>
          <section aria-label="Learned fixes" class="dictionary">
            <h3>Learned fixes</h3>
            <p class="muted">Replaced words, offered again where they recur.
              {#if !learnedOn}Learned fixes are off in Settings › Language QA.{/if}
            </p>
            {#if learnedError}<p role="alert">{learnedError}</p>{/if}
            {#if !learnedLoaded}
              <p class="muted">Loading…</p>
            {:else if !learned.length}
              <p class="muted">Nothing learned yet. Replace one word in a verse and it appears here.</p>
            {:else}
              <table>
                <thead><tr><th>Replaced</th><th>With</th><th>Times</th><th>Books</th><th>Last at</th><th></th></tr></thead>
                <tbody>
                  {#each learned as fix (`${fix.old} → ${fix.new}`)}
                    <tr class:forgotten={!fix.enabled || fix.count <= 0}>
                      <td class="word" lang={$targetLang}>{fix.old}</td>
                      <td class="word" lang={$targetLang}>{fix.new}</td>
                      <td>{Math.max(0, fix.count)}</td>
                      <td>{(fix.books ?? []).map((b) => b.toUpperCase()).join(", ")}</td>
                      <td>{fix.lastRef}</td>
                      <td>
                        {#if fix.enabled}
                          <button disabled={learnedBusy} on:click={() => setLearned(fix, false)}>Forget</button>
                        {:else}
                          <button disabled={learnedBusy} on:click={() => setLearned(fix, true)}>Restore</button>
                        {/if}
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            {/if}
          </section>
        {/if}
        </div>
      {/if}
    </section>
    </div>
  {/if}
  {#if !docked && (expanded || !launcherHidden)}
    <div class="launcher-row">
      <button class="launcher" on:click={toggle} aria-expanded={expanded} aria-controls="language-qa-results">
        Language QA · {error ? "unavailable" : live?.state ?? "starting"}
        {#if live?.totalFindings} · {live.totalFindings}{/if}
      </button>
      {#if launcherHides && !expanded}
        <button class="launcher-close" on:click={hideLauncher} aria-label="Hide until the next check"
          title="Hide until the next check. The Language QA button in the status bar opens the panel.">✕</button>
      {/if}
    </div>
  {/if}
</aside>

<style>
  /* --z-panel (#288): a floating panel sits below every dialog. */
  /* #379 item 6: the body reads at --fs-xs like every panel; the tab bar and
     the filter row, chrome, at --fs-2xs like the bar's own actions. */
  .language-qa { position: fixed; bottom: 40px; right: 16px; z-index: var(--z-panel); font-size: var(--fs-xs); }
  /* Docked: the column is the box; the section fills it and scrolls. */
  .language-qa.docked { position: static; flex: 1; min-height: 0; display: flex; flex-direction: column; }
  /* #389: the frame carries the floating box's left-edge handle (the section
     scrolls, so the handle cannot sit inside it) and dims while a drag would
     close it. Docked, the frame is the column's flex child and fills it. */
  .float-frame { position: relative; }
  .float-frame.closing { opacity: .55; }
  .language-qa.docked .float-frame { flex: 1; min-height: 0; display: flex; flex-direction: column; }
  .language-qa.docked section { width: auto; max-height: none; flex: 1; min-height: 0; margin: 0; border: 0;
    border-radius: 0; box-shadow: none; }
  /* The section scrolls; its header and tab bar stay (sticky). Padding lives on
     the parts, not the section, so both sticky rows span the full width. */
  section { width: min(560px, calc(100vw - 32px)); max-height: min(580px, calc(100vh - 150px)); overflow: auto; padding: 0; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 8px; box-shadow: 0 4px 24px #0003; margin-bottom: 8px; }
  .paging { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .panel-head { position: sticky; top: 0; z-index: 3; background: var(--surface); }
  /* Errors and the one-line coverage warning under the bar; nothing is
     drawn (no second line) when there is none of them. */
  .head-meta { padding: 4px 12px 6px; border-bottom: 1px solid var(--border); }
  .head-meta:not(:has(*)) { display: none; }
  .info-btn { width: 20px; height: 20px; padding: 0; border-radius: 50%; font: italic 700 var(--fs-3xs)/1 Georgia, "Times New Roman", serif; color: var(--accent); border-color: var(--accent); }
  .info-btn[aria-expanded="true"] { background: var(--accent); color: white; }
  .status-line { margin: 4px 0; color: var(--text-2); }
  .alert { margin: 2px 0; color: var(--danger); }
  .coverage-warn { display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 10px; margin: 2px 0; color: var(--warning); }
  /* #376: the (i) is a popover anchored under the bar (the sticky header is
     its containing block). It scrolls inside itself; the header never grows. */
  .about { position: absolute; top: 100%; left: 8px; right: 8px; z-index: 4; margin: 0; padding: 10px 12px;
    background: var(--surface); color: var(--text); border: 1px solid var(--border-strong); border-radius: 8px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, .14); max-height: min(420px, 50vh); overflow: auto; outline: none; }
  .about p { margin: 4px 0; }
  .about h3 { font-size: var(--fs-2xs); margin: 10px 0 2px; }
  .about ul { margin: 2px 0; padding-left: 18px; }
  .about li { padding: 2px 0; border: 0; }
  .about .limitations { max-height: 120px; overflow: auto; }
  .about-head { display: flex; align-items: center; gap: 8px; }
  .about-head h3 { flex: 1; margin: 0; font-size: var(--fs-xs); }
  .about-close { width: 22px; height: 22px; padding: 0; border: 0; border-radius: 5px; background: transparent; color: var(--text-3); font-size: var(--fs-3xs); line-height: 1; }
  .about-close:hover, .about-close:focus-visible { background: var(--accent-bg); color: var(--accent); outline: none; }
  .panel-body { padding: 10px 12px; }
  button { cursor: pointer; border: 1px solid var(--border); border-radius: 4px; padding: 4px 8px; background: var(--surface); color: inherit; }
  button:disabled { opacity: .5; cursor: default; }
  .launcher-row { display: flex; justify-content: flex-end; align-items: center; gap: 4px; }
  .launcher { display: block; }
  .launcher-close { padding: 4px 7px; line-height: 1; }
  p { margin: 8px 0; overflow-wrap: anywhere; }
  ol { padding-left: 22px; }
  li { padding: 8px 0; border-bottom: 1px solid var(--border, #ddd); }
  /* Target text, in the target face (#286): under --font-ui a Gurmukhi line's
     danda was drawn from Vijaya, slanted, beside letters from Nirmala UI. */
  .evidence { font-family: var(--font-target); font-size: var(--fs-md); white-space: pre-wrap; }
  .severity, .category { margin-left: 8px; }
  .recheck { margin-left: 8px; font-weight: 600; color: var(--warning); }
  .where { margin-left: 8px; font-style: italic; }
  .reference { font-size: var(--fs-3xs); opacity: .85; border-left: 2px solid var(--border); padding-left: 6px; }
  /* The tab bar sits under the header and stays with it. */
  .panel-tabs { position: sticky; top: var(--head-h, 0px); z-index: 2; display: flex; gap: 2px; padding: 0 12px;
    background: var(--surface); border-bottom: 1px solid var(--border); overflow-x: auto; scrollbar-width: none;
    font-size: var(--fs-3xs); }
  .panel-tabs button { flex: 1 0 auto; border: 0; border-bottom: 2px solid transparent; border-radius: 0; background: none;
    padding: 8px 6px 6px; font-weight: 700; color: var(--text-2); white-space: nowrap; }
  /* #385: the book tab carries a name of any length and is the one that gives
     way at the panel's minimum width -- one line, cut with an ellipsis, the
     full name in its title. The other tabs keep their width. */
  .panel-tabs .book-tab { flex-shrink: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .panel-tabs button:hover { color: var(--text); }
  .panel-tabs button[aria-selected="true"] { color: var(--accent); border-bottom-color: var(--accent); }
  /* #376: the one filter row, pinned under the tab bar (#178). */
  .list-row { position: sticky; top: calc(var(--head-h, 0px) + var(--tabs-h, 0px)); z-index: 2; margin: 0;
    padding: 6px 12px; background: var(--surface); border-bottom: 1px solid var(--border); font-size: var(--fs-2xs); }
  .filter-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; }
  .segmented { display: inline-flex; border: 1px solid var(--border); border-radius: 6px; overflow: hidden; }
  .segmented button { border: 0; border-radius: 0; border-right: 1px solid var(--border); background: var(--surface); padding: 3px 8px; white-space: nowrap; }
  .segmented button:last-child { border-right: 0; }
  .segmented button[aria-selected="true"], .segmented button[aria-checked="true"] { background: var(--accent-bg); color: var(--accent); font-weight: 600; }
  .kinds { position: relative; }
  .kinds-btn { padding: 3px 8px; border-radius: 6px; white-space: nowrap; }
  .kinds-btn[aria-expanded="true"] { background: var(--accent-bg); color: var(--accent); border-color: var(--accent); }
  .legend { position: absolute; top: calc(100% + 4px); left: 0; z-index: 3; min-width: 220px; max-width: min(360px, calc(100vw - 32px));
    max-height: min(320px, 50vh); overflow: auto; padding: 8px; background: var(--surface); border: 1px solid var(--border-strong);
    border-radius: 8px; box-shadow: 0 8px 24px rgba(0, 0, 0, .14); display: flex; flex-wrap: wrap; gap: 4px; }
  .legend .clear { font-size: var(--fs-3xs); color: var(--accent); align-self: center; }
  .dictionary h3 { font-size: var(--fs-2xs); margin: 10px 0 4px; }
  .flags .toggle { display: flex; gap: 6px; align-items: center; }
  .book-words .tick-row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 6px 0; }
  .book-words input[type="number"] { width: 48px; }
  .book-words .table-box { max-height: 260px; overflow: auto; border: 1px solid var(--border); border-radius: 6px; }
  .book-words table { width: 100%; border-collapse: collapse; }
  .book-words th { position: sticky; top: 0; background: var(--surface); text-align: left; font-size: var(--fs-3xs);
    color: var(--text-3); padding: 4px; border-bottom: 1px solid var(--border); }
  .book-words td { padding: 3px 4px; border-bottom: 1px solid var(--border); }
  .book-words td.word { font-family: var(--font-target); font-size: var(--fs-sm); }
  .book-words tr.added td { opacity: .55; }
  .link { border: 0; background: none; padding: 0; font: inherit; color: inherit; text-decoration: underline dotted; }
  .dictionary .words { list-style: none; padding: 0; margin: 0; }
  .dictionary .words li { display: flex; gap: 8px; align-items: center; padding: 3px 0; border: 0; }
  .dictionary .words .word { font-family: var(--font-target); font-size: var(--fs-sm); }
  .flags li.resolved { opacity: .7; }
  .legend button { display: inline-flex; align-items: center; gap: 4px; font-size: var(--fs-3xs); padding: 2px 8px; }
  .legend button[aria-pressed="true"] { border-color: var(--accent); background: var(--accent-bg); }
  .legend .swatch { background: none; padding: 0 2px; font-size: var(--fs-3xs); }
  .legend .n { color: var(--text-3); font-variant-numeric: tabular-nums; }
  .walk-status { margin: 0; font-size: var(--fs-3xs); color: var(--text-2); }
  .walk-status:empty { display: none; }
  .edits h3 { font-size: var(--fs-2xs); margin: 10px 0 2px; }
  .edits del { background: var(--danger-bg); color: var(--danger); }
  .edits ins { background: var(--success-bg); color: var(--success); text-decoration: none; }
  .dictionary table { width: 100%; border-collapse: collapse; }
  .dictionary th { text-align: left; font-size: var(--fs-3xs); color: var(--text-3); padding: 4px; border-bottom: 1px solid var(--border); }
  .dictionary td { padding: 4px; border-bottom: 1px solid var(--border); }
  .dictionary td.word { font-family: var(--font-target); font-size: var(--fs-sm); }
  .dictionary tr.forgotten td { opacity: .55; }
  .dictionary tr.forgotten td.word { text-decoration: line-through; }
  .history-toggle { font-size: var(--fs-3xs); padding: 2px 6px; }
  .notice { font-weight: 600; }
  .muted { opacity: .75; }
  .scope { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 12px; margin: 8px 0; padding: 8px; border: 1px solid var(--border); border-radius: 6px; }
  .scope h3 { font-size: var(--fs-3xs); margin: 0 0 4px; }
  .scope ul { margin: 0; padding-left: 16px; }
  .scope li { padding: 2px 0; border: 0; }
  .scope .reason { display: block; font-size: var(--fs-3xs); opacity: .75; }
  .scope p { grid-column: 1 / -1; margin: 4px 0 0; }
  @media (max-width: 480px) { .scope { grid-template-columns: 1fr; } }
</style>
