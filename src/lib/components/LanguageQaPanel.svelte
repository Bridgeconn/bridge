<script lang="ts">
  // #487: the Language QA tab of the Review panel. Until 2026-11-11 this was
  // a panel of its own -- a docked column, a floating box on the other
  // screens, a launcher, Pause, ◂ ▸, Undock and Close in its bar. All of
  // that is gone: ReviewPanel mounts this inside its Language QA tab, the
  // View menu's Language QA entry shows or hides that tab (viewMenu.ts), and
  // a verse's findings, whatever their scope, are acted on here with the
  // same buttons the verse's right-click menu offers.
  //
  // PanelWindow.svelte still mounts it in a separate window (`docked`), where
  // it draws the shared bar so the window can be docked back or closed.
  import { getContext as getSvelteContext, onDestroy, tick } from "svelte";
  import { get as getStore } from "svelte/store";
  import PanelHeader from "./PanelHeader.svelte";
  import { revealFinding } from "../findingFocus";
  import { bridge as bridgeApi } from "../api/bridgeClient";
  import { bindReviewProject } from "../reviewProjectGuard";
  import { languageQaChannel, nudgeLanguageQa } from "../languageQaInline";
  import type {
    BookWordRow, FlagInput, LanguageQaFlag, LanguageQaScope, LanguageQaStatus, LanguageQaSuggestion, LanguageQaView, LearnedFix,
  } from "../types/languageQa";
  import type { HouseStyleEntry } from "../types/houseStyle";
  import { addProjectWords, canAddProjectWord } from "../projectWords";
  import { addFlag, deleteFlag, setFlagStatus, publishBookFlags, recordFlagCheck } from "../flags";
  import type { AiReviewImportPreview } from "../types/languageQa";
  import LanguageQaHistoryList from "./LanguageQaHistoryList.svelte";
  import FlagDialog from "./FlagDialog.svelte";
  import RelatedWords from "./RelatedWords.svelte";
  import OccurrencesPopup from "./OccurrencesPopup.svelte";
  import type { VerseHistoryEntry } from "../types/finding";
  import { graphemeDiff } from "../utils/unicodeDiff";
  import { LANGUAGE_QA_CATEGORY_LABELS, LANGUAGE_QA_CATEGORY_MARKS } from "../utils/highlight";
  import { decideLanguageQaFindingOptimistically } from "../findingActions";
  import { forgetLearnedFix, isLearnedFinding, learnedPairOf } from "../learnedFixes";
  import { openScopeDialog } from "../scopedApply";
  import { orderedSuggestions, suggestionTag } from "../languageQaSuggestions";
  import {
    checkingProgress, focusedFindingId, chapterVerseNums, currentChapter, languageQaFindingsByVerse, project, selectedVerse,
    targetLang, verseKey,
  } from "../stores";
  import { applyLanguageQaSuggestedFix, editingChapter } from "../verseEditor";
  import type { LanguageQaCategory, LanguageQaFinding } from "../types/languageQa";

  const native = getSvelteContext<{ dock: () => void; close: () => void } | undefined>("panel-window");
  const bridge = native ? bindReviewProject(bridgeApi, getStore(project)?.path || "__no_project__") : bridgeApi;

  export let projectPath: string;
  export let onNavigate: (book: string, chapter: string, verse: string) => void | Promise<void>;
  /** The tab is on screen. The paged chapter / book list is read only then;
   * the selected verse's list is read regardless, for the tab's count. */
  export let active = true;
  /** The selected verse's open findings: the Review panel's tab badge. */
  export let verseCount = 0;
  /** In a separate window (PanelWindow.svelte): draw the shared bar. */
  export let docked = false;
  $: ownBar = docked || Boolean(native);

  const PAGE = 50;

  // Which list is paged: every open finding; those shown again because the
  // rule changed since they were ignored; or those marked as false positives.
  let view: LanguageQaView = "findings";
  // Which part of the book the list covers. The Review panel is about one
  // verse, so that is where the list starts; the choice is kept while the
  // reviewer moves between verses.
  type ListScope = "verse" | "chapter" | "book";
  let listScope: ListScope = "verse";
  // #487: every kind is shown until the reviewer unticks one; what is kept
  // is the unticked set, so a kind that first appears later is shown too.
  let hiddenCategories: string[] = [];
  let verseList: LanguageQaFinding[] = [];
  let verseHidden: Array<LanguageQaFinding & { decision: string }> = [];
  // F8 / Shift+F8: where the walk stands, said for screen readers.
  let walkStatus = "";
  let pendingStep: { chapter: string; step: 1 | -1 } | null = null;
  // The tab's own sections. "findings" holds the three engine lists above; the
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
  // The page on show, fetched on demand (see below).
  let page: LanguageQaStatus | null = null;
  // The coverage headings are bilingual only when the statement itself is
  // (Tamil); a profile pack's statement is English.
  $: effectiveLanguage = status?.language;
  $: tamilCoverage = !!effectiveLanguage && ["ta", "tam"].includes(effectiveLanguage.language.toLowerCase().split("-")[0]) && effectiveLanguage.pack !== "common" && effectiveLanguage.basis !== "setting-off";
  $: aboutLanguage = effectiveLanguage?.name || effectiveLanguage?.language || $project?.targetLanguage || "Language QA";
  $: checksOff = effectiveLanguage?.basis === "setting-off" || status?.setting === "off";
  $: commonOnly = effectiveLanguage?.pack === "common";
  $: aboutStamp = `${projectPath}|${live?.generation}|${live?.state}|${live?.language?.pack}|${live?.language?.setting}|${live?.setting}`;
  const detectionLabels: Record<string, string> = {
    metadata: "Language supplied by the project.",
    "script-suggestion": "Language suggested from the script; the project has no declared language.",
    "metadata-conflict": "The project language and detected script disagree. Only common checks are enabled.",
    "mixed-script": "The sample contains mixed scripts. Only common checks are enabled.",
    undetermined: "The language could not be determined. Only common checks are enabled.",
  };

  // The tab does not poll. Its state and totals come from the one Language
  // QA status channel (languageQaInline.ts), which backs off when idle. It
  // fetches rows only when there is something new to show: the tab is shown,
  // paged, switched to another list or scope, or a new pass lands (a changed
  // generation or state). It never feeds the verse marks; those come from
  // languageQa.inline, unpaged.
  $: channel = $languageQaChannel.projectPath === projectPath ? $languageQaChannel : null;
  $: live = channel?.status ?? null;
  $: error = localError || channel?.error || "";
  $: pageCurrent = page?.projectPath === projectPath && page?.generation === live?.generation && page?.state === live?.state
    && page?.language?.pack === live?.language?.pack && page?.language?.setting === live?.language?.setting && page?.setting === live?.setting;
  $: status = pageCurrent ? page : live;
  $: scopeChapter = listScope === "book" ? "" : $currentChapter;
  // The verse scope reads languageQa.verse; its kinds are counted here. The
  // engine's categoryCounts are narrowed by chapter only, never by kind, so
  // an unticked kind stays in the legend.
  $: verseCounts = verseList.reduce<Record<string, number>>((counts, f) => {
    if (f.category) counts[f.category] = (counts[f.category] ?? 0) + 1;
    return counts;
  }, {});
  $: legendCounts = listScope === "verse" ? verseCounts : (status?.categoryCounts ?? {});
  $: allCategories = Object.keys(legendCounts);
  $: shownCategories = allCategories.filter((category) => !hiddenCategories.includes(category));
  $: narrowed = allCategories.some((category) => hiddenCategories.includes(category));
  $: pageKey = active && live && listScope !== "verse" && (!narrowed || shownCategories.length)
    ? `${view}|${offset}|${aboutStamp}|${scopeChapter}|${narrowed ? shownCategories.join(",") : ""}` : "";
  // The state is part of the key: a pass publishes its findings under the
  // generation it started with, so the list read while it was queued (the
  // previous pass's findings) must be read again once it completes (#237).
  $: verseKeyNow = live && $selectedVerse
    ? `${projectPath}|${live.generation}|${live.state}|${$currentChapter}|${$selectedVerse}` : "";
  // Another verse: drop the last verse's list at once, before its own arrives.
  let verseShownFor = "";
  $: {
    const shown = `${projectPath}|${$currentChapter}|${$selectedVerse ?? ""}`;
    if (shown !== verseShownFor) {
      verseShownFor = shown;
      verseList = [];
      verseHidden = [];
      actionNotice = "";
    }
  }
  $: if (verseKeyNow) void loadVerseList(verseKeyNow, $currentChapter, $selectedVerse ?? "");
  $: verseCount = verseList.length;
  $: listed = listScope === "verse"
    ? verseList.filter((f) => !narrowed || shownCategories.includes(f.category ?? ""))
    : (narrowed && !shownCategories.length ? [] : (status?.findings ?? []));
  $: if (pageKey) void loadPage(pageKey);

  async function loadPage(key: string): Promise<void> {
    const ticket = ++sequence;
    const path = projectPath;
    busy = true;
    try {
      const filters: { chapter?: string; categories?: string[] } = {};
      if (scopeChapter) filters.chapter = scopeChapter;
      if (narrowed) filters.categories = shownCategories;
      const next = Object.keys(filters).length
        ? await bridge.languageQaStatus(path, offset, PAGE, view, filters)
        : await bridge.languageQaStatus(path, offset, PAGE, view);
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

  // -- Paging (#487): Previous / Next, a go-to-page box, and the pager pinned
  // to the bottom of the tab (CSS below). The rows on show stay until the
  // next page arrives, so nothing blanks between pages; a page the reviewer
  // asked for starts at its first row, under the pinned filter rows.
  let listTop: HTMLElement | null = null;
  let gotoPage: number | null = null;
  $: total = listScope !== "verse" ? (status?.totalFindings ?? 0) : 0;
  $: pageCount = Math.max(1, Math.ceil(total / PAGE));
  $: pageIndex = Math.min(pageCount - 1, Math.floor(offset / PAGE));
  $: pageStart = Math.min((status?.offset ?? offset) + 1, total);
  $: pageEnd = Math.min((status?.offset ?? offset) + PAGE, total);

  function showPage(index: number): void {
    const next = Math.max(0, Math.min(pageCount - 1, index)) * PAGE;
    if (next === offset) return;
    offset = next;
    void tick().then(() => listTop?.scrollIntoView?.({ block: "start" }));
  }

  function turnPage(delta: number): void {
    showPage(pageIndex + delta);
  }

  function goToPage(): void {
    if (gotoPage === null || !Number.isFinite(gotoPage)) return;
    showPage(Math.round(gotoPage) - 1);
    gotoPage = null;
  }

  async function loadVerseList(key: string, chapter: string, verse: string): Promise<void> {
    try {
      const result = await bridge.languageQaVerse(projectPath, chapter, verse);
      if (disposed || key !== verseKeyNow) return;
      verseList = result.findings;
      verseHidden = result.hidden ?? [];
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

  function showAllCategories(): void {
    hiddenCategories = [];
    offset = 0;
  }

  // The (i): what the checks cover and what they never do (DECISIONS
  // 2026-10-09). Closed by the (i) again, Escape, or a click elsewhere.
  let aboutOpen = false;
  let infoButton: HTMLButtonElement | null = null;
  let aboutBox: HTMLDivElement | null = null;
  // The pinned rows' height: what a page's first row scrolls in under.
  let headHeight = 0;
  // #376: the Kinds dropdown in the filter row, closed the same three ways.
  let kindsOpen = false;
  let kindsButton: HTMLButtonElement | null = null;
  let kindsBox: HTMLDivElement | null = null;

  // #376: the state word: "completed", "paused", "checking 12/50".
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
    hiddenCategories = hiddenCategories.includes(category)
      ? hiddenCategories.filter((c) => c !== category) : [...hiddenCategories, category];
    offset = 0;
  }

  /** The marks of one chapter in reading order (the ones drawn in the text),
   * without the kinds the reviewer unticked. */
  function chapterMarks(chapter: string): LanguageQaFinding[] {
    const marks: LanguageQaFinding[] = [];
    for (const verse of $chapterVerseNums[chapter] ?? []) {
      const found = ($languageQaFindingsByVerse[verseKey(chapter, verse)] ?? [])
        .filter((f) => !hiddenCategories.includes(f.category ?? ""));
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

  /** A card's reference (#402): the verse opens, then the finding's mark is
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
    if (next !== "findings" && listScope === "verse") listScope = "chapter";
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

  // -- The card's actions (#487): the same as the verse's right-click menu,
  // on a finding of any scope. The list changes first and the engine after;
  // a failed call puts the finding back and says why.
  let actionNotice = "";
  let actionNoticeError = false;
  let actionBusy = false;
  // Where a Use applies: this verse (written at once), or every place of
  // the same finding in the chapter or book (asked first).
  let applyScope: LanguageQaScope = "verse";
  const APPLY_SCOPES: { scope: LanguageQaScope; label: string }[] = [
    { scope: "verse", label: "This verse" }, { scope: "chapter", label: "Whole chapter" }, { scope: "book", label: "Whole book" },
  ];
  let occurrences: { word: string; source: "irv" | "ov"; match?: "word" | "text" } | null = null;
  // Flag for review: a question for the team, never a change to the verse.
  let flagDraft: LanguageQaFinding | null = null;
  const severityBadge: Record<string, string> = {
    high: "badge-wrong", medium: "badge-review", low: "badge-review", info: "badge-review",
  };
  // Related words are offered for the first single-word finding of the verse.
  $: relatedWord = listScope === "verse"
    ? verseList.map((f) => f.originalText.trim()).find((w) => w && !/\s/.test(w)) ?? "" : "";

  function removeFinding(finding: LanguageQaFinding): void {
    verseList = verseList.filter((f) => f.id !== finding.id);
    if (page) page = { ...page, findings: page.findings.filter((f) => f.id !== finding.id) };
  }

  function restoreFinding(finding: LanguageQaFinding): void {
    if (verseKey(finding.chapter, finding.verse) === verseKey($currentChapter, $selectedVerse ?? "")
      && !verseList.some((f) => f.id === finding.id)) {
      verseList = [...verseList, finding].sort((a, b) => a.start - b.start);
    }
    if (page && !page.findings.some((f) => f.id === finding.id)) {
      page = { ...page, findings: [...page.findings, finding] };
    }
  }

  function say(message: string, failed = false): void {
    actionNotice = message;
    actionNoticeError = failed;
  }

  function useFix(finding: LanguageQaFinding, chosen: LanguageQaSuggestion): void {
    if (actionBusy) return;
    if (applyScope !== "verse") {
      void openScopeDialog(finding, chosen.text, applyScope);
      return;
    }
    actionBusy = true;
    actionNotice = "";
    removeFinding(finding);
    void applyLanguageQaSuggestedFix(finding, chosen).then((result) => {
      say(result.message, !result.ok);
      if (!result.ok) restoreFinding(finding);
    }).finally(() => { actionBusy = false; });
  }

  function decideFinding(finding: LanguageQaFinding, decision: "ignored" | "rejected"): void {
    removeFinding(finding);
    say(decision === "ignored" ? "Occurrence ignored." : "Marked as a false positive.");
    void decideLanguageQaFindingOptimistically(finding, decision).then((failure) => {
      if (!failure) return;
      say(failure, true);
      restoreFinding(finding);
    });
  }

  /** Forget a learned fix: every recurrence of it goes, not just this one. */
  function forgetFix(finding: LanguageQaFinding): void {
    const pair = learnedPairOf(finding);
    if (!pair) return;
    const isSame = (f: LanguageQaFinding) => learnedPairOf(f)?.old === pair.old && learnedPairOf(f)?.newWord === pair.newWord;
    const removed = [...verseList, ...(page?.findings ?? [])].filter(isSame);
    verseList = verseList.filter((f) => !isSame(f));
    if (page) page = { ...page, findings: page.findings.filter((f) => !isSame(f)) };
    say(`No longer offering “${pair.old}” → “${pair.newWord}”. Restore it in the Dictionary tab.`);
    void forgetLearnedFix(pair.old, pair.newWord).then((failure) => {
      if (!failure) return;
      say(failure, true);
      removed.forEach(restoreFinding);
    });
  }

  /** "This word is spelt right in this project": its spelling findings go. */
  function addWord(finding: LanguageQaFinding): void {
    const word = finding.originalText.trim();
    const isWord = (f: LanguageQaFinding) => f.originalText.trim() === word;
    const removed = [...verseList, ...(page?.findings ?? [])].filter(isWord);
    verseList = verseList.filter((f) => !isWord(f));
    if (page) page = { ...page, findings: page.findings.filter((f) => !isWord(f)) };
    say(`“${word}” is now a project word.`);
    void addProjectWords([word]).then((failure) => {
      if (!failure) return;
      say(failure, true);
      removed.forEach(restoreFinding);
    });
  }

  function copyWord(word: string): void {
    const write = typeof navigator !== "undefined" ? navigator.clipboard?.writeText(word) : undefined;
    say(write ? `Copied “${word}”.` : "The clipboard is not available here.");
    write?.catch(() => say("Could not copy to the clipboard.", true));
  }

  async function saveFlag(input: FlagInput): Promise<string> {
    if (!$project) return "No project is open.";
    const result = await addFlag($project.path, input);
    if (result.error) return result.error;
    flagDraft = null;
    say("Flag saved.");
    return "";
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
    const failure = await addProjectWords(words, wordScope, projectPath);
    bookWordsBusy = false;
    if (failure) {
      bookWordsNotice = failure;
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
    const failure = await recordFlagCheck(projectPath, flag, checkConclusion, resolve);
    if (failure) { flagsError = failure; return; }
    checkingFlag = "";
    checkConclusion = "";
    await loadFlags();
  }

  async function flagAction(flag: LanguageQaFlag, action: "resolved" | "open" | "delete"): Promise<void> {
    const failure = action === "delete" ? await deleteFlag(projectPath, flag) : await setFlagStatus(projectPath, flag, action);
    if (failure) {
      flagsError = failure;
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
  });
</script>

<svelte:window on:keydown={onWindowKeydown} on:pointerdown={onWindowPointerdown} />

<div class="language-qa" class:window={ownBar} aria-label="Language QA">
  {#if ownBar}
    <PanelHeader id="languageQa" title={`Language QA · ${stateWord}`} label="Language QA" layout={false} />
  {/if}
  <p class="walk-status" role="status" aria-live="polite">{walkStatus}</p>

  <!-- The pinned rows: the state line with the (i), the section tabs and,
       on Issues, the one filter row (#178, #376). They stay while the list
       scrolls under them; the (i) is a popover anchored here that never
       changes their height. -->
  <div class="panel-head" bind:clientHeight={headHeight}>
    <div class="state-row">
      <span class="state">Checks {stateWord}{#if status?.totalFindings}{" · "}{status.totalFindings} candidates{/if}</span>
      <button type="button" class="info-btn" bind:this={infoButton} aria-label="About these checks"
        aria-expanded={aboutOpen} aria-controls="language-qa-about"
        title={`About ${aboutLanguage} checks and limitations`} on:click={() => (aboutOpen = !aboutOpen)}>i</button>
    </div>
    {#if error}<p class="alert" role="alert">{error}</p>{/if}
    {#if status?.error}<p class="alert" role="alert">{status.error}</p>{/if}
    {#if aboutOpen}
      <!-- Behind the (i) at Benz's request (DECISIONS 2026-10-09, superseding
           2026-09-24): what the checks cover, and what they never do; since
           #376 also the full status line, the list and key hints and the
           tabs' explanations. -->
      <div id="language-qa-about" class="about" role="dialog" aria-label="What Language QA checks"
        tabindex="-1" bind:this={aboutBox}>
        <div class="about-head">
          <h3>About Language QA · {aboutLanguage}</h3>
          <button type="button" class="about-close" aria-label="Close this note" on:click={closeAbout}>✕</button>
        </div>
        <p>Checks run offline, on this computer.</p>
      {#if status?.incomplete}
        <p class="coverage-warn"><span class="notice">Coverage incomplete. Omitted text has not passed QA.</span></p>
      {/if}
        {#if !status}<p>{error ? "Language QA is unavailable. Coverage cannot be confirmed." : "Preparing language checks. Coverage is not yet available."}</p>
        {:else if checksOff}<p>Language QA is switched off. No language checks are running.</p>
        {:else if commonOnly}<p>Only common technical checks are available; there is no active language-specific pack.</p>{/if}
        {#if effectiveLanguage}<p>Project language: {effectiveLanguage.declared || $project?.targetLanguageId || "not declared"}. Effective pack: {effectiveLanguage.pack}.
          {#if effectiveLanguage.basis === "setting"}Selected in Settings; this overrides automatic pack selection.{/if}</p>{/if}
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
          <p>{status.language?.message ?? (status.state === "paused" ? "Checks paused. Resume them in Settings › Language QA." : "Preparing language checks…")}</p>
        {/if}
        {#if !checksOff && !commonOnly && status?.coverage?.inScope}
        <div class="scope">
          <div>
            <h3>Checks{#if tamilCoverage} · <span lang="ta">சரிபார்ப்பவை</span>{/if}</h3>
            <ul>
              {#each status.coverage.inScope as row (row.category)}
                <li>{row.label}{#if tamilCoverage && row.labelTa} · <span lang="ta">{row.labelTa}</span>{/if}</li>
              {/each}
            </ul>
          </div>
          <div>
            <h3>Does not check{#if tamilCoverage} · <span lang="ta">சரிபார்க்காதவை</span>{/if}</h3>
            <ul>
              {#each status.coverage.outOfScope as row (row.category)}
                <li title={row.reason}>
                  {row.label}{#if tamilCoverage && row.labelTa} · <span lang="ta">{row.labelTa}</span>{/if}
                  <span class="reason">{row.reason}{#if tamilCoverage && row.reasonTa} <span lang="ta">{row.reasonTa}</span>{/if}</span>
                </li>
              {/each}
            </ul>
          </div>
          <p class="muted">Who checks these before publication: {status.coverage.handOff}</p>
        </div>
        {/if}
        {#if status}<p class="muted">{status.coverage?.summary ?? ""} {status.storage}</p>{/if}
        <p class="muted">No candidates from the enabled checks is not publication approval.</p>
        {#if status?.limitations?.length}
          <h3>Coverage details ({status.limitations.length})</h3>
          <ul class="limitations">{#each status.limitations as limitation}<li>{limitation}</li>{/each}</ul>
        {/if}
        {#if !checksOff && status?.findings?.length}
          <h3>Examples from this book</h3><ul>{#each status.findings.slice(0, 3) as finding}<li>{finding.chapter}:{finding.verse} · <span lang={$targetLang}>{finding.originalText}</span> — {finding.message}</li>{/each}</ul>
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
    {#if status}
      <div class="panel-tabs" role="tablist" aria-label="Language QA panel">
        <button role="tab" aria-selected={panelTab === "findings"} on:click={() => showPanelTab("findings")}>Issues</button>
        <button role="tab" class="book-tab" aria-selected={panelTab === "bookWords"} title={`Words in ${bookLabel}`}
          on:click={() => showPanelTab("bookWords")}>Words in {bookLabel}</button>
        <button role="tab" aria-selected={panelTab === "flags"} on:click={() => showPanelTab("flags")}>Flags</button>
        <button role="tab" aria-selected={panelTab === "edits"} on:click={() => showPanelTab("edits")}>Edits</button>
        <button role="tab" aria-selected={panelTab === "dictionary"} on:click={() => showPanelTab("dictionary")}>Dictionary</button>
      </div>
      {#if panelTab === "findings"}
        <!-- #376: one filter row: the list switch, the scope, and Kinds as one
             dropdown. It wraps to a second line at the column's minimum
             width, never a third. -->
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
          <div class="scope-switch segmented" role="radiogroup" aria-label="Show findings for">
            {#each [["verse", "Verse"], ["chapter", "Chapter"], ["book", "Book"]] as [value, label]}
              <button role="radio" aria-checked={listScope === value} disabled={value === "verse" && view !== "findings"}
                on:click={() => showScope(value === "verse" ? "verse" : value === "chapter" ? "chapter" : "book")}>{label}</button>
            {/each}
          </div>
          {#if allCategories.length}
            <div class="kinds">
              <button type="button" class="kinds-btn" bind:this={kindsButton} aria-expanded={kindsOpen}
                aria-controls="language-qa-kinds" aria-haspopup="true"
                title={narrowed ? "Some kinds are unticked and left out of the list" : "Every kind is shown; untick a kind to leave it out"}
                on:click={() => (kindsOpen = !kindsOpen)}>
                Kinds · {narrowed ? `${shownCategories.length} of ${allCategories.length}` : allCategories.length} ▾
              </button>
              {#if kindsOpen}
                <div id="language-qa-kinds" class="legend" role="group" aria-label="Kinds of finding" bind:this={kindsBox}>
                  {#each Object.entries(legendCounts) as [category, count] (category)}
                    <button aria-pressed={!hiddenCategories.includes(category)} on:click={() => toggleCategory(category)}
                      title={hiddenCategories.includes(category) ? "Left out; click to show this kind again" : "Shown; click to leave this kind out"}>
                      <mark class="swatch {markClass(category)}">ab</mark>
                      {categoryLabel(category)}
                      <span class="n">{count}</span>
                    </button>
                  {/each}
                  {#if narrowed}
                    <button type="button" class="link clear" on:click={showAllCategories}>All</button>
                  {/if}
                </div>
              {/if}
            </div>
          {/if}
        </div>
      {/if}
    {/if}
  </div>

  <div class="panel-body">
  {#if !status}
    <p class="muted">{error ? "Language QA is unavailable." : "Language QA has not reported yet."}</p>
  {:else if panelTab === "findings"}
    {#if actionNotice}<p class="action-notice" class:failed={actionNoticeError} role="status">{actionNotice}</p>{/if}
    {#if listScope === "verse" && !$selectedVerse}
      <p class="muted">Select a verse to list its findings.</p>
    {:else if listScope === "verse" && !listed.length}
      <p class="muted none">
        {#if narrowed && verseList.length}No findings in this verse of the kinds ticked.
        {:else if status.state !== "completed"}Language QA is checking…
        {:else}No Language QA findings on this verse.{/if}
      </p>
    {/if}
    {#if listScope !== "verse" && view === "findings" && status.state === "completed" && !status.totalFindings}
      <p class="muted">No candidates found by the enabled checks.</p>
    {/if}
    <ol class="cards" bind:this={listTop} style:scroll-margin-top="{headHeight}px"
      aria-label={view === "findings" ? "Language QA findings" : view === "recheck" ? "Findings to re-check" : "False positives"}
      start={listScope === "verse" ? 1 : (status.offset ?? 0) + 1}>
      {#each listed as finding (finding.id)}
        <li class="finding lqa-finding" data-lqa-id={finding.id}>
          <div class="verdict">
            <button type="button" class="ref" on:click={() => void openFinding(finding)}
              title={finding.context ? "Open the verse" : "Open the verse and show this in the text"}>
              {finding.book.toUpperCase()} {finding.chapter}:{finding.verse}
            </button>
            <span class="badge {severityBadge[finding.severity] ?? 'badge-review'}">{finding.severity}</span>
            {#if finding.category || isLearnedFinding(finding)}<span class="engine-badge">{isLearnedFinding(finding) ? "learned fix" : finding.category}</span>{/if}
            <span class="check-id">{finding.ruleId}</span>
            {#if finding.previouslyIgnored}<span class="recheck" title="Ignored under an older rule version; check it again">Re-check</span>{/if}
            {#if finding.context}<span class="engine-badge where" title={finding.context === "heading" ? `Section heading: ${finding.contextText ?? ""}` : finding.context === "introduction" ? `Book introduction: ${finding.contextText ?? ""}` : "Footnote text"}>in {finding.context}</span>{/if}
          </div>
          <p class="explain"><b class="evidence" lang={$targetLang}>{finding.originalText}</b> <span class="message">{finding.message}</span></p>
          {#if finding.context === "heading" && finding.contextText}<p class="muted">Heading: {finding.contextText}</p>{/if}
          {#if finding.context === "introduction" && finding.contextText}<p class="muted">Book introduction: {finding.contextText}</p>{/if}
          {#if finding.referenceEvidence}
            <details>
              <summary>Reference evidence · {finding.referenceEvidence.label}</summary>
              <p>{finding.referenceEvidence.range}</p>
              <p>{finding.referenceEvidence.openingText}</p>
              {#if finding.referenceEvidence.closingText !== finding.referenceEvidence.openingText}
                <p>{finding.referenceEvidence.closingText}</p>
              {/if}
              <p class="muted">{finding.referenceEvidence.path}</p>
            </details>
          {/if}
          {#if finding.reference}
            <p class="reference"><b>{finding.reference.label} {finding.reference.ref}:</b> {finding.reference.text}</p>
          {/if}
          <div class="decision-row lqa-actions">
            {#if view !== "falsePositives"}
              {#each orderedSuggestions(finding) as s (s.rank)}
                <button class="edit-inline" disabled={actionBusy || $checkingProgress.running || Boolean($editingChapter)}
                  title={s.rationale || "Replace the flagged text with this form and re-check the verse"}
                  on:click={() => useFix(finding, s)}>{s.source === "learned" ? "Change to" : "Use"} “{s.text}”{#if suggestionTag(s)}<small class="sugg-tag">{suggestionTag(s)}</small>{/if}</button>
              {/each}
              <button class="ignore" on:click={() => decideFinding(finding, "ignored")}>⊘ Ignore</button>
              <button class="ignore" on:click={() => decideFinding(finding, "rejected")}>False positive</button>
              {#if isLearnedFinding(finding)}
                <button class="ignore" title="Stop offering this replacement anywhere in the book; it can be restored"
                  on:click={() => forgetFix(finding)}>Forget this fix</button>
              {/if}
              <button class="flag" title="Ask the team about this text; nothing in the verse changes"
                on:click={() => (flagDraft = finding)}>⚑ Flag…</button>
              {#if canAddProjectWord(finding)}
                <button class="ignore" title="This word is spelt right in this project: stop reporting it anywhere in the book"
                  on:click={() => addWord(finding)}>Add to dictionary (this book)</button>
              {/if}
            {/if}
            <button class="ignore" title="Copy the flagged text" on:click={() => copyWord(finding.originalText.trim())}>Copy</button>
            <button class="ignore" title="Every place this text occurs in the book"
              on:click={() => (occurrences = { word: finding.originalText.trim(), source: "irv", match: "text" })}>Search</button>
            <button class="ignore history-toggle" aria-expanded={historyOpen.has(finding.id)} on:click={() => toggleHistory(finding.id)}>
              History
            </button>
          </div>
          {#if view !== "falsePositives" && orderedSuggestions(finding).length && !finding.context}
            <div class="apply-row" role="radiogroup" aria-label="Apply a suggestion to">
              <span class="apply-label">Apply to</span>
              {#each APPLY_SCOPES as option (option.scope)}
                <button type="button" role="radio" aria-checked={applyScope === option.scope}
                  class:on={applyScope === option.scope} on:click={() => (applyScope = option.scope)}>{option.label}</button>
              {/each}
            </div>
          {/if}
          {#if historyOpen.has(finding.id)}
            <LanguageQaHistoryList {projectPath} chapter={finding.chapter} verse={finding.verse} findingId={finding.id} />
          {/if}
        </li>
      {/each}
    </ol>
    {#if listScope === "verse" && relatedWord && $project}
      <RelatedWords projectPath={$project.path} word={relatedWord}
        onShowOccurrences={(word, source) => (occurrences = { word, source })} />
    {/if}
    {#if listScope === "verse" && verseHidden.length > 0}
      <details class="decided">
        <summary>Decided ({verseHidden.length})</summary>
        {#each verseHidden as f (f.id)}
          <div class="finding lqa-finding decided-card">
            <div class="verdict">
              <span class="check-id">{f.ruleId}</span>
              <span class="badge badge-decided">{f.decision === "rejected" ? "false positive" : f.decision}</span>
            </div>
            <p class="explain"><b class="evidence" lang={$targetLang}>{f.originalText}</b> <span class="message">{f.message}</span></p>
          </div>
        {/each}
      </details>
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

  {#if status && panelTab === "findings" && listScope !== "verse" && total > PAGE}
    <!-- #487: pinned to the bottom of the tab while the list scrolls. -->
    <div class="paging" class:busy>
      <button type="button" on:click={() => turnPage(-1)} disabled={busy || pageIndex === 0}>Previous</button>
      <span class="page-of">Page {pageIndex + 1} of {pageCount} · {pageStart}–{pageEnd} of {total}</span>
      <form class="goto" on:submit|preventDefault={goToPage}>
        <label>Go to <input type="number" min="1" max={pageCount} bind:value={gotoPage} aria-label="Go to page" disabled={busy} /></label>
        <button type="submit" disabled={busy || gotoPage === null}>Go</button>
      </form>
      <button type="button" on:click={() => turnPage(1)} disabled={busy || pageIndex >= pageCount - 1}>Next</button>
    </div>
  {/if}
</div>

{#if occurrences && $project}
  <OccurrencesPopup projectPath={$project.path} word={occurrences.word} source={occurrences.source}
    match={occurrences.match ?? "word"} {onNavigate} onClose={() => (occurrences = null)} />
{/if}
{#if flagDraft}
  <FlagDialog
    draft={{ chapter: flagDraft.chapter, verse: flagDraft.verse, start: flagDraft.start, end: flagDraft.end,
      text: flagDraft.originalText, suggested: flagDraft.suggestions?.[0]?.text, findingId: flagDraft.id }}
    reference={`${flagDraft.book.toUpperCase()} ${flagDraft.chapter}:${flagDraft.verse}`}
    onSave={saveFlag}
    onCancel={() => (flagDraft = null)}
  />
{/if}

<style>
  /* #379 item 6: the body reads at --fs-xs like every panel; the tab bar and
     the filter row, chrome, at --fs-2xs. The tab is laid out by its host:
     ReviewPanel's .tab-content scrolls and pads it 10px 12px, so the root
     takes that padding back and the pinned rows, the body and the pager each
     span the column with their own gutters. */
  .language-qa { font-size: var(--fs-xs); color: var(--text); margin: -10px -12px; display: flex; flex-direction: column; min-height: 0; }
  /* A separate window (PanelWindow.svelte) has no host padding and scrolls here. */
  .language-qa.window { margin: 0; flex: 1; overflow: auto; }
  .panel-head { position: sticky; top: 0; z-index: 3; background: var(--surface); border-bottom: 1px solid var(--border); }
  .state-row { display: flex; align-items: center; gap: 8px; padding: 6px 12px; font-size: var(--fs-2xs); color: var(--text-2); }
  .state { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .info-btn { width: 20px; height: 20px; padding: 0; border-radius: 50%; font: italic 700 var(--fs-3xs)/1 Georgia, "Times New Roman", serif; color: var(--accent); border: 1px solid var(--accent); background: var(--surface); flex-shrink: 0; }
  .info-btn[aria-expanded="true"] { background: var(--accent); color: white; }
  .status-line { margin: 4px 0; color: var(--text-2); }
  .alert { margin: 0; padding: 2px 12px 6px; color: var(--danger); }
  .coverage-warn { display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 10px; margin: 2px 0; color: var(--warning); }
  /* #376: the (i) is a popover anchored under the state row (the sticky head
     is its containing block). It scrolls inside itself; the head never grows. */
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
  p { margin: 8px 0; overflow-wrap: anywhere; }
  ol { padding-left: 22px; }
  li { padding: 8px 0; border-bottom: 1px solid var(--border, #ddd); }
  /* Target text, in the target face (#286): under --font-ui a Gurmukhi line's
     danda was drawn from Vijaya, slanted, beside letters from Nirmala UI. */
  .evidence { font-family: var(--font-target); font-size: var(--fs-md); white-space: pre-wrap; }
  .severity, .category { margin-left: 8px; }
  .recheck { font-weight: 600; color: var(--warning); font-size: var(--fs-2xs); }
  .reference { font-size: var(--fs-3xs); opacity: .85; border-left: 2px solid var(--border); padding-left: 6px; }
  /* The section tabs sit under the state row and stay with it. */
  .panel-tabs { display: flex; gap: 2px; padding: 0 12px; border-top: 1px solid var(--border);
    background: var(--surface); border-bottom: 1px solid var(--border); overflow-x: auto; scrollbar-width: none;
    font-size: var(--fs-3xs); }
  .panel-tabs button { flex: 1 0 auto; border: 0; border-bottom: 2px solid transparent; border-radius: 0; background: none;
    padding: 8px 6px 6px; font-weight: 700; color: var(--text-2); white-space: nowrap; }
  /* #385: the book tab carries a name of any length and is the one that gives
     way at the column's minimum width -- one line, cut with an ellipsis, the
     full name in its title. The other tabs keep their width. */
  .panel-tabs .book-tab { flex-shrink: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .panel-tabs button:hover { color: var(--text); }
  .panel-tabs button[aria-selected="true"] { color: var(--accent); border-bottom-color: var(--accent); }
  /* #376: the one filter row, pinned under the tabs (#178). */
  .list-row { margin: 0; padding: 6px 12px; background: var(--surface); font-size: var(--fs-2xs); }
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
  .legend button { display: inline-flex; align-items: center; gap: 4px; font-size: var(--fs-3xs); padding: 2px 8px; }
  .legend button[aria-pressed="true"] { border-color: var(--accent); background: var(--accent-bg); }
  .legend .swatch { background: none; padding: 0 2px; font-size: var(--fs-3xs); }
  .legend .n { color: var(--text-3); font-variant-numeric: tabular-nums; }
  /* The cards: ReviewPanel's finding card, one per listed finding, with the
     verse's own actions (#487). */
  .cards { list-style: none; padding: 0; margin: 0; }
  .cards > li { border-bottom: 0; }
  .finding { border-top: 1px dashed var(--border); padding-top: 10px; margin-top: 10px; }
  .finding:first-child { border-top: none; padding-top: 0; margin-top: 0; }
  .verdict { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 8px; margin-bottom: 6px; }
  .ref { font-size: var(--fs-3xs); font-weight: 700; padding: 2px 7px; border-radius: 999px; border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); white-space: nowrap; }
  .ref:hover, .ref:focus-visible { border-color: var(--accent); color: var(--accent); outline: none; }
  .badge { font-size: var(--fs-2xs); font-weight: 700; padding: 3px 8px; border-radius: 5px; flex-shrink: 0; }
  .badge-wrong { background: var(--danger-bg); color: var(--danger); }
  .badge-review { background: var(--warning-bg); color: var(--warning); }
  .badge-decided { background: var(--success-bg); color: var(--success); text-transform: capitalize; }
  .check-id { font-size: var(--fs-xs); color: var(--text-3); min-width: 0; overflow-wrap: anywhere; }
  .engine-badge { font-size: var(--fs-3xs); font-weight: 700; text-transform: capitalize; color: var(--accent); background: var(--accent-bg); padding: 2px 7px; border-radius: 999px; flex-shrink: 0; }
  .engine-badge.where { text-transform: none; font-style: italic; }
  .explain { font-size: var(--fs-sm); color: var(--text-2); line-height: 1.6; margin: 0 0 8px; }
  .explain .message { margin-left: .4em; }
  .decision-row { display: flex; flex-wrap: wrap; gap: 6px; }
  .decision-row button { flex: 1 1 auto; padding: 7px; font-size: var(--fs-xs); font-weight: 700; border-radius: 6px; border: none; cursor: pointer; }
  .decision-row button:disabled { opacity: .55; cursor: not-allowed; }
  .ignore { background: #F5EBFC; color: #9333EA; }
  .flag { background: var(--flag-bg); color: var(--flag); }
  .edit-inline { background: var(--accent-bg); color: var(--accent); }
  .history-toggle { flex: 0 1 auto; }
  .sugg-tag { margin-left: 0.4em; color: var(--text-3); font-size: var(--fs-2xs); font-weight: 400; }
  .apply-row { display: flex; align-items: center; gap: 0; margin-top: 8px; }
  .apply-label { font-size: var(--fs-2xs); font-weight: 700; color: var(--text-2); margin-right: 8px; white-space: nowrap; }
  .apply-row button { flex: 1; padding: 5px 0; font-size: var(--fs-2xs); font-weight: 600; color: var(--text-2);
    background: var(--surface); border: 1px solid var(--border-strong); border-left-width: 0; border-radius: 0; cursor: pointer; }
  .apply-row button:first-of-type { border-left-width: 1px; border-radius: 6px 0 0 6px; }
  .apply-row button:last-of-type { border-radius: 0 6px 6px 0; }
  .apply-row button.on { background: var(--accent); border-color: var(--accent); color: #fff; }
  .action-notice { margin: 0 0 6px; font-size: var(--fs-xs); color: var(--text-3); }
  .action-notice.failed { color: var(--danger); }
  .none { color: var(--text-3); }
  .decided { margin-top: 12px; }
  .decided summary { cursor: pointer; font-weight: 700; color: var(--text-2); }
  .decided-card { opacity: .75; }
  /* #487: the pager, pinned to the bottom of the tab. */
  .paging { position: sticky; bottom: 0; z-index: 2; display: flex; align-items: center; flex-wrap: wrap; justify-content: space-between; gap: 6px 10px;
    padding: 6px 12px; background: var(--surface); border-top: 1px solid var(--border); font-size: var(--fs-2xs); }
  .paging.busy { opacity: .7; }
  .page-of { color: var(--text-2); white-space: nowrap; }
  .goto { display: inline-flex; align-items: center; gap: 4px; margin: 0; }
  .goto input { width: 52px; padding: 2px 4px; }
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
