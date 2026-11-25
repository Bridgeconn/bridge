<script lang="ts">
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";
  import "../alignmentCards.css";
  import LayoutMenu from "./LayoutMenu.svelte";
  import GridPicker from "./GridPicker.svelte";
  import GridToggle from "./GridToggle.svelte";
  import WordPanels from "./WordPanels.svelte";
  import WordPanel from "./WordPanel.svelte";
  import AlignmentResetControls from "./AlignmentResetControls.svelte";
  import { WORD_PANEL_PRESETS, crossPanelLayout } from "../wordPanels";
  import { edgeScrollStep } from "../alignmentLayout";
  import SourceSplitControls from "./SourceSplitControls.svelte";
  import AlignmentChapterReset from "./AlignmentChapterReset.svelte";
  // Cross-verse alignment page, slice 1 (#116): several verses of one
  // chapter side by side -- source tokens down the left, each verse's word
  // bank down the right, a gap overview across the top. In this slice a
  // drop is accepted only within the same verse and goes through the
  // existing alignment.realign / alignment.unalign; a drop across verses
  // records a Bridge-private cross-verse link (#117) in the workbench
  // database. The tC alignment data stays strictly verse-local throughout:
  // the linked source token's group stays empty and the target word stays
  // in its own verse's word bank; only the annotations change.
  import { onMount } from "svelte";
  import { bridge as apiBridge } from "../api/bridgeClient";
  import { get, derived } from "svelte/store";
  import { onDestroy } from "svelte";
  import { project as activeProject } from "../stores";
  import { bindReviewProject } from "../reviewProjectGuard";
  import { alignmentBusy, alignmentPinned } from "../alignmentWindow";
  import { alignmentBusyElsewhere, alignmentOpen, holdAlignmentBusy, openAlignment, showAlignmentTab, watchAlignmentChanges } from "../alignmentUi";
  const expectedPath = get(activeProject)?.path || "";
  const bridge = bindReviewProject(apiBridge, expectedPath);
  import { recheckVerse } from "../verseChecks";
  import {
    alignmentStatusByVerse, checkStatusByVerse, noteAlignmentChanged, settingsOpen, targetLang, verseKey, chapterVerseNums,
  } from "../stores";
  import { alignmentStatusLabel } from "../alignmentStatus";
  import type {
    AlignmentContext, AlignmentCounts, AlignmentToken, AutoAlignIssue, AutoAlignJobStatus, AutoAlignSuggestion,
    AutoAlignVerdict,
    CrossVerseLink, CrossVerseLinkResult, CrossVerseProposal, NullDecisionEntry, NullReason,
  } from "../types/finding";
  import {
    idFor, liveIssues, liveSuggestions, passLabel, placedByPass, providerProblem, relationTag, signatureOf,
    suggestionKey, suggestionsForSource, suggestionsForTarget, verdictView, windowJobError, windowProblem,
  } from "../autoAlign";
  import { createPointerDrag } from "../alignmentDrag";
  import { createMarquee } from "../marqueeSelect";
  import { askConfirmation } from "../confirmAction";
  import { BACKUPS_SHOWN, backupChange, backupLabel, backupTime } from "../alignmentBackups";
  import { syncVerseRows } from "../verseRowSync";
  import {
    alignedTargetsFor, bottomIdsAfterDrop, bottomIdsAfterStep, groupForSource, groupForTarget, occurrenceLabel as occurrence, unaccountedTargets,
    unrealizedSources, topIdsFor, sourceColumns, undoTargetId, type DropSlot,
  } from "../alignmentGroups";
  import { defaultRange, joinVerseId, rangeBetween, spanOf, splitVerseId, toggleVerse } from "../crossVerseRange";
  import { suggestCrossVerseRange, unionInChapterOrder } from "../crossVerseSuggest";
  import { SourceGlossCache } from "../lexiconGloss";
  import LexiconPopup from "./LexiconPopup.svelte";

  export let chapter: string;
  const verseNums = derived(chapterVerseNums, (chapters) => chapters[chapter] || []);
  /** The verse the page was opened on; the default range is this ±1. */
  export let verse: string;
  export let onClose: () => void;
  export let onDetach: (() => void) | null = null;
  export let onPin: (() => void) | null = null;
  export let standalone = false;
  /** Drawn inside the editor's Alignment tab (2026-11-15): see AlignmentModal. */
  export let embedded = false;
  // 2026-11-15: this page and the single-verse editor can be open together,
  // as two tabs: see AlignmentModal.
  const busyHolder = {};
  onDestroy(() => holdAlignmentBusy(busyHolder, false));
  /** Verses to start with instead of anchor ±1 (#118): the editor's
   *  multi-selection or a finding's references. */
  export let initialVerses: string[] = [];

  const BANK_NOTICE =
    "To link across verses, drop the word onto a source word of the other verse, not into its word bank.";
  const ALIGNED_NOTICE =
    "A word that is aligned in its own verse cannot also be linked to another verse. Remove it from its cell first.";

  let selection: string[] = initialVerses.length > 1
    ? unionInChapterOrder($verseNums, initialVerses)
    : defaultRange($verseNums, verse);
  if (selection.length === 0) selection = defaultRange($verseNums, verse);
  /** Verses the last Stage 6B run marked CROSS_VERSE that the picker added (#118). */
  let suggested: string[] = [];
  let contexts: Record<string, AlignmentContext> = {};
  let chapterStatus: AlignmentCounts | null = null;
  let reading: Record<string, string> = {};
  let loading = true;
  let busy = false;
  $: holdAlignmentBusy(busyHolder, busy || autoBusy || proposalsBusy);
  let error = "";
  /** The raw text behind a plain error (#243), shown under "Show details"
   *  only while `error` is still the message it explains. */
  let errorDetail: { message: string; raw: string } | null = null;
  let notice = "";
  // 2026-11-16 (Joel): a note is drawn over the foot of the tab and goes by
  // itself, as on the Word alignment tab; it was a row of the page.
  let noticeTimer: ReturnType<typeof setTimeout> | undefined;
  $: { clearTimeout(noticeTimer); if (notice) noticeTimer = setTimeout(() => (notice = ""), 5000); }
  onDestroy(() => clearTimeout(noticeTimer));
  // 2026-11-25 (Joel): an error goes by itself too, as in the Verses panel:
  // after ten seconds, held while it is pointed at, and its close button
  // clears it at once. It stayed until it was closed, so a refused drop
  // ("... is marked grammatical; clear that before aligning it") sat over the
  // foot of the tab for the rest of the session. Two kinds still stay: one
  // with "Show details" to open, and one that is all the page has to show
  // (the range could not be read).
  const ERROR_MS = 10000;
  let errorTimer: ReturnType<typeof setTimeout> | undefined;
  function holdError(): void { clearTimeout(errorTimer); errorTimer = undefined; }
  function scheduleErrorClear(text: string, pageShown: boolean, detail: { message: string; raw: string } | null): void {
    holdError();
    if (text && pageShown && detail?.message !== text) errorTimer = setTimeout(() => (error = ""), ERROR_MS);
  }
  $: scheduleErrorClear(error, ordered.length > 0, errorDetail);
  onDestroy(holdError);
  const crossTree = crossPanelLayout.tree;
  /** When set, both columns show only that verse's gaps. */
  let gapFilterVerse: string | null = null;
  let lexiconToken: AlignmentToken | null = null;
  let lexiconDirection: "ltr" | "rtl" = "rtl";
  // The picked-up words, as "verse|T001" keys (2026-11-16, Joel: several at
  // once, as on the Word alignment tab). A plain click picks one; Ctrl-click
  // adds or removes one; Shift-click takes the run from the last one; a box
  // drawn in a verse's word bank takes what it touches. They are always words
  // of ONE verse: a pick in another verse starts again. `anchor` is the last
  // word picked on its own, where a Shift-click starts.
  let picked: string[] = [];
  let anchor: string | null = null;
  // The English sense goes under the source word and the lemma moves into the
  // tooltip: a lemma is one more Greek/Hebrew string, and tells a reviewer who
  // does not read those scripts nothing. Cached across range changes, since a
  // verse that leaves and re-enters the range resolves the same entries.
  const glosses = new SourceGlossCache();
  let glossVersion = 0;
  let loadSequence = 0;
  /** Cross-verse suggestions (#139), loaded only on an explicit click. */
  let proposals: CrossVerseProposal[] = [];
  let proposalsBusy = false;
  let proposalError = "";
  let proposalsUnavailable = "";
  let suggestionsShown = false;
  /** `aiAvailable` is undefined until settings load, so "Align automatically"
   *  reads "checking" rather than flickering from disabled to enabled. */
  let aiAvailable: boolean | undefined = undefined;
  let dismissed = new Set<string>();
  /** #222: the last automatic pass on each verse, as stored by the engine. */
  let verdicts: Record<string, AutoAlignVerdict | null> = {};
  let autoBusy = false;
  let autoStage = "";
  /** What the last run in this session covered, for its notice and "Undo a verse". */
  let lastRun: { verses: string[]; usage: string; summary: string; mixed: boolean } | null = null;
  let usageLine = "";
  let dismissedAuto = new Set<string>();
  /** The "Not missing ▾" / "Not an addition ▾" menu, when open. */
  let menu: { side: "source" | "target"; verse: string; id: string; word: string } | null = null;
  /** The selection the current proposals were computed for, so a widened range
   *  is reported as stale rather than silently showing yesterday's answer. */
  let proposalsFor: string[] = [];

  $: span = spanOf($verseNums, selection);
  $: spanVerses = span ? rangeBetween($verseNums, span[0], span[1]) : [];
  $: ordered = selection.filter((v) => contexts[v]);
  $: totalGaps = ordered.reduce(
    (acc, v) => ({
      sourceUnmatched: acc.sourceUnmatched + contexts[v].gaps.sourceUnmatched,
      targetUnmatched: acc.targetUnmatched + contexts[v].gaps.targetUnmatched,
    }),
    { sourceUnmatched: 0, targetUnmatched: 0 },
  );
  $: visibleVerses = gapFilterVerse ? ordered.filter((v) => v === gapFilterVerse) : ordered;
  $: visibleProposals = proposals.filter((p) => !dismissed.has(proposalKey(p)));
  $: windowIssue = windowProblem(selection, $verseNums.filter((v) => v !== "front"));
  $: rangeIssues = ordered.flatMap((v) => liveIssues(contexts[v], verdicts[v]));
  $: rangeSuggestions = ordered.flatMap((v) => liveSuggestions(contexts[v], verdicts[v])
    .filter((s) => !dismissedAuto.has(suggestionKey(s))));
  $: proposalsStale = suggestionsShown && proposalsFor.join("␟") !== selection.join("␟");

  // The page is chapter-scoped, and no longer closes itself when the editor
  // moves to another chapter (2026-11-16, Joel): AlignmentHost gives it the
  // new chapter and verse, as it does the Word alignment tab; pinned, it stays.

  // Composite ids in the DOM: a draggable token is "verse|T001", a drop
  // column is "verse|H001", a word bank is the verse. The drop handler
  // compares the two verses to route same-verse vs cross-verse.
  // A drag that starts on a picked word carries the whole selection; one that
  // starts elsewhere supersedes it. `data-drop-slot` on an aligned card says
  // which card the drop landed on, so the words go before or after it and a
  // card dragged along its own cell is reordered (#410, here since 2026-11-16).
  const drag = createPointerDrag({
    onDragStart: (tokenId) => { if (!picked.includes(tokenId)) picked = []; },
    onDrop: ({ tokenId, column, bank, slot }) => {
      const keys = picked.includes(tokenId) ? picked : [tokenId];
      picked = [];
      if (column) dropOnColumn(keys, column, slot);
      else if (bank) dropOnBank(keys, bank);
    },
  });
  const dragState = drag.state;

  // A selection box in one verse's word bank. With Ctrl held, and the same
  // verse as what is picked, it adds; otherwise it replaces.
  let pickedBeforeMarquee: string[] = [];
  let marqueeVerse = "";
  const marquee = createMarquee({
    onStart: (additive) => { pickedBeforeMarquee = additive && picked.length && splitVerseId(picked[0]).verse === marqueeVerse ? picked : []; },
    onChange: (hits) => { picked = [...pickedBeforeMarquee, ...hits.filter((key) => !pickedBeforeMarquee.includes(key))]; },
    onEnd: (hits) => { if (hits.length) anchor = hits[hits.length - 1]; },
  });
  const marqueeState = marquee.state;
  function startMarquee(event: PointerEvent, v: string) {
    if (busy) return;
    marqueeVerse = v;
    marquee.start(event, event.currentTarget as Element);
  }

  // The panels scroll on their own (2026-11-16). While a word is dragged
  // inside the Source words panel, near its top or bottom edge, that panel
  // scrolls a few px per frame (edgeScrollStep); the Target words panel
  // follows it when the two are side by side (linkScroll).
  let dialogEl: HTMLElement | undefined;
  let edgeEl: HTMLElement | null = null;
  let edgeStep = 0, edgeRaf = 0;
  function trackEdge(event: PointerEvent): void {
    edgeEl = $dragState.tokenId && $dragState.moved ? dialogEl?.querySelector<HTMLElement>('[data-panel-body="source"]') ?? null : null;
    if (!edgeEl) { edgeStep = 0; return; }
    const r = edgeEl.getBoundingClientRect();
    const inside = event.clientX >= r.left && event.clientX < r.right && event.clientY >= r.top && event.clientY < r.bottom;
    edgeStep = inside ? edgeScrollStep(event.clientY, r.top, r.bottom) : 0;
    if (edgeStep && !edgeRaf) edgeRaf = requestAnimationFrame(edgeTick);
  }
  function edgeTick(): void {
    edgeRaf = 0;
    if (!edgeStep || !$dragState.tokenId || !edgeEl) return;
    edgeEl.scrollTop += edgeStep;
    edgeRaf = requestAnimationFrame(edgeTick);
  }

  // #495 keeps a verse level on both sides by giving each verse block its
  // partner's height (verseRowSync). The two columns now scroll in their own
  // panels, so while the panels stand side by side they are scrolled
  // together: scrolling one moves the other to the same place.
  const linked: HTMLElement[] = [];
  let scrolling: HTMLElement | null = null;
  function linkScroll(node: HTMLElement) {
    const body = node.closest<HTMLElement>("[data-panel-body]");
    if (!body) return {};
    const onScroll = () => {
      if (scrolling && scrolling !== body) return;
      const other = linked.find((el) => el !== body);
      if (!other) return;
      const a = body.getBoundingClientRect(), b = other.getBoundingClientRect();
      if (Math.abs(a.top - b.top) > 4 || !(a.right <= b.left + 1 || b.right <= a.left + 1)) return;
      scrolling = body;
      other.scrollTop = body.scrollTop;
      requestAnimationFrame(() => { scrolling = null; });
    };
    linked.push(body);
    body.addEventListener("scroll", onScroll, { passive: true });
    return { destroy() { body.removeEventListener("scroll", onScroll); const at = linked.indexOf(body); if (at >= 0) linked.splice(at, 1); } };
  }
  $: ghostLabel = $dragState.tokenId ? (picked.includes($dragState.tokenId) ? picked : [$dragState.tokenId]).map(tokenWord).join(" ") : "";

  onMount(() => drag.attach(window));
  onMount(() => marquee.attach(window));
  onMount(() => { void loadThenSuggest(); });
  // Whether an AI proposal is even offered is a settings question, not a project
  // one, and a failure here must leave the offline path untouched -- so it is its
  // own mount, and a throw just means "no AI button".
  async function readAiAvailable() {
    try {
      const settings = await bridge.getSettings();
      aiAvailable = Boolean(settings?.aiReady ?? settings?.hasApiKey);
    } catch {
      aiAvailable = false;
    }
  }
  onMount(readAiAvailable);
  // #506: Settings is where a key is saved or a ChatGPT sign-in made. Ask again
  // when it closes, or the AI buttons stay disabled until this page is reopened.
  let settingsWasOpen = false;
  $: {
    if (settingsWasOpen && !$settingsOpen) void readAiAvailable();
    settingsWasOpen = $settingsOpen;
  }

  /** Load the range, then widen it with the last analysis's cross-verse
   *  verses if the page was opened on the default range. The suggestion is
   *  advisory: it never narrows the range and the picker stays manual. */
  async function loadThenSuggest() {
    await load();
    if (initialVerses.length > 1) return;
    const suggestion = await suggestCrossVerseRange(chapter);
    if (!suggestion) return;
    const added = suggestion.verses.filter((v) => !selection.includes(v) && $verseNums.includes(v));
    if (added.length === 0) return;
    suggested = added;
    selection = unionInChapterOrder($verseNums, selection, added);
    await load();
  }

  function resetToDefaultRange() {
    suggested = [];
    selection = defaultRange($verseNums, verse);
    gapFilterVerse = null;
    void load();
  }

  function tokenWord(compositeId: string): string {
    const { verse: v, id } = splitVerseId(compositeId);
    return contexts[v]?.bottomTokens.find((t) => t.id === id)?.word ?? "";
  }

  // A verse of the range was written somewhere else (the Word alignment tab,
  // the verse editor): read the range again, quietly, once nothing is saving.
  let changedOutside = false;
  onDestroy(watchAlignmentChanges(() => selection.map((v) => verseKey(chapter, v)), () => busy || autoBusy || proposalsBusy,
    () => { changedOutside = true; }));
  $: if (changedOutside && !$alignmentBusy && !loading) { changedOutside = false; void load(true); }

  async function load(quiet = false) {
    const sequence = ++loadSequence;
    if (!quiet) loading = true;
    error = "";
    try {
      const range = await bridge.getAlignmentRange(chapter, selection);
      void Promise.all(selection.map(async (v) => { try { const data = await bridge.getVerse(chapter, v); return [v, data.display?.plain ?? data.text ?? ""] as const; } catch { return [v, ""] as const; } })).then((lines) => { if (sequence === loadSequence) reading = Object.fromEntries(lines); });
      if (sequence !== loadSequence) return; // a newer selection superseded this load
      const next: Record<string, AlignmentContext> = {};
      for (const context of range.verses) next[context.verse] = context;
      contexts = next;
      chapterStatus = range.chapterStatus;
      void loadMeanings(range.verses.flatMap((c) => c.topTokens));
      void loadVerdicts(range.verses, sequence);
    } catch (value) {
      if (sequence !== loadSequence) return;
      error = value instanceof Error ? value.message : String(value);
    } finally {
      if (sequence === loadSequence) loading = false;
    }
  }

  /** The stored verdict of each verse an automatic pass has run on (#222).
   *  Cheap reads, and only for verses whose context says there is one. */
  async function loadVerdicts(list: AlignmentContext[], sequence: number) {
    const next: Record<string, AutoAlignVerdict | null> = {};
    for (const context of list) {
      if (!context.autoAlign) { next[context.verse] = null; continue; }
      try {
        next[context.verse] = (await bridge.autoAlignVerdict(chapter, context.verse)).verdict;
      } catch {
        next[context.verse] = null;
      }
    }
    if (sequence === loadSequence) verdicts = { ...verdicts, ...next };
  }

  /** Ask the window twice and write what both passes agree on (#219). One
   *  click, never on open or on a range change; the notice reports what was
   *  placed and what is left for the reviewer. */
  async function runAuto() {
    if (autoBusy || busy || alignmentBusyElsewhere(busyHolder) || windowIssue || !aiAvailable) return;
    autoBusy = true;
    busy = true;
    error = "";
    notice = "";
    errorDetail = null;
    // The window is a job (#242): the label follows the pass its status
    // reports (#243), and the last status keeps the window's own error.
    autoStage = passLabel(null);
    let lastStatus: AutoAlignJobStatus | null = null;
    try {
      const wanted = [...selection];
      const result = await bridge.autoAlignWindow(chapter, wanted, true, (status) => {
        lastStatus = status;
        autoStage = passLabel(status);
      });
      if (result.unavailable) {
        error = result.unavailable.message;
        return;
      }
      for (const item of result.results) {
        verdicts = {
          ...verdicts,
          [item.verse]: {
            chapter, verse: item.verse, verdict: item.verdict, runId: result.runId,
            applyRequested: true, issues: item.issues, suggestions: item.suggestions,
            applied: item.applied, window: result.verses, createdAt: "", usage: result.usage,
          },
        };
        contexts = { ...contexts, [item.verse]: item.context };
      }
      const placed = result.results.reduce((n, r) => n + r.applied.groups.length + r.applied.links.length + r.applied.nulls.length, 0);
      const omissions = result.results.reduce((n, r) => n + r.issues.filter((i) => i.kind === "POSSIBLE_OMISSION").length, 0);
      const additions = result.results.reduce((n, r) => n + r.issues.filter((i) => i.kind === "POSSIBLE_ADDITION").length, 0);
      const suggested = result.results.reduce((n, r) => n + r.suggestions.length, 0);
      const clean = result.results.filter((r) => r.verdict === "ALIGNED_CLEAN").length;
      const parts = [
        `${clean} of ${result.results.length} verse${result.results.length === 1 ? "" : "s"} aligned with nothing left`,
        `${placed} group${placed === 1 ? "" : "s"}, link${placed === 1 ? "" : "s"} and decision${placed === 1 ? "" : "s"} written`,
        suggested ? `${suggested} suggestion${suggested === 1 ? "" : "s"} for you` : "",
        omissions ? `${omissions} possible omission${omissions === 1 ? "" : "s"}` : "",
        additions ? `${additions} possible addition${additions === 1 ? "" : "s"}` : "",
      ].filter(Boolean);
      const usage = result.usage;
      usageLine = usage ? `Last run: ${usage.calls} requests · ${usage.totalTokens.toLocaleString()} tokens · about $${usage.estimatedCostUSD.toFixed(2)}` : "";
      lastRun = {
        verses: result.verses, usage: usageLine,
        summary: `${clean === result.results.length ? "✓ " : ""}${parts.join(", ")}.`,
        mixed: clean !== result.results.length,
      };
      chapterStatus = result.results[result.results.length - 1]?.context.chapterStatus ?? chapterStatus;
      for (const item of result.results) await refreshChecks(item.verse, item.context, "");
      notice = "";
      error = result.failures?.length ? `Some agreed changes were not applied: ${result.failures.join("; ")}` : "";
    } catch (value) {
      const raw = windowJobError(lastStatus, value instanceof Error ? value.message : String(value));
      const plain = providerProblem(raw);
      error = plain ?? raw;
      errorDetail = plain ? { message: plain, raw } : null;
    } finally {
      autoStage = "";
      autoBusy = false;
      busy = false;
    }
  }

  async function revertVerse(event: Event) {
    const select = event.currentTarget as HTMLSelectElement;
    const v = select.value;
    select.value = "";
    if (!v || busy || alignmentBusyElsewhere(busyHolder)) return;
    busy = true;
    error = "";
    try {
      const result = await bridge.autoAlignRevert(chapter, v);
      // A reverted link reaches its other verse, which the result does not
      // name: every verse of the window the pass ran on counts as written (#291).
      for (const other of verdicts[v]?.window ?? []) {
        if (other !== v) noteAlignmentChanged(verseKey(chapter, other));
      }
      verdicts = { ...verdicts, [v]: null };
      contexts = { ...contexts, [v]: result.context };
      await refreshChecks(v, result.context, "");
      notice = result.skipped.length
        ? `Restored v.${v}. Left alone, because you changed them after the pass: ${result.skipped.length}.`
        : `Restored v.${v} to how it was before the automatic pass.`;
      // A reverted link reaches its other verse too.
      await load();
    } catch (value) {
      error = value instanceof Error ? value.message : String(value);
    } finally {
      busy = false;
    }
  }

  /** ✓ on a suggestion: the same writers a drag would use, so a refusal
   *  (the word got a home meanwhile) surfaces exactly as it would there. */
  async function acceptSuggestion(s: AutoAlignSuggestion) {
    if (s.kind === "null" && s.token) {
      const context = contexts[s.token.verse];
      const id = context && idFor(context, s.token.side, s.token.signature);
      if (!id) return;
      await setNull(s.token.side, s.token.verse, id, s.reason as NullReason, s.note);
      return;
    }
    if (!s.source || !s.target) return;
    const sourceContext = contexts[s.source.verse];
    const targetContext = contexts[s.target.verse];
    const topId = sourceContext && idFor(sourceContext, "source", s.source.signature);
    const bottomId = targetContext && idFor(targetContext, "target", s.target.signature);
    if (!topId || !bottomId) {
      error = "That word is not in its verse any more. Run the automatic pass again.";
      return;
    }
    if (s.source.verse === s.target.verse) {
      alignWithin(s.source.verse, topId, [bottomId]);
    } else {
      linkAcross(s.source.verse, topId, s.target.verse, bottomId);
    }
  }

  function dismissSuggestion(s: AutoAlignSuggestion) {
    // Session-only, like the corpus suggestions (#140 persists dismissals).
    dismissedAuto = new Set([...dismissedAuto, suggestionKey(s)]);
  }

  async function setNull(side: "source" | "target", v: string, id: string, reason: NullReason, note = "") {
    menu = null;
    await mutate(v, async () => (await bridge.nullSet(chapter, v, side, id, reason, note)).context,
      `Marked ${reason.toLowerCase()}.`);
  }

  function clearNull(v: string, entry: NullDecisionEntry) {
    void mutate(v, async () => (await bridge.nullClear(entry.decisionId)).context, "Decision cleared.");
  }

  // Every helper the template calls takes the state it reads as an argument:
  // Svelte 4 re-runs a template expression only when a variable *named in it*
  // changes, so a helper that read `verdicts` or `visibleProposals` from the
  // closure would never refresh its cell.
  function issueFor(
    context: AlignmentContext, verdict: AutoAlignVerdict | null | undefined, side: "source" | "target", token: AlignmentToken,
  ): AutoAlignIssue | undefined {
    const signature = signatureOf(token);
    return liveIssues(context, verdict).find((i) => i.side === side && i.signature === signature);
  }

  function nullFor(context: AlignmentContext, side: "source" | "target", id: string): NullDecisionEntry | undefined {
    return context.nullDecisions[side].find((entry) => entry.id === id);
  }

  function sourceSuggestions(list: AutoAlignSuggestion[], v: string, token: AlignmentToken): AutoAlignSuggestion[] {
    return suggestionsForSource(list, v, signatureOf(token));
  }

  function targetSuggestions(list: AutoAlignSuggestion[], v: string, token: AlignmentToken): AutoAlignSuggestion[] {
    return suggestionsForTarget(list, v, signatureOf(token));
  }

  function corpusFor(list: CrossVerseProposal[], v: string, topId: string): CrossVerseProposal[] {
    return list.filter((p) => p.source.verse === v && p.source.topId === topId);
  }

  /** "ai" when the last pass wrote this group, plus its shape when not 1:1. */
  function groupTag(verdict: AutoAlignVerdict | null | undefined, context: AlignmentContext, topId: string): string {
    const group = context.groups.find((g) => g.topIds.includes(topId));
    if (!group) return "";
    const top = context.topTokens.find((t) => t.id === topId);
    const bottoms = group.bottomIds.map((id) => context.bottomTokens.find((t) => t.id === id)).filter(Boolean) as AlignmentToken[];
    const ai = top && placedByPass(verdict, signatureOf(top), bottoms.map(signatureOf)) ? "ai" : "";
    return [ai, relationTag(group.topIds.length, group.bottomIds.length)].filter(Boolean).join(" · ");
  }

  function linkTag(context: AlignmentContext, link: CrossVerseLink): string {
    const group = context.crossVerseGroups.find((g) => g.linkIds.includes(link.id));
    return group ? relationTag(group.sources.length, group.targets.length) : "";
  }

  function openMenu(side: "source" | "target", v: string, token: AlignmentToken) {
    menu = { side, verse: v, id: token.id, word: token.word };
  }

  /** Suggestions are loaded on an explicit click, never with the range (#139).
   *  The first call in a session pays the one-time Uroman/Smart-Edit-Distance
   *  table load (~2 s) plus a scan of every completed verse in the collection;
   *  paying that silently on every range change would make the picker feel
   *  broken. Steady state afterwards is milliseconds. */
  async function loadProposals() {
    if (proposalsBusy) return;
    proposalsBusy = true;
    proposalError = "";
    try {
      const wanted = [...selection];
      const result = await bridge.crossVersePropose(chapter, wanted);
      proposals = result.proposals;
      proposalsFor = wanted;
      proposalsUnavailable = result.unavailable?.message ?? "";
      suggestionsShown = true;
    } catch (value) {
      proposalError = value instanceof Error ? value.message : String(value);
    } finally {
      proposalsBusy = false;
    }
  }

  function proposalKey(proposal: CrossVerseProposal): string {
    const { source, target } = proposal;
    return `${source.verse}|${source.topId}|${target.verse}|${target.bottomId}`;
  }

  function dismissProposal(proposal: CrossVerseProposal) {
    // Session-local only in this slice; persisting it is #140, which needs a
    // workbench schema bump.
    dismissed = new Set([...dismissed, proposalKey(proposal)]);
  }

  /** Accepting is an ordinary cross-verse link with the ids the proposal
   *  carries -- there is no separate apply path, and nothing was written
   *  until this click. */
  async function acceptProposal(proposal: CrossVerseProposal) {
    const { source, target } = proposal;
    await mutateCross(
      () => bridge.crossVerseLink(
        { chapter, verse: source.verse, topId: source.topId },
        { chapter, verse: target.verse, bottomId: target.bottomId },
      ),
      `Linked ${source.word} (${chapter}:${source.verse}) to ${target.word} (${chapter}:${target.verse}).`,
    );
    // Only after the link actually succeeded: a refused link (the word was
    // aligned underneath us, the text changed) must leave the suggestion on
    // screen with the error, not silently swallow it.
    if (error) return;
    dismissProposal(proposal);
    await loadProposals();
  }

  function evidenceSummary(proposal: CrossVerseProposal): string {
    const parts: string[] = [];
    for (const item of proposal.evidence) {
      if (item.rawScore <= 0) continue;
      if (item.kind === "STRONGS_PRECEDENT" && item.jointCount) {
        parts.push(`this lemma rendered "${proposal.target.word}" ${item.jointCount}× in completed verses`);
      } else if (item.kind === "SURFACE_PRECEDENT" && item.jointCount) {
        parts.push(`this exact form paired ${item.jointCount}×`);
      } else if (item.kind === "PHONETIC") {
        parts.push("the two words sound alike when romanized");
      } else if (item.kind === "PROXIMITY") {
        // rawScore is 1/distance, so only 1 means the verse next door.
        parts.push(item.rawScore === 1 ? "the verse next door" : "a nearby verse");
      } else if (item.kind === "MODEL_PICK") {
        // The model's own sentence, verbatim. It is the only evidence line a
        // reviewer who reads neither original language can check for themselves,
        // so it leads -- and it is attributed, never presented as a measurement.
        parts.unshift(item.reason ? `the AI says: ${item.reason}` : "the AI picked this pairing");
      }
    }
    return parts.join(" · ");
  }

  async function loadMeanings(tokens: AlignmentToken[]) {
    await glosses.load(tokens);
    glossVersion = glosses.version;
  }

  // `glossVersion` is read, not used, so Svelte re-invokes these once the
  // lexicon lookups resolve.
  function sourceGloss(token: AlignmentToken, _version: number): string {
    return glosses.cardGlossFor(token);
  }

  // The hint on a source word: the lemma, its number and a short meaning.
  // The whole lexicon entry is long, and is one click away (LexiconPopup).
  function sourceHint(token: AlignmentToken, _version: number): string {
    const identity = [(token.lemma ?? "").trim(), token.strong].filter(Boolean).join(" · ");
    const short = glosses.glossFor(token).short;
    return [[identity, short].filter(Boolean).join(": "), "Click for the full entry"].filter(Boolean).join(". ");
  }

  // ---- range picker -------------------------------------------------------

  function setSpan(from: string, to: string) {
    const next = rangeBetween($verseNums, from, to);
    if (next.length === 0) return;
    suggested = [];
    selection = next;
    gapFilterVerse = null;
    void load();
  }

  function onFromChange(from: string) {
    setSpan(from, frame[frame.length - 1] ?? span?.[1] ?? from);
  }

  function onToChange(to: string) {
    setSpan(frame[0] ?? span?.[0] ?? to, to);
  }

  // 2026-11-16 (Joel): automatic alignment, link suggestions and the chapter
  // reset are one menu on the bar (they were a row of buttons under it). The
  // menu is kept mounted while closed: the chapter reset in it looks for an
  // interrupted job when the page opens.
  let aiOpen = false, aiPlace = "";
  let aiButton: HTMLButtonElement | undefined, aiEl: HTMLElement | undefined;
  let chapterReset: AlignmentChapterReset | undefined;
  let chapterJob = { running: false, resumable: false, text: "", error: "" };
  // A stable function that changes the state only when it differs: the reset
  // reports whenever it re-renders, and a new state re-renders it.
  function setChapterJob(value: typeof chapterJob): void {
    if (value.running !== chapterJob.running || value.resumable !== chapterJob.resumable || value.text !== chapterJob.text || value.error !== chapterJob.error) chapterJob = value;
  }
  function chapterResetChanged(values: AlignmentContext[]): void {
    for (const value of values) if (value.chapter === chapter) contexts = { ...contexts, [value.verse]: value };
  }
  const setBusy = (value: boolean): void => { busy = value; };
  function toggleAi(): void {
    if (aiOpen || !aiButton) { aiOpen = false; return; }
    const r = aiButton.getBoundingClientRect();
    aiPlace = `top:${r.bottom + 4}px;right:${Math.max(6, window.innerWidth - r.right)}px;max-height:${Math.max(180, window.innerHeight - r.bottom - 16)}px`;
    aiOpen = true;
  }
  function onAiOutside(event: Event): void {
    const target = event.target as Node;
    if (aiOpen && !aiEl?.contains(target) && !aiButton?.contains(target)) aiOpen = false;
    if (moreOpen && !moreEl?.contains(target) && !moreButton?.contains(target)) moreOpen = false;
  }
  function onAiClick(event: Event): void {
    if ((event.target as HTMLElement).closest("button")) aiOpen = false;
  }

  // Which verses of the span are shown (2026-11-16, Joel): the Verses
  // panel's grid, in place of the row of chips. The last one cannot be
  // switched off.
  // `frame` is the From to To range the grid offers. It follows the range,
  // except while a verse is switched off or on in the grid: switching off
  // the first or last verse must not shrink the range, or it could not be
  // switched back on.
  let frame: string[] = [];
  let keepFrame = false;
  $: { selection; const next = spanVerses; if (keepFrame && frame.length) keepFrame = false; else frame = next; }
  function toggleShown(v: string) {
    const next = toggleVerse($verseNums, selection, v);
    if (next.length === selection.length) return;
    keepFrame = true;
    selection = next;
    if (gapFilterVerse && !next.includes(gapFilterVerse)) gapFilterVerse = null;
    void load();
  }

  function toggleGapFilter(v: string) {
    gapFilterVerse = gapFilterVerse === v ? null : v;
  }

  // ---- mutations (same-verse only in this slice) --------------------------

  async function refreshChecks(v: string, updated: AlignmentContext, message: string) {
    if (expectedPath && get(activeProject)?.path !== expectedPath) return;
    contexts = { ...contexts, [v]: updated };
    chapterStatus = updated.chapterStatus;
    const key = verseKey(chapter, v);
    alignmentStatusByVerse.update((values) => ({ ...values, [key]: updated.status }));
    // Same-verse saves, null decisions, both ends of a link or unlink, each
    // verse of an automatic window and a revert all land here (#291).
    noteAlignmentChanged(key);
    checkStatusByVerse.update((values) => ({ ...values, [key]: "pending" }));
    try {
      // Only the alignment checks, as AlignmentModal does after a save: the
      // verse's other findings are kept (#251), Greek Room is on demand (#252).
      await recheckVerse(chapter, v, ["alignment"], { expectedPath });
      // `message` is empty when the caller reports its own aggregate result
      // (the AI auto-link batch, #146), so join rather than interpolate --
      // otherwise every notice starts with a stray space.
      if (expectedPath && get(activeProject)?.path !== expectedPath) return;
      notice = [message, `The alignment checks for ${chapter}:${v} are current.`]
        .filter(Boolean).join(" ");
    } catch (value) {
      if (expectedPath && get(activeProject)?.path !== expectedPath) return;
      checkStatusByVerse.update((values) => ({ ...values, [key]: "failed" }));
      error = [message, `The save succeeded, but rechecking failed: ${value instanceof Error ? value.message : String(value)}`]
        .filter(Boolean).join(" ");
    }
  }

  async function mutate(v: string, action: () => Promise<AlignmentContext>, message: string) {
    if (busy || alignmentBusyElsewhere(busyHolder)) return;
    busy = true;
    error = "";
    notice = "";
    try {
      await refreshChecks(v, await action(), message);
    } catch (value) {
      error = value instanceof Error ? value.message : String(value);
    } finally {
      busy = false;
    }
  }

  // Several words placed together are one realign call: one history row, one
  // undo step. `at` is the card the drop landed on, when it landed on one.
  function alignWithin(v: string, topId: string, bottomIds_: string[], at: DropSlot | null = null) {
    const context = contexts[v];
    if (!context) return;
    const bottomIds = bottomIdsAfterDrop(context, topId, bottomIds_, at);
    if (!bottomIds) return; // already in this column, in place
    const moved = bottomIds.length - (groupForSource(context, topId)?.bottomIds.length ?? 0);
    void mutate(v, () => bridge.realignWords(chapter, v, topIdsFor(context, topId), bottomIds, context.alignment),
      moved > 1 ? `${moved} words placed together.` : moved === 0 ? "Word order changed." : "Alignment saved.");
  }

  // The Word alignment tab's join and split (#207), for one verse of the
  // range: "Join" folds a column into the one before it, "Split" takes the
  // last source word out again. A source word with a cross-verse link has
  // its home in another verse, so a join of one is refused before the click,
  // with the reason in the hint. Neither a join nor a split needs a target
  // word (2026-11-18, Joel and the team).
  type SourceRow = AlignmentToken & { members: AlignmentToken[] };
  function joinProblem(context: AlignmentContext, previous: SourceRow, current: SourceRow): string {
    if ([...previous.members, ...current.members].some((member) => linksForSource(context, member.id).length > 0)) return "Remove the cross-verse link first, then join";
    return "";
  }
  function joinWithPrevious(v: string, index: number) {
    const context = contexts[v];
    if (!context || index <= 0) return;
    const rows = sourceRows(context);
    const previous = rows[index - 1], current = rows[index];
    if (!previous || !current || joinProblem(context, previous, current)) return;
    const bottomIds = [...alignedTargetsFor(context, previous.id), ...alignedTargetsFor(context, current.id)].map((token) => token.id);
    void mutate(v, () => bridge.realignWords(chapter, v, [...previous.members, ...current.members].map((member) => member.id), bottomIds, context.alignment), "Source words joined.");
  }
  // 2026-11-17 (Joel): split at the seam that was clicked, as on the Word
  // alignment tab: the words before it keep the target words, the ones after
  // it become their own cell in place, so the source order never changes.
  function splitAt(v: string, memberIds: string[], place: number) {
    const context = contexts[v];
    const group = context && groupForSource(context, memberIds[0]);
    if (!context || !group || place <= 0 || place >= memberIds.length) return;
    void mutate(v, () => bridge.realignWords(chapter, v, memberIds.slice(0, place), [...group.bottomIds], context.alignment), "Source words split.");
  }

  // Undo and the backups of one verse, as on the Word alignment tab (#122):
  // undo names the newest edit not yet undone; a backup is asked about first.
  function undoVerse(v: string) {
    const context = contexts[v];
    const id = context ? undoTargetId(context.history) : null;
    if (!context || !id) return;
    void mutate(v, () => bridge.restoreAlignment(chapter, v, id, context.alignment), `Last alignment change in ${chapter}:${v} undone.`);
  }

  // 2026-11-16 (Joel): the bar has the Word alignment tab's Undo and its
  // "more" menu. This page shows several verses, so:
  // - Undo steps back the newest change among the verses in the range (its
  //   hint names the verse);
  // - the menu holds the chapter reset, each verse's reset, and the newest
  //   backups of the range, each named by its verse;
  // - the status beside From and To is the range's: one verse reads as on
  //   the Word alignment tab, several as a count of each state.
  $: undoNext = ordered
    .map((v) => { const id = undoTargetId(contexts[v].history); const entry = contexts[v].history.find((item) => item.id === id); return entry ? { verse: v, timestamp: entry.timestamp } : null; })
    .filter((value): value is { verse: string; timestamp: string } => Boolean(value))
    .sort((a, b) => (a.timestamp < b.timestamp ? 1 : a.timestamp > b.timestamp ? -1 : 0))[0] ?? null;
  $: rangeBackups = ordered
    .flatMap((v) => contexts[v].history.map((item) => ({ verse: v, item })))
    .sort((a, b) => (a.item.timestamp < b.item.timestamp ? 1 : a.item.timestamp > b.item.timestamp ? -1 : 0))
    .slice(0, BACKUPS_SHOWN);
  $: rangeStatus = (["invalid", "partial", "untouched", "complete_cross_verse", "complete"] as const)
    .map((status) => ({ status, count: ordered.filter((v) => contexts[v].status === status).length }))
    .filter((entry) => entry.count > 0);
  let moreOpen = false, morePlace = "";
  let moreButton: HTMLButtonElement | undefined, moreEl: HTMLElement | undefined;
  let pendingResets: Record<string, boolean> = {};
  $: resetPending = ordered.some((v) => pendingResets[v]);
  function setPendingReset(v: string, value: boolean): void {
    if (Boolean(pendingResets[v]) !== value) pendingResets = { ...pendingResets, [v]: value };
  }
  function toggleMore(): void {
    if (moreOpen || !moreButton) { moreOpen = false; return; }
    const r = moreButton.getBoundingClientRect();
    morePlace = `top:${r.bottom + 4}px;right:${Math.max(6, window.innerWidth - r.right)}px;max-height:${Math.max(180, window.innerHeight - r.bottom - 16)}px`;
    moreOpen = true;
  }
  function onMoreClick(event: Event): void {
    if ((event.target as HTMLElement).closest("button")) moreOpen = false;
  }
  const setError = (message: string): void => { error = message; };
  async function restoreVerseBackup(v: string, item: { id: string; timestamp: string; operation: string }) {
    if (!contexts[v] || busy) return;
    const ok = await askConfirmation({ title: `Restore this backup of ${chapter}:${v}?`,
      body: `The alignment of this verse goes back to how it was ${backupChange(item.operation)}: ${backupTime(item.timestamp)}.`,
      confirmLabel: "Go back to this version" });
    const context = contexts[v];
    if (!ok || !context) return;
    void mutate(v, () => bridge.restoreAlignment(chapter, v, item.id, context.alignment), "Selected alignment backup restored.");
  }

  // 2026-11-16 (Joel): the Word alignment tab's earlier / later, here too: a
  // word in a cell that holds several moves one place. The same realign call
  // as a drop, within its own verse.
  function stepWithinCell(v: string, topId: string, bottomId: string, delta: -1 | 1) {
    const context = contexts[v];
    if (!context) return;
    const bottomIds = bottomIdsAfterStep(context, topId, bottomId, delta);
    if (!bottomIds) return;
    void mutate(v, () => bridge.realignWords(chapter, v, topIdsFor(context, topId), bottomIds, context.alignment), "Word order changed.");
  }

  // The aligned ones among `bottomIds` go back in one unalign call.
  function returnToBank(v: string, bottomIds: string | string[]) {
    const context = contexts[v];
    if (!context) return;
    const aligned = (Array.isArray(bottomIds) ? bottomIds : [bottomIds]).filter((id) => groupForTarget(context, id));
    if (aligned.length === 0) return;
    void mutate(v, () => bridge.unalignWords(chapter, v, aligned, context.alignment),
      aligned.length > 1 ? `${aligned.length} words returned to the word bank.` : "Returned to word bank.");
  }

  /** A cross-verse link or unlink returns both verses' contexts; each is
   *  patched in and rechecked, exactly like a same-verse save. */
  async function mutateCross(action: () => Promise<CrossVerseLinkResult>, message: string) {
    if (busy || alignmentBusyElsewhere(busyHolder)) return;
    busy = true;
    error = "";
    notice = "";
    try {
      const result = await action();
      await refreshChecks(result.source.verse, result.source, message);
      await refreshChecks(result.target.verse, result.target, message);
    } catch (value) {
      error = value instanceof Error ? value.message : String(value);
    } finally {
      busy = false;
    }
  }

  function linkAcross(sourceVerse: string, topId: string, targetVerse: string, bottomId: string) {
    void mutateCross(
      () => bridge.crossVerseLink(
        { chapter, verse: sourceVerse, topId },
        { chapter, verse: targetVerse, bottomId },
      ),
      "Cross-verse link saved.",
    );
  }

  /** Several words of one verse dropped on a source word of another: one
   *  link per word, in turn (the engine folds them into one group between
   *  the two verses). A failure part way keeps what was linked and says so. */
  async function linkManyAcross(sourceVerse: string, topId: string, targetVerse: string, bottomIds: string[]) {
    if (busy || alignmentBusyElsewhere(busyHolder)) return;
    busy = true;
    error = "";
    notice = "";
    let last: CrossVerseLinkResult | null = null;
    let done = 0;
    let failure = "";
    try {
      for (const bottomId of bottomIds) {
        last = await bridge.crossVerseLink({ chapter, verse: sourceVerse, topId }, { chapter, verse: targetVerse, bottomId });
        contexts = { ...contexts, [last.source.verse]: last.source, [last.target.verse]: last.target };
        done += 1;
      }
    } catch (value) {
      failure = value instanceof Error ? value.message : String(value);
    }
    try {
      if (last) {
        const message = `${done} word${done === 1 ? "" : "s"} linked across verses.`;
        await refreshChecks(last.source.verse, last.source, message);
        await refreshChecks(last.target.verse, last.target, message);
      }
      if (failure) error = done ? `${done} of ${bottomIds.length} words were linked. ${failure}` : failure;
    } finally {
      busy = false;
    }
  }

  function unlink(link: CrossVerseLink) {
    void mutateCross(() => bridge.crossVerseUnlink(link.id), "Cross-verse link removed.");
  }

  function linksForSource(context: AlignmentContext, topId: string): CrossVerseLink[] {
    return context.crossVerseLinks.filter((link) => link.sourceTopId === topId);
  }

  function linkForBottom(context: AlignmentContext, bottomId: string): CrossVerseLink | undefined {
    return context.crossVerseLinks.find((link) => link.targetBottomId === bottomId && link.state === "active");
  }

  /** Routes the picked tokens ("verse|T001", all of one verse) dropped on a
   *  column ("verse|H001"): the same verse realigns through tC, another verse
   *  records Bridge links. `slot` is the aligned card the drop landed on. */
  function dropOnColumn(keys: string[], columnKey: string, slot: { value: string; after: boolean } | null = null) {
    if (keys.length === 0) return;
    const column = splitVerseId(columnKey);
    const tokens = keys.map(splitVerseId);
    const v = tokens[0].verse;
    const ids = tokens.filter((token) => token.verse === v).map((token) => token.id);
    if (v !== column.verse) {
      const context = contexts[v];
      if (context && ids.some((id) => groupForTarget(context, id))) { error = ""; notice = ALIGNED_NOTICE; return; }
      if (ids.length === 1) linkAcross(column.verse, column.id, v, ids[0]);
      else void linkManyAcross(column.verse, column.id, v, ids);
      return;
    }
    const at = slot ? splitVerseId(slot.value) : null;
    alignWithin(v, column.id, ids, at && at.verse === v && slot ? { id: at.id, after: slot.after } : null);
  }

  function dropOnBank(keys: string[], bankVerse: string) {
    if (keys.length === 0) return;
    const v = splitVerseId(keys[0]).verse;
    if (v !== bankVerse) {
      error = "";
      notice = BANK_NOTICE;
      return;
    }
    returnToBank(v, keys.map((key) => splitVerseId(key).id));
  }

  /** The words of verse `v` that can be picked, in verse order: every word
   *  but one a cross-verse link or a "no counterpart" decision accounts for. */
  function pickable(v: string): string[] {
    const context = contexts[v];
    if (!context) return [];
    return context.bottomTokens
      .filter((token) => !linkForBottom(context, token.id) && nullFor(context, "target", token.id)?.state !== "active")
      .map((token) => joinVerseId(v, token.id));
  }

  // Click-to-pick-up: the keyboard/click-operable alternative to dragging.
  // A plain click picks one word up, or puts the only picked word down. Ctrl
  // (or ⌘) adds or removes a word; Shift takes the run from the anchor.
  function handleWordClick(tokenKey: string, event?: MouseEvent) {
    if (busy) return;
    if (drag.consumeSuppressedClick(tokenKey)) return;
    const v = splitVerseId(tokenKey).verse;
    const sameVerse = picked.length > 0 && splitVerseId(picked[0]).verse === v;
    if (event?.ctrlKey || event?.metaKey) {
      picked = !sameVerse ? [tokenKey] : picked.includes(tokenKey) ? picked.filter((key) => key !== tokenKey) : [...picked, tokenKey];
      anchor = tokenKey;
      return;
    }
    if (event?.shiftKey && anchor && anchor !== tokenKey && splitVerseId(anchor).verse === v) {
      const list = pickable(v);
      const from = list.indexOf(anchor), to = list.indexOf(tokenKey);
      if (from >= 0 && to >= 0) {
        // Only words in the same place as the one clicked: a run between two
        // unaligned words skips the aligned ones between them, and the other
        // way round (2026-11-17, Joel; see AlignmentModal).
        const context = contexts[v];
        const placed = (key: string): boolean => Boolean(context && groupForTarget(context, splitVerseId(key).id));
        const want = placed(tokenKey);
        const run = list.slice(Math.min(from, to), Math.max(from, to) + 1).filter((key) => key === anchor || placed(key) === want);
        const kept = sameVerse ? picked : [];
        picked = [...kept, ...run.filter((key) => !kept.includes(key))];
        return;
      }
    }
    picked = picked.length === 1 && picked[0] === tokenKey ? [] : [tokenKey];
    anchor = tokenKey;
  }

  function handleColumnClick(columnKey: string) {
    if (!picked.length || busy) return;
    const keys = picked;
    picked = [];
    dropOnColumn(keys, columnKey);
  }

  function handleBankClick(bankVerse: string) {
    // The click that ends a selection box must not put the words down.
    if (marquee.consumeSuppressedClick()) return;
    if (!picked.length || busy) return;
    const keys = picked;
    picked = [];
    dropOnBank(keys, bankVerse);
  }

  function startPointerTrack(event: PointerEvent, tokenKey: string) {
    if (busy) return;
    drag.start(event, tokenKey);
  }

  function openLexicon(token: AlignmentToken, direction: "ltr" | "rtl") {
    lexiconToken = token;
    lexiconDirection = direction;
  }

  function sourceRows(context: AlignmentContext): SourceRow[] {
    if (gapFilterVerse) return unrealizedSources(context).map((token) => ({ ...token, members: [token] }));
    const linked = (context.crossVerseGroups || []).filter((g) => g.state === "active" && g.sourceTopIds.length > 1)
      .map((g) => ({ id: g.groupId, topIds: g.sourceTopIds, bottomIds: [] }));
    return sourceColumns({ ...context, groups: [...linked, ...context.groups] }).map((column) => ({ ...column.tokens[0], members: column.tokens }));
  }

  function bankTokens(context: AlignmentContext): AlignmentToken[] {
    return gapFilterVerse ? unaccountedTargets(context) : context.bottomTokens;
  }

  function activate(event: KeyboardEvent, action: () => void) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      action();
    }
  }
</script>

<svelte:window on:pointerdown|capture={onAiOutside} on:resize={() => { aiOpen = false; moreOpen = false; }} on:keydown={(event) => { if (event.key !== "Escape") return; if (aiOpen || moreOpen) { aiOpen = false; moreOpen = false; return; } if (menu) { menu = null; return; } if (picked.length && !lexiconToken) { picked = []; return; } if (!busy && !lexiconToken && !embedded) onClose(); }} on:pointermove={trackEdge} on:pointerup={() => (edgeStep = 0)} />

<div class="overlay" class:standalone class:embedded role="presentation">
  <section class="page alignment-cards" role={embedded ? "region" : "dialog"} aria-modal={embedded ? undefined : "true"} aria-label={`Cross-verse alignment, chapter ${chapter}`} bind:this={dialogEl} use:syncVerseRows>
    <!-- 2026-11-16 (Joel): the Word alignment bar: 36 px, the chapter, then
         the range, then the icons. The tab names the page, so the heading is
         kept for screen readers only. -->
    <header>
      <h2 class="sr-only">Cross-verse alignment · Chapter {chapter} · verses {span ? (span[0] === span[1] ? span[0] : `${span[0]}–${span[1]}`) : verse}</h2>
      <div class="place picker" aria-label="Verse range">
        <span class="bar-word">Chapter {chapter}</span>
        <span class="rule" aria-hidden="true" />
        <!-- 2026-11-16 (Joel): the Verses panel's chapter picker, a grid of
             numbers, for both ends of the range. -->
        <span class="range-end"><span class="range-word">From</span>
          <GridPicker label="From" value={frame[0] ?? span?.[0] ?? verse} options={$verseNums.filter((v) => v !== "front")} disabled={busy} onChange={onFromChange} /></span>
        <span class="range-end"><span class="range-word">To</span>
          <GridPicker label="To" value={frame[frame.length - 1] ?? span?.[1] ?? verse} options={$verseNums.filter((v) => v !== "front")} disabled={busy} onChange={onToChange} /></span>
      </div>
      <!-- The range's alignment state, where the Word alignment bar has its verse's. -->
      <span class="range-status" role="group" aria-label="Alignment of the range">
        {#each rangeStatus as entry (entry.status)}
          <span class="status {entry.status}">{ordered.length === 1 ? `Verse: ${alignmentStatusLabel(entry.status)}` : `${entry.count} ${alignmentStatusLabel(entry.status).toLowerCase()}`}</span>
        {/each}
      </span>
      <div class="tools">
        {#if autoBusy || proposalsBusy}<span class="stage" role="status"><span class="spin" />{autoBusy ? autoStage : "Working out suggestions…"}</span>{/if}
        <button type="button" class="tool" aria-label="Undo last change" disabled={busy || autoBusy || !undoNext} on:click={() => undoNext && undoVerse(undoNext.verse)}
          use:tooltip={undoNext ? `Undo last change: the newest one in this range, in ${chapter}:${undoNext.verse}` : "Nothing to undo in this range"}><UiIcon name="undo" /></button>
        <button type="button" class="tool" class:alert={resetPending || chapterJob.resumable || Boolean(chapterJob.error)} bind:this={moreButton} aria-label="Reset and backups" aria-haspopup="menu" aria-expanded={moreOpen}
          use:tooltip={moreOpen ? "" : "Reset a verse or the chapter, or go back to an earlier version"} on:click={toggleMore}><UiIcon name="more" /></button>
        <button type="button" class="tool ai" class:open={aiOpen} bind:this={aiButton}
          aria-label="Automatic alignment" aria-haspopup="menu" aria-expanded={aiOpen}
          use:tooltip={aiOpen ? "" : "Automatic alignment: align this range with AI, or suggest links"} on:click={toggleAi}><UiIcon name="sparkle" /></button>
        <LayoutMenu size={28} quiet presets={WORD_PANEL_PRESETS} current={crossPanelLayout.preset($crossTree)} onChoose={crossPanelLayout.applyPreset} onReset={crossPanelLayout.reset}
          hint="Layout: arrange the verses, the source words and the target words"
          resetHint="The verses on top, source and target words side by side, standard text sizes" />
        <button type="button" class="tool" aria-label={$alignmentPinned ? "Follow editor (verse is pinned)" : "Pin verse (following editor)"} aria-pressed={$alignmentPinned} disabled={busy}
          use:tooltip={$alignmentPinned ? "Pinned to this verse. Click to follow the verse selected in the editor" : "Following the editor's verse. Click to pin this verse"}
          on:click={() => onPin ? onPin() : alignmentPinned.update((v) => !v)}><UiIcon name={$alignmentPinned ? "pin" : "follow"} /></button>
        <!-- 2026-11-16 (Joel): the way to Word alignment from here, as that
             tab has one to this page. Open already: it is shown. -->
        <button type="button" class="tool" aria-label="Word alignment" disabled={busy}
          use:tooltip={$alignmentOpen && !standalone ? "Word alignment is already open. Click to show it" : `Word alignment: the words of verse ${verse} alone`}
          on:click={() => { if ($alignmentOpen && !standalone) showAlignmentTab("word"); else openAlignment(chapter, verse); }}><UiIcon name="align" /></button>
        {#if onDetach && !standalone}<button type="button" class="tool" aria-label="Move to separate window" disabled={busy} use:tooltip={"Move to separate window"} on:click={onDetach}><UiIcon name="detach" /></button>{/if}
        {#if !embedded}<button type="button" class="tool" on:click={onClose} disabled={busy} aria-label="Close cross-verse alignment" use:tooltip={"Close"}><UiIcon name="close" /></button>{/if}
      </div>
    </header>
    {#if loading && ordered.length === 0}
      <div class="loading"><span class="spin" /> Loading {selection.length} verse{selection.length === 1 ? "" : "s"}…</div>
    {:else}
      {#if chapterJob.running || chapterJob.resumable || chapterJob.error}
        <!-- The chapter reset while it runs, or when it stopped part way. -->
        <div class="job-row" role="status">
          {#if chapterJob.running}<span class="spin" />{/if}
          <span>{chapterJob.text}</span>
          {#if chapterJob.running}<button type="button" class="link" on:click={() => chapterReset?.cancelReset()}>Cancel chapter reset</button>{/if}
          {#if chapterJob.resumable}<span>Open the reset menu on the bar to resume it.</span>{/if}
          {#if chapterJob.error}<span class="job-error" role="alert">{chapterJob.error}</span>{/if}
        </div>
      {/if}

      {#if lastRun}
        <div class="run-note" class:mixed={lastRun.mixed} role="status">
          <span>{lastRun.summary}</span>
          <select aria-label="Undo a verse" on:change={revertVerse} disabled={busy}>
            <option value="">Undo a verse ▾</option>
            {#each lastRun.verses as v}<option value={v}>Restore v.{v} to before this run</option>{/each}
          </select>
        </div>
      {/if}
      {#if proposalError}<div class="error">{proposalError}</div>{/if}
      {#if proposalsStale}<p class="empty">The range changed since the suggestions were worked out — suggest again.</p>{/if}
      {#if proposalsUnavailable}
        <p class="empty">{proposalsUnavailable}</p>
      {:else if suggestionsShown && !proposalsBusy && visibleProposals.length === 0}
        <p class="empty">No cross-verse realization found for the gaps in this range.</p>
      {/if}

      {#if loading}<div class="reloading"><span class="spin" /> Updating range…</div>{/if}

      <!-- 2026-11-16 (Joel): three panels, as on the Word alignment tab
           (WordPanels / WordPanel, with this page's own saved layout). They
           fill the tab and share its width and height; each scrolls inside
           when its verses need more room. It was AlignmentWorkspace's movable
           areas, which grew the page. -->
      <WordPanels layout={crossPanelLayout}>
        <WordPanel id="read">
          <svelte:fragment slot="tools">
            {#if suggested.length > 0}
              <span class="widened">↔ widened with v.{suggested.join(", ")} <button type="button" class="link" on:click={resetToDefaultRange} disabled={busy}>Back to {verse} ±1</button></span>
            {/if}
            <GridToggle label="Verses shown" options={frame} selected={selection} disabled={busy} onToggle={toggleShown} />
          </svelte:fragment>
          <div class="reading" role="region" aria-label={`Read chapter ${chapter}, verses ${visibleVerses.join(", ")}`}>
            <!-- 2026-11-16 (Joel): the verse number alone (the bar names the
                 chapter), then its text, with a hairline between verses and no
                 extra room: this panel is for reference, the other two for work. -->
            {#each visibleVerses as v}<p class="range-reading" dir={contexts[v].targetDirection} lang={$targetLang}><span class="read-num" dir="ltr" aria-label={`Verse ${v}`}>{v}</span><span class="read-text">{reading[v] ?? ""}</span></p>{/each}
          </div>
        </WordPanel>
        <WordPanel id="source">
          <svelte:fragment slot="tools">
            <!-- What is left in the range, where a row under the bar had it. -->
            <span class="totals" use:tooltip={"What is still open in the verses shown"}>
              {#if lastRun || rangeIssues.length || rangeSuggestions.length}
                {rangeIssues.filter((i) => i.kind === "POSSIBLE_OMISSION").length} possible omissions · {rangeIssues.filter((i) => i.kind === "POSSIBLE_ADDITION").length} additions · {rangeSuggestions.length} suggestions
              {:else}
                {totalGaps.sourceUnmatched} source · {totalGaps.targetUnmatched} target unmatched
              {/if}
            </span>
            {#if gapFilterVerse}<button type="button" class="link" on:click={() => (gapFilterVerse = null)}>Show all</button>{/if}
            <button type="button" class="hint" aria-label="Source words help"
              use:tooltip={"Click a word for its lexicon entry. Drop target words into the cell under it; a word from another verse makes a cross-verse link. A verse's state, beside its number, shows only what is left in it when clicked."}><UiIcon name="info" /></button>
          </svelte:fragment>
        <div class="col sources" data-verse-col="source" use:linkScroll>
          <div class="scroll">
            {#each visibleVerses as v (v)}
              {@const context = contexts[v]}
              <div class="verse-block" data-verse-row={v}>
                <div class="verse-head">
                  <span class="vnum">{chapter}:{v}</span>
                  <!-- The verse's state after an automatic pass, and its filter
                       (they were a card in a row under the bar). -->
                  <button type="button" class="verdict {verdictView(context, verdicts[v]).tone}" class:active={gapFilterVerse === v} aria-pressed={gapFilterVerse === v}
                    aria-label={`v.${v}: ${verdictView(context, verdicts[v]).label}`}
                    on:click={() => toggleGapFilter(v)}
                    use:tooltip={gapFilterVerse === v ? "Show all words again" : `Show only what is left in verse ${v}`}
                  >{verdictView(context, verdicts[v]).glyph} {verdictView(context, verdicts[v]).label}</button>
                  {#each verdictView(context, verdicts[v]).lines.filter(Boolean) as line}<span class="v-sub">{line}</span>{/each}
                  {#if !context.sourceAvailable}<span class="warn">no original-language source</span>{/if}
                  {#if context.issues.length}<span class="warn" use:tooltip={context.issues.join(" · ")}>⚠ {context.issues.length} issue{context.issues.length === 1 ? "" : "s"}</span>{/if}
                </div>
                <SourceSplitControls {context} busy={busy || autoBusy} onBusy={(value) => busy = value} onChanged={(values) => { for (const value of values) if (value.chapter === chapter) contexts = { ...contexts, [value.verse]: value }; }} />
                <div class="rows" dir={context.sourceDirection}>
                {#each sourceRows(context) as src, index (src.id)}
                  {@const columnKey = joinVerseId(v, src.id)}
                  {@const previous = index > 0 ? sourceRows(context)[index - 1] : null}
                  {@const cannotJoin = previous ? joinProblem(context, previous, src) : ""}
                  {@const ownGroup = groupForSource(context, src.id)}
                  <div class="row" class:joined={src.members.length > 1}>
                    <div class="source-words" class:joined={src.members.length > 1}>
                    {#each src.members as member, place (member.id)}
                      <!-- The split button only on a cell that is one alignment group.
                           A cell can also be drawn merged because its words share a
                           cross-verse link (sourceRows); a realign cannot take that
                           apart, so a button there would save nothing and say it had.
                           That cell is parted by removing its link (2026-11-18). -->
                      {#if place > 0 && !gapFilterVerse && ownGroup && ownGroup.topIds.length > 1}
                        <span class="seam"><button type="button" class="seam-split" on:click|stopPropagation={() => splitAt(v, src.members.map((m) => m.id), place)} disabled={busy}
                          aria-label={`Split ${src.members.map((m) => m.word).join(" ")} before ${member.word} in verse ${v}`}
                          use:tooltip={"Split here"}><UiIcon name="unmerge" /></button></span>
                      {/if}
                      <div class="source-card">
                      {#if place === 0 && !gapFilterVerse && previous}
                        <span class="card-tools source-tools">
                          <button type="button" class="card-btn merge" on:click|stopPropagation={() => joinWithPrevious(v, index)} disabled={busy || Boolean(cannotJoin)}
                            aria-label={`Join ${src.members.map((m) => m.word).join(" ")} with the previous source word in verse ${v}`}
                            use:tooltip={cannotJoin || "Merge with the previous word: one target word for both"}><UiIcon name="merge" /></button>
                        </span>
                      {/if}
                      <button type="button" class="token source" dir={context.sourceDirection} class:hebrew={context.sourceDirection === "rtl"}
                        on:click={() => openLexicon(member, context.sourceDirection)} disabled={busy} use:tooltip={sourceHint(member, glossVersion)}>
                        <span class="word">{member.word}{#if member.occurrences > 1}<span class="occ">{occurrence(member)}</span>{/if}</span>
                        {#if sourceGloss(member, glossVersion)}<small class="gloss">{sourceGloss(member, glossVersion)}</small>{/if}
                      </button>
                      </div>
                    {/each}
                    </div>
                    <div
                      class="drop-cell"
                      class:drop-hover={$dragState.overColumn === columnKey}
                      data-drop-column={columnKey}
                      dir={context.targetDirection}
                      lang={$targetLang}
                      role="button"
                      tabindex="0"
                      aria-label={picked.length > 1 ? `Align ${picked.length} picked-up words to ${src.word} in verse ${v}`
                        : picked.length ? `Align picked-up word to ${src.word} in verse ${v}` : `Target words aligned to ${src.word} in verse ${v}`}
                      on:click={() => handleColumnClick(columnKey)}
                      on:keydown={(event) => activate(event, () => handleColumnClick(columnKey))}
                    >
                      {#each alignedTargetsFor(context, src.id) as item, at (item.id)}
                        {@const tag = groupTag(verdicts[v], context, src.id)}
                        {@const count = groupForSource(context, src.id)?.bottomIds.length ?? 0}
                        {@const cardKey = joinVerseId(v, item.id)}
                        <!-- The word can be picked up and moved to another cell
                             of its verse, alone or with others, and a drop on
                             a card lands before or after it (2026-11-16, as on
                             the Word alignment tab). -->
                        <span class="token target aligned-card" class:picked={picked.includes(cardKey)}
                          class:insert-before={$dragState.moved && $dragState.overSlot?.value === cardKey && !$dragState.overSlot.after}
                          class:insert-after={$dragState.moved && $dragState.overSlot?.value === cardKey && $dragState.overSlot.after}
                          data-drop-slot={cardKey}
                          use:tooltip={tag.startsWith("ai") ? "Placed automatically: both passes agreed" : ""}>
                          <button type="button" class="pick" on:pointerdown={(event) => startPointerTrack(event, cardKey)}
                            on:click|stopPropagation={(event) => handleWordClick(cardKey, event)} disabled={busy}
                            aria-label={`Pick up ${item.word} from ${src.word}`} aria-pressed={picked.includes(cardKey)}
                          ><span class="word">{item.word}{#if item.occurrences > 1}<span class="occ">{occurrence(item)}</span>{/if}</span></button>
                          {#if tag}<small class="tag">{tag}</small>{/if}
                          <span class="card-tools">
                            {#if count > 1}
                              <button type="button" class="card-btn step" on:click|stopPropagation={() => stepWithinCell(v, src.id, item.id, -1)}
                                disabled={busy || at === 0} aria-label={`Move ${item.word} earlier`} use:tooltip={"Move earlier"}><UiIcon name="chevronLeft" /></button>
                              <button type="button" class="card-btn step" on:click|stopPropagation={() => stepWithinCell(v, src.id, item.id, 1)}
                                disabled={busy || at === count - 1} aria-label={`Move ${item.word} later`} use:tooltip={"Move later"}><UiIcon name="chevronRight" /></button>
                            {/if}
                            <button type="button" class="card-btn unalign-x" on:click|stopPropagation={() => returnToBank(v, item.id)} disabled={busy}
                              aria-label={`Unalign ${item.word} from ${src.word}`} use:tooltip={"Remove"}><UiIcon name="close" /></button>
                          </span>
                        </span>
                      {/each}
                      {#each linksForSource(context, src.id) as link (link.id)}
                        <span
                          class="token target linked-card"
                          class:invalid={link.state === "invalid"}
                          use:tooltip={link.state === "invalid"
                            ? (link.invalidReason ?? "This link no longer applies.")
                            : `Realized in verse ${link.target.verse} by ${link.target.word}. Bridge-private link; translationCore alignment is unchanged.`}
                        >
                          <span class="word">{link.target.word}</span>
                          <small>{link.state === "invalid" ? "link invalid" : "realized in"} v.{link.target.verse}{#if linkTag(context, link)} · {linkTag(context, link)}{/if}</small>
                          <span class="card-tools"><button type="button" class="card-btn unalign-x" on:click|stopPropagation={() => unlink(link)} disabled={busy}
                            aria-label={`Remove cross-verse link from ${src.word} to ${link.target.word} in verse ${link.target.verse}`}
                            use:tooltip={"Remove this cross-verse link"}><UiIcon name="close" /></button></span>
                        </span>
                      {/each}
                      {#if nullFor(context, "source", src.id)}
                        {@const decision = nullFor(context, "source", src.id)}
                        {#if decision}
                          <!-- 2026-11-25 (Joel): a small chip, the reason and who
                               decided it. The explanation was a line inside
                               the card, which made the card as wide as the
                               panel; it is in the hint, in full. -->
                          <span class="token null-card" class:invalid={decision.state === "invalid" || decision.stale}
                            use:tooltip={decision.origin === "ai-auto" ? `Both passes agree this word has no separate target word: ${decision.note || decision.reason.toLowerCase()}` : `Marked by you: ${decision.note || decision.reason.toLowerCase()}`}>
                            <span class="null-reason">{decision.reason.toLowerCase()}</span>
                            <small class:ai={decision.origin === "ai-auto"}>{decision.origin === "ai-auto" ? "ai" : "you"}</small>
                            <span class="card-tools"><button type="button" class="card-btn unalign-x" on:click|stopPropagation={() => clearNull(v, decision)} disabled={busy}
                              aria-label={`Clear ${decision.reason.toLowerCase()} on ${src.word}`} use:tooltip={"Clear this decision"}><UiIcon name="close" /></button></span>
                          </span>
                        {/if}
                      {/if}
                      {#if issueFor(context, verdicts[v], "source", src)}
                        {@const issue = issueFor(context, verdicts[v], "source", src)}
                        <span class="issue-badge omission" use:tooltip={issue?.note || ""}><span aria-hidden="true">?</span>possible omission</span>
                        <button type="button" class="issue-action" on:click|stopPropagation={() => openMenu("source", v, src)} disabled={busy}>Not missing ▾</button>
                      {/if}
                      {#each sourceSuggestions(rangeSuggestions, v, src) as s (suggestionKey(s))}
                        <span class="token suggest-card" class:disputed={s.status !== "UNCERTAIN" || !Object.values(s.votes).every(Boolean)}
                          use:tooltip={`${Object.entries(s.votes).map(([pass, yes]) => `${pass}: ${yes ? "yes" : "no"}`).join(" · ")}${s.reason ? ` — ${s.reason}` : ""}`}>
                          {#if s.kind === "link"}
                            <span class="word">{s.target?.word} ?</span>
                            <small>{s.target && s.target.verse !== v ? `v.${s.target.verse} · ` : ""}{s.status === "CORPUS_DISAGREES" ? "corpus disagrees" : s.status === "CONFLICTS_WITH_HUMAN" ? "differs from yours" : "passes disagree"}</small>
                          {:else}
                            <span class="null-reason">{s.reason.toLowerCase()} ?</span>
                            <small>passes disagree</small>
                          {/if}
                          <button type="button" class="accept-x" on:click|stopPropagation={() => acceptSuggestion(s)} disabled={busy} aria-label={`Accept ${s.kind === "link" ? s.target?.word : s.reason.toLowerCase()} for ${src.word}`}
                            use:tooltip={s.kind === "link" ? `Accept: align ${s.target?.word ?? "this word"} here` : `Accept: mark ${src.word} ${s.reason.toLowerCase()}`}><UiIcon name="check" /></button>
                          <button type="button" class="unalign-x" on:click|stopPropagation={() => dismissSuggestion(s)} disabled={busy} aria-label="Dismiss this suggestion"
                            use:tooltip={"Dismiss this suggestion"}><UiIcon name="close" /></button>
                        </span>
                      {/each}
                      {#each corpusFor(visibleProposals, v, src.id) as proposal (proposalKey(proposal))}
                        <span class="token suggest-card" class:disputed={proposal.status === "AMBIGUOUS"} use:tooltip={evidenceSummary(proposal) || ""}>
                          <span class="word">{proposal.target.word} ?</span>
                          <small>v.{proposal.target.verse} · {proposal.status === "AMBIGUOUS" ? "ambiguous" : "corpus"}</small>
                          {#if proposal.status === "PROPOSED"}
                            <button type="button" class="accept-x" on:click|stopPropagation={() => acceptProposal(proposal)} disabled={busy || proposalsBusy} aria-label={`Accept ${proposal.target.word} for ${src.word}`}
                              use:tooltip={`Accept: link ${proposal.target.word} from verse ${proposal.target.verse} here`}><UiIcon name="check" /></button>
                          {/if}
                          <button type="button" class="unalign-x" on:click|stopPropagation={() => dismissProposal(proposal)} disabled={busy} aria-label="Dismiss this suggestion"
                            use:tooltip={"Dismiss this suggestion"}><UiIcon name="close" /></button>
                        </span>
                      {/each}
                      {#if alignedTargetsFor(context, src.id).length === 0 && linksForSource(context, src.id).length === 0
                        && !nullFor(context, "source", src.id) && !issueFor(context, verdicts[v], "source", src)
                        && sourceSuggestions(rangeSuggestions, v, src).length === 0 && corpusFor(visibleProposals, v, src.id).length === 0}
                        <span class="placeholder" aria-hidden="true">·</span>
                      {/if}
                    </div>
                  </div>
                {:else}
                  <p class="empty">{gapFilterVerse ? "Every source word has a counterpart." : "No source tokens in this verse."}</p>
                {/each}
                </div>
              </div>
            {/each}
          </div>
        </div>
        </WordPanel>
        <WordPanel id="target">
          <svelte:fragment slot="tools">
            {#if picked.length > 1}
              <span class="picked-count" role="status" use:tooltip={`${picked.map(tokenWord).join(" ")}. Click a cell to place them, or press Esc to put them down`}>{picked.length} picked</span>
            {/if}
            <button type="button" class="hint" aria-label="Target words help"
              use:tooltip={"In verse order. Drag a blue word into a source cell, or click it then click a cell. Ctrl-click adds a word, Shift-click a run, or drag a box in a verse's word bank to select several of that verse, then drag them together. To link across verses, drop on a source word of the other verse."}><UiIcon name="info" /></button>
          </svelte:fragment>
        <div class="col targets" data-verse-col="target" use:linkScroll>
          <div class="scroll">
            {#each visibleVerses as v (v)}
              {@const context = contexts[v]}
              <div class="verse-block" data-verse-row={v}>
                <div class="verse-head">
                  <span class="vnum">{chapter}:{v}</span>
                </div>
                <div
                  class="bank"
                  class:drop-hover={$dragState.overBank === v}
                  class:marquee-active={$marqueeState.moved && marqueeVerse === v}
                  data-drop-bank={v}
                  on:pointerdown={(event) => startMarquee(event, v)}
                  dir={context.targetDirection}
                  lang={$targetLang}
                  role="button"
                  tabindex="0"
                  aria-label={picked.length > 1 ? `Return ${picked.length} picked-up words to the word bank of verse ${v}`
                    : picked.length ? `Return picked-up word to the word bank of verse ${v}` : `Word bank of verse ${v}`}
                  on:click={() => handleBankClick(v)}
                  on:keydown={(event) => activate(event, () => handleBankClick(v))}
                >
                  {#each bankTokens(context) as item (item.id)}
                    {@const tokenKey = joinVerseId(v, item.id)}
                    {@const accountedBy = linkForBottom(context, item.id)}
                    {#if accountedBy}
                      <span
                        class="token target accounted"
                        use:tooltip={`Realizes ${accountedBy.source.word} from verse ${accountedBy.source.verse}. Bridge-private link; this word stays in the word bank for translationCore.`}
                      >
                        <span class="word">{item.word}{#if item.occurrences > 1}<span class="occ">{occurrence(item)}</span>{/if}</span>
                        <small>↔ v.{accountedBy.source.verse}</small>
                        <span class="card-tools"><button type="button" class="card-btn unalign-x" on:click|stopPropagation={() => unlink(accountedBy)} disabled={busy}
                          aria-label={`Remove cross-verse link from ${accountedBy.source.word} in verse ${accountedBy.source.verse} to ${item.word}`}
                          use:tooltip={"Remove this cross-verse link"}><UiIcon name="close" /></button></span>
                      </span>
                    {:else if nullFor(context, "target", item.id)?.state === "active"}
                      {@const decision = nullFor(context, "target", item.id)}
                      {#if decision}
                        <span class="token target null-word" use:tooltip={decision.origin === "ai-auto" ? `Both passes agree: ${decision.note || decision.reason.toLowerCase()}` : `Marked by you: ${decision.note || decision.reason.toLowerCase()}`}>
                          <span class="word">{item.word}</span>
                          <small>{decision.reason === "EXPLICITATION" ? "explicitation" : "grammar"}{decision.origin === "ai-auto" ? " · ai" : ""}</small>
                          <span class="card-tools"><button type="button" class="card-btn unalign-x" on:click|stopPropagation={() => clearNull(v, decision)} disabled={busy}
                            aria-label={`Clear ${decision.reason.toLowerCase()} on ${item.word}`} use:tooltip={"Clear this decision"}><UiIcon name="close" /></button></span>
                        </span>
                      {/if}
                    {:else if groupForTarget(context, item.id)}
                      <span class="token target already-aligned" use:tooltip={"Already aligned in this verse"}>
                        <span class="word">{item.word}{#if item.occurrences > 1}<span class="occ">{occurrence(item)}</span>{/if}</span>
                      </span>
                    {:else}
                      {@const addition = issueFor(context, verdicts[v], "target", item)}
                      {@const options = targetSuggestions(rangeSuggestions, v, item)}
                      <span class="bank-item">
                        <button
                          type="button"
                          class="token target unaligned"
                          class:picked={picked.includes(tokenKey)}
                          class:flag-add={Boolean(addition)}
                          class:flag-sugg={options.length > 0}
                          data-marquee-item={tokenKey}
                          aria-pressed={picked.includes(tokenKey)}
                          on:pointerdown={(event) => startPointerTrack(event, tokenKey)}
                          on:click|stopPropagation={(event) => handleWordClick(tokenKey, event)}
                          disabled={busy}
                          use:tooltip={addition?.note || ""}
                        ><span class="word">{item.word}{#if item.occurrences > 1}<span class="occ">{occurrence(item)}</span>{/if}</span></button>
                        {#if addition}
                          <span class="issue-badge addition" use:tooltip={addition.note || ""}><span aria-hidden="true">?</span>possible addition</span>
                          <button type="button" class="issue-action" on:click|stopPropagation={() => openMenu("target", v, item)} disabled={busy}>Not an addition ▾</button>
                        {/if}
                        {#each options as s (suggestionKey(s))}
                          <span class="option">
                            {#if s.kind === "link"}→ <span class="greek">{s.source?.word}</span> v.{s.source?.verse} ?{:else}{s.reason === "EXPLICITATION" ? "explicitation" : "grammar"} ?{/if}
                            <button type="button" class="accept-x" on:click|stopPropagation={() => acceptSuggestion(s)} disabled={busy}
                              aria-label={`Accept ${s.kind === "link" ? s.source?.word : s.reason.toLowerCase()} for ${item.word}`}>✓</button>
                          </span>
                        {/each}
                      </span>
                    {/if}
                  {:else}
                    <p class="empty">{gapFilterVerse ? "Every target word is aligned." : "This verse has no target words."}</p>
                  {/each}
                </div>
              </div>
            {/each}
          </div>
        </div>
        </WordPanel>
      </WordPanels>
    {/if}
  </section>
  {#if notice || error}
    <div class="toasts">
      {#if error}
        <!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
        <div class="toast bad" role="alert" on:mouseenter={holdError} on:mouseleave={() => scheduleErrorClear(error, ordered.length > 0, errorDetail)}>
          <span>{error}
            {#if errorDetail?.message === error}
              <details class="error-detail"><summary>Show details</summary><code>{errorDetail.raw}</code></details>
            {/if}
          </span>
          <button type="button" class="toast-close" aria-label="Dismiss this message" on:click={() => (error = "")}><UiIcon name="close" /></button>
        </div>
      {/if}
      {#if notice}<div class="toast ok" role="status">{notice}</div>{/if}
    </div>
  {/if}
</div>

<!-- svelte-ignore a11y-click-events-have-key-events -->
<div class="ai-menu" role="menu" tabindex="-1" aria-label="Automatic alignment" hidden={!aiOpen} style={aiPlace} bind:this={aiEl} on:click={onAiClick}>
  <button type="button" role="menuitem" class="ai-item" on:click={runAuto} disabled={busy || loading || !aiAvailable || Boolean(windowIssue)}
    use:tooltip={aiAvailable === undefined
      ? "Checking whether an AI provider is configured…"
      : !aiAvailable
        ? "Add an API key or sign in with ChatGPT in Settings to align automatically"
        : windowIssue || "Ask your AI provider twice and write what both readings agree on"}>
    <span class="ai-name">{lastRun ? "Align again" : "Align automatically"}</span>
    <small>{aiAvailable === false ? "Needs an API key or a ChatGPT sign-in: set one up in Settings."
      : windowIssue ? windowIssue
      : "Asks your AI provider twice, source-first and target-first. Words both passes agree on are aligned; the rest become suggestions for you."}</small>
  </button>
  <button type="button" role="menuitem" class="ai-item" on:click={loadProposals} disabled={proposalsBusy || busy || loading}>
    <span class="ai-name">{suggestionsShown ? "Suggest again" : "Suggest links"}</span>
    <small>Proposes cross-verse links, learned from this project's own completed alignments. No AI provider is needed.</small>
  </button>
  {#if usageLine}<div class="ai-note">{usageLine}</div>{/if}
</div>

<!-- Reset and backups, the Word alignment bar's "more" menu, for a range:
     the chapter, then each verse, then the range's newest backups. Kept
     mounted while closed, so an interrupted reset is still noticed. -->
<!-- svelte-ignore a11y-click-events-have-key-events -->
<div class="more-menu" role="menu" tabindex="-1" aria-label="Reset and backups" hidden={!moreOpen} style={morePlace} bind:this={moreEl} on:click={onMoreClick}>
  <AlignmentChapterReset menu bind:this={chapterReset} {chapter} busy={busy || autoBusy} onBusy={setBusy} onState={setChapterJob} onChanged={chapterResetChanged} />
  {#each ordered as v (v)}
    <div class="more-label">Verse {chapter}:{v}</div>
    <AlignmentResetControls menu context={contexts[v]} busy={busy || autoBusy} onBusy={setBusy} onError={setError} onPending={(value) => setPendingReset(v, value)} onChanged={chapterResetChanged} />
  {/each}
  <div class="more-label">Go back to an earlier version</div>
  {#each rangeBackups as entry (`${entry.verse}:${entry.item.id}`)}
    <button type="button" role="menuitem" class="more-item" disabled={busy || autoBusy} on:click={() => void restoreVerseBackup(entry.verse, entry.item)}>{chapter}:{entry.verse} · {backupLabel(entry.item)}</button>
  {:else}
    <div class="more-none">None yet: one is kept for each change.</div>
  {/each}
</div>

{#if menu}
  {@const current = menu}
  <div class="menu-overlay" role="presentation" on:click={(event) => { if (event.target === event.currentTarget) menu = null; }}>
    <div class="issue-menu" role="menu" tabindex="-1" aria-label={current.side === "source" ? `Why ${current.word} is not missing` : `Why ${current.word} is not an addition`}>
      <div class="menu-title">{current.side === "source" ? `${current.word} is not missing because…` : `${current.word} is not an addition because…`}</div>
      {#if current.side === "source"}
        <button type="button" role="menuitem" on:click={() => setNull("source", current.verse, current.id, "GRAMMATICAL")}>Grammatical<small>a Tamil ending or word order carries it</small></button>
        <button type="button" role="menuitem" on:click={() => setNull("source", current.verse, current.id, "IMPLICIT")}>Implicit<small>the meaning is clear from context</small></button>
      {:else}
        <button type="button" role="menuitem" on:click={() => setNull("target", current.verse, current.id, "GRAMMATICAL")}>Grammar<small>the language needs this word</small></button>
        <button type="button" role="menuitem" on:click={() => setNull("target", current.verse, current.id, "EXPLICITATION")}>Explicitation<small>it states what the source implies</small></button>
      {/if}
      <button type="button" role="menuitem" on:click={() => { notice = current.side === "source" ? `Drag the word that carries ${current.word} into its cell.` : `Drag ${current.word} onto the source word it renders.`; menu = null; }}>Link manually…<small>{current.side === "source" ? "drag a target word into this cell" : "drag it onto a source word"}</small></button>
    </div>
  </div>
{/if}

{#if lexiconToken}
  <LexiconPopup token={lexiconToken} direction={lexiconDirection} onClose={() => (lexiconToken = null)} />
{/if}

{#if $dragState.tokenId && $dragState.moved}
  <div class="drag-ghost" lang={$targetLang} style="left:{$dragState.ghost.x}px; top:{$dragState.ghost.y}px;">{ghostLabel}</div>
{/if}
{#if $marqueeState.moved && $marqueeState.rect}
  <div class="marquee" aria-hidden="true" style="left:{$marqueeState.rect.left}px; top:{$marqueeState.rect.top}px; width:{$marqueeState.rect.width}px; height:{$marqueeState.rect.height}px;"></div>
{/if}

<style>
  .source-words { display: flex; flex-wrap: wrap; align-items: stretch; justify-content: center; gap: 3px; width: 100%; }
  .standalone { padding: 0; background: var(--surface); }
  .standalone .modal, .standalone .page { width: 100%; height: 100vh; max-height: 100vh; border-radius: 0; }
  .overlay { position: fixed; inset: 0; z-index: var(--z-dialog); background: rgba(15, 20, 26, .58); display: grid; place-items: center; padding: 16px; }
  .page {
    /* About 95% of the window (#484), same as AlignmentModal; was a 1340px cap.
       A column: the bar, the range and the automatic-alignment rows, then the
       panels take what is left (WordPanels is `flex: 1`) and scroll inside
       themselves. The page scrolls only when the window is too short. */
    width: min(95vw, 100%); max-height: calc(100vh - 32px); overflow: auto; display: flex; flex-direction: column; min-height: 0;
    background: var(--surface); border-radius: 14px; box-shadow: 0 24px 80px rgba(0,0,0,.24); padding: 0; color: var(--text); container-type: inline-size; font-size: var(--fs-xs);
  }
  /* The bar: the Word alignment tab's (and the Verses panel's): 36px, one row. */
  header { position: sticky; top: 0; z-index: 4; flex: none; display: flex; align-items: center; gap: 8px; height: 36px; min-height: 36px; box-sizing: border-box; padding: 0 10px; overflow: hidden; background: var(--surface); border-bottom: 1px solid var(--border); }
  .sr-only { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
  .place { display: flex; align-items: center; gap: 8px; flex: none; }
  .bar-word { font-size: var(--fs-xs); font-weight: 700; color: var(--text); white-space: nowrap; }
  .rule { width: 1px; height: 18px; flex: none; background: var(--border); }
  .tools { display: flex; align-items: center; gap: 2px; flex: none; margin-left: auto; }
  .picker { font-size: var(--fs-2xs); font-weight: 600; color: var(--text-2); }
  .range-end { display: inline-flex; align-items: center; gap: 5px; }
  .range-word { white-space: nowrap; }
  button, select { font: inherit; }
  button { border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); border-radius: 7px; padding: 6px 9px; cursor: pointer; }
  button:hover:not(:disabled) { border-color: var(--accent); }
  button:disabled { opacity: .5; cursor: not-allowed; }
  select { border: 1px solid var(--border-strong); border-radius: 7px; padding: 5px 7px; color: var(--text); background: var(--surface); }
  /* The bar's icon buttons and the panels' info hints, as on the Word alignment tab. */
  .tool, .hint { display: grid; place-items: center; flex: none; width: 28px; height: 28px; padding: 0; border: 0; border-radius: 7px; background: transparent; color: var(--text-2); }
  .tool :global(svg) { width: 16px; height: 16px; }
  .tool:hover:not(:disabled), .hint:hover { background: var(--bg); color: var(--text); }
  .tool[aria-pressed="true"], .tool[aria-pressed="true"]:hover:not(:disabled) { color: var(--accent); }
  .tool:focus-visible, .hint:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .hint { width: 20px; height: 20px; color: var(--text-3); cursor: help; }
  .hint :global(svg) { width: 14px; height: 14px; }
  .link { flex: none; border: 0; background: none; color: var(--accent); padding: 0; font-size: var(--fs-3xs); text-decoration: underline; white-space: nowrap; }
  .loading, .reloading { flex: none; padding: 12px; display: flex; gap: 10px; align-items: center; justify-content: center; color: var(--text-2); font-size: var(--fs-sm); }
  .loading { padding: 36px; }
  .spin { width: 12px; height: 12px; border: 2px solid var(--accent-bg); border-top-color: var(--accent); border-radius: 50%; animation: spin .8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }


  /* #222: the automatic pass. Auto-bar and verdict strip replace the gap strip
     and the suggestion strip; suggestions now sit in the cells they would
     fill. Sizes are the approved mockup's (1366x768). */
  /* The bar's automatic-alignment button and its menu (2026-11-16). */
  .tool.ai { color: var(--accent); }
  .tool.ai:hover, .tool.ai.open { background: var(--accent-bg); color: var(--accent); }
  .tool.ai.alert { color: var(--danger); }
  .stage { display: inline-flex; align-items: center; gap: 6px; margin-right: 4px; font-size: var(--fs-2xs); font-weight: 600; color: var(--accent); white-space: nowrap; }
  .ai-menu { position: fixed; z-index: var(--z-dropdown); box-sizing: border-box; width: 300px; max-width: calc(100vw - 12px); overflow-y: auto; padding: 4px;
    border: 1px solid var(--border-strong); border-radius: 10px; background: var(--surface); color: var(--text); font-size: var(--fs-2xs); box-shadow: 0 12px 32px rgba(0,0,0,.16); }
  .ai-menu[hidden] { display: none; }
  .ai-item { display: block; width: 100%; padding: 7px 8px; border: 0; border-radius: 6px; background: none; color: var(--text); text-align: left; }
  .ai-item:hover:not(:disabled) { background: var(--accent-bg); }
  .ai-name { display: block; font-weight: 700; }
  .ai-item small { display: block; margin-top: 2px; color: var(--text-3); font-size: var(--fs-3xs); line-height: 1.35; white-space: normal; }
  .ai-note { padding: 4px 8px 6px; color: var(--text-3); font-size: var(--fs-3xs); font-variant-numeric: tabular-nums; }
  .range-status { display: flex; align-items: center; gap: 4px; min-width: 0; overflow: hidden; }
  .tool.alert { color: var(--danger); }
  .more-menu { position: fixed; z-index: var(--z-dropdown); box-sizing: border-box; width: 280px; max-width: calc(100vw - 12px); overflow-y: auto; padding: 4px;
    border: 1px solid var(--border-strong); border-radius: 10px; background: var(--surface); color: var(--text); font-size: var(--fs-2xs); box-shadow: 0 12px 32px rgba(0,0,0,.16); }
  .more-menu[hidden] { display: none; }
  .more-label { margin-top: 4px; padding: 7px 8px 3px; border-top: 1px solid var(--border); color: var(--text-3); font-size: var(--fs-3xs); font-weight: 700; }
  .more-item { display: block; width: 100%; padding: 6px 8px; border: 0; border-radius: 6px; background: none; color: var(--text); text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .more-item:hover:not(:disabled) { background: var(--bg); }
  .more-none { padding: 4px 8px 6px; color: var(--text-3); }
  .job-row { flex: none; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 4px 10px 0; padding: 5px 10px; border-radius: 8px; background: var(--surface-2); color: var(--text-2); font-size: var(--fs-2xs); }
  .job-error { color: var(--danger); }
  /* A verse's state beside its number (it was a card in a row under the bar):
     a small chip that is also the "show only what is left" switch. */
  .verdict { flex: none; padding: 1px 8px; border: 0; border-radius: 999px; font-size: var(--fs-3xs); font-weight: 700; white-space: nowrap; }
  .verdict.clean { background: var(--success-bg); color: var(--success); }
  .verdict.review, .verdict.stale { background: var(--warning-bg); color: var(--warning); }
  .verdict.idle { background: var(--surface-2); color: var(--text-3); box-shadow: inset 0 0 0 1px var(--border); }
  .verdict.active { outline: 2px solid var(--accent); outline-offset: 1px; }
  .v-sub { font-size: var(--fs-3xs); color: var(--text-3); white-space: nowrap; }
  .totals { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--fs-3xs); font-weight: 600; color: var(--text-3); font-variant-numeric: tabular-nums; }
  .widened { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--fs-3xs); color: var(--accent); }
  /* The last automatic run, with its "Undo a verse": a row, because it holds a control. */
  .run-note { flex: none; display: flex; gap: 12px; align-items: center; margin: 4px 10px 0; padding: 5px 10px; border-radius: 8px; background: var(--success-bg); color: var(--success); font-size: var(--fs-2xs); line-height: 1.4; }
  .run-note.mixed { background: var(--warning-bg); color: #8A4B05; }
  .run-note select { font-size: var(--fs-2xs); padding: 3px 6px; margin-left: auto; }

  /* Two-line cards: word, then where/what. A long Tamil word ellipsizes inside
     a 150px track instead of overflowing it (#206). */
  .aligned-card, .linked-card, .accounted, .null-card, .suggest-card {
    position: relative; display: inline-grid; grid-template-columns: minmax(0, 1fr) auto; column-gap: 4px; align-items: center;
    max-width: 100%; min-width: 0; box-sizing: border-box; border-radius: 7px; padding: 3px 5px 3px 8px; color: var(--text);
  }
  .aligned-card .word, .linked-card > .word, .accounted > .word, .suggest-card > .word {
    font-family: var(--font-target); font-size: var(--fs-sm); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0;
  }
  .aligned-card > small, .linked-card > small, .accounted > small, .null-card > small, .suggest-card > small {
    grid-column: 1; font-size: var(--fs-3xs); font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  /* A card's remove (2026-11-16): one small round button on its top edge,
     at the end of the word, shown while the card is pointed at or focused,
     as on the Word alignment tab. A suggestion keeps its accept and dismiss
     in view: it is a question waiting for an answer. */
  .card-tools { position: absolute; z-index: 2; top: -11px; inset-inline-end: -5px; display: none; align-items: center; gap: 1px; padding: 1px;
    border: 1px solid var(--border-strong); border-radius: 999px; background: var(--surface); box-shadow: 0 2px 6px rgba(0,0,0,.16); }
  .token:hover > .card-tools, .token:focus-within > .card-tools { display: inline-flex; }
  .card-tools .card-btn { display: grid; place-items: center; width: 16px; height: 16px; padding: 0; border: 0; border-radius: 50%; background: transparent; color: var(--text-2); opacity: 1; }
  .card-tools .card-btn :global(svg) { width: 9px; height: 9px; stroke-width: 3; }
  .card-tools .card-btn:disabled { opacity: .3; cursor: default; }
  .card-tools .card-btn.unalign-x:hover:not(:disabled), .card-tools .card-btn.unalign-x:focus-visible { color: var(--danger); background: var(--danger-bg); }
  .card-tools .card-btn.step:hover:not(:disabled), .card-tools .card-btn.step:focus-visible { color: var(--accent); background: var(--accent-bg); }
  .drop-cell[dir="rtl"] .card-btn.step :global(svg) { transform: scaleX(-1); }
  .aligned-card .tag { color: var(--accent); }
  /* The word of an aligned card is a pick-up button, drawn as the plain word
     (#285); the card shows the pick. A bar on the side of a card shows where
     a dragged word will land (#410). All as on the Word alignment tab. */
  .aligned-card .pick { min-width: 0; border: 0; background: none; padding: 0; margin: 0; font: inherit; color: inherit; text-align: inherit; cursor: pointer; touch-action: none; user-select: none; }
  .aligned-card.insert-before { box-shadow: -4px 0 0 0 var(--accent); }
  .aligned-card.insert-after { box-shadow: 4px 0 0 0 var(--accent); }
  .drop-cell[dir="rtl"] .aligned-card.insert-before { box-shadow: 4px 0 0 0 var(--accent); }
  .drop-cell[dir="rtl"] .aligned-card.insert-after { box-shadow: -4px 0 0 0 var(--accent); }
  /* Join and split, the Word alignment tab's arrows (#207). */
  /* 2026-11-17 (Joel): joining and splitting source words is a small toolbar
     on the column's first source card, shown while the card is pointed at or
     focused, like a target card's. It sits on the side of the word before
     it. The arrows between the cards are gone: they read as direction, not
     as "join". */
  /* 2026-11-17 (Joel): merged source words are one segmented card, not cards
     in a blue box: the cards touch, share one border with square inner
     corners, and a soft ring in the source colour marks the group. Logical
     properties, so it reads the same in a right-to-left verse. These rules
     live here, not in alignmentCards.css: they must outrank this component's
     own `button` and `.source-words` rules, and only a rule scoped the same
     way does so in both the dev server and a build. */
  .source-words.joined { flex-wrap: nowrap; gap: 0; border-radius: 8px; box-shadow: 0 0 0 3px color-mix(in srgb, var(--term) 16%, transparent); }
  .source-words .source-card > .token.source { flex: 1 1 auto; }
  .source-words.joined .token.source { border-color: color-mix(in srgb, var(--term) 50%, var(--border)); }
  .source-words.joined .seam + .source-card { margin-inline-start: -1px; }
  .source-words.joined .source-card:hover, .source-words.joined .source-card:focus-within { z-index: 1; }
  .source-words.joined .source-card:not(:last-child) > .token.source { border-start-end-radius: 0; border-end-end-radius: 0; }
  .source-words.joined .source-card:not(:first-child) > .token.source { border-start-start-radius: 0; border-end-start-radius: 0; }
  /* The seam between two merged words is the split button: always shown, one
     click splits the group there and the words keep their order. The seam is
     its own zero-width item between the two cards and the button is centred
     on it both ways, so it sits exactly on the line whatever the card widths,
     the text size or the reading direction. */
  .source-words .seam { position: relative; z-index: 3; flex: none; width: 0; align-self: stretch; }
  .source-words .seam .seam-split {
    position: absolute; top: 50%; left: 0; transform: translate(-50%, -50%);
    display: grid; place-items: center; width: 18px; height: 18px; min-width: 0; min-height: 0; box-sizing: border-box; padding: 0; margin: 0; line-height: 0; border-radius: 50%;
    border: 1px solid color-mix(in srgb, var(--term) 50%, var(--border)); background: var(--surface); color: var(--text-2); cursor: pointer;
    box-shadow: 0 1px 3px rgba(0,0,0,.12);
  }
  .source-words .seam .seam-split :global(svg) { display: block; width: 12px; height: 12px; stroke-width: 2; }
  .source-words .seam .seam-split:hover:not(:disabled), .source-words .seam .seam-split:focus-visible { color: var(--accent); border-color: var(--accent); background: var(--accent-bg); }
  .source-words .seam .seam-split:disabled { opacity: .45; cursor: default; }
  .source-tools { inset-inline-end: auto; inset-inline-start: -5px; direction: ltr; }
  .source-card:hover > .source-tools, .source-card:focus-within > .source-tools { display: inline-flex; }
  .card-tools .card-btn.merge { width: 18px; height: 18px; }
  .card-tools .card-btn.merge :global(svg) { width: 12px; height: 12px; stroke-width: 2.4; }
  .card-tools .card-btn.merge:hover:not(:disabled), .card-tools .card-btn.merge:focus-visible { color: var(--accent); background: var(--accent-bg); }
  .picked-count { flex: none; border-radius: 999px; padding: 1px 8px; font-size: var(--fs-3xs); font-weight: 600; white-space: nowrap; color: var(--accent); background: var(--accent-bg); }
  .bank { touch-action: none; }
  /* A verse's word bank fills its verse block (2026-11-16, Joel): the block is
     often taller than its words, because it is as tall as the same verse's
     source words beside it, and that empty room must start a selection box
     and take a drop, not only the strip the words sit in. Nothing is drawn
     differently. */
  .targets .verse-block { display: flex; flex-direction: column; }
  .targets .bank { flex: 1 1 auto; }
  .bank.marquee-active { user-select: none; cursor: crosshair; }
  .marquee { position: fixed; z-index: var(--z-popover); pointer-events: none; border: 1px solid var(--accent); background: color-mix(in srgb, var(--accent) 14%, transparent); border-radius: 3px; }
  .null-card { border: 1px dashed var(--border-strong); background: var(--surface-2); color: var(--text-2); }
  .null-card.invalid { border-color: var(--danger); }
  .null-card small { color: var(--text-3); font-weight: 400; }
  .null-reason { font-family: var(--font-ui); font-size: var(--fs-2xs); font-weight: 700; white-space: nowrap; }
  /* 2026-11-25 (Joel): a "no counterpart" decision is a chip the height of a
     target word, centred in the cell like one: the reason, then who decided
     it ("ai" in the accent colour, as on an aligned card). `.token.` in the
     selector because `.token`, further down, is a column for every card. */
  .token.null-card { flex-direction: row; align-items: center; justify-content: center; gap: 5px; box-sizing: border-box; min-width: 0; min-height: 2rem; padding: .1rem .55rem; border-radius: 6px; }
  .null-card > small.ai { color: var(--accent); font-weight: 700; }
  .suggest-card { border: 1px dotted var(--accent); background: var(--surface); }
  .suggest-card.disputed { border-color: var(--warning); }
  .suggest-card small { color: var(--text-3); }
  /* 2026-11-25 (Joel): a suggestion is two short lines with its accept and
     dismiss beside them. It was meant to be this grid from the start, but
     `.token` (a column, further down, same weight) won, so the card stood as
     four things one under another. The two buttons are 22px round targets
     that show the pointer, the press and the keyboard focus. */
  .token.suggest-card { display: inline-grid; grid-template-columns: minmax(0, 1fr) auto auto; grid-template-rows: auto auto; column-gap: 2px; row-gap: 0;
    align-items: center; justify-items: start; box-sizing: border-box; min-height: 2rem; padding: 2px 3px 2px 8px; border-radius: 6px; }
  .suggest-card > .word, .suggest-card > .null-reason { grid-column: 1; grid-row: 1; }
  .suggest-card > small { grid-column: 1; grid-row: 2; }
  .suggest-card > button { grid-row: 1 / span 2; display: grid; place-items: center; flex: none; width: 22px; height: 22px; padding: 0; border: 0; border-radius: 50%; background: transparent;
    transition: background-color .12s, transform .08s; }
  .suggest-card > button :global(svg) { width: 13px; height: 13px; stroke-width: 2.6; }
  .suggest-card > .accept-x { color: var(--success); }
  .suggest-card > .unalign-x { color: var(--text-2); }
  .suggest-card > .accept-x:hover:not(:disabled), .suggest-card > .accept-x:focus-visible { background: var(--success-bg); }
  .suggest-card > .unalign-x:hover:not(:disabled), .suggest-card > .unalign-x:focus-visible { color: var(--danger); background: var(--danger-bg); }
  .suggest-card > button:active:not(:disabled) { transform: scale(.9); }
  .suggest-card > button:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
  @media (prefers-reduced-motion: reduce) { .suggest-card > button { transition: none; } }
  .accept-x { border: 0; background: none; padding: 0; width: 16px; height: 16px; line-height: 1; display: inline-flex; align-items: center; justify-content: center; border-radius: 50%; color: var(--success); font-size: var(--fs-sm); font-weight: 800; }
  .accept-x:hover:not(:disabled) { background: #EAF7EF; }
  .issue-badge { display: inline-flex; align-items: center; gap: 4px; border-radius: 999px; padding: 1px 8px; font-size: var(--fs-2xs); font-weight: 700; white-space: nowrap; color: #8A4B05; background: var(--warning-bg); }
  .issue-action { border: 0; background: none; padding: 0; color: var(--accent); font-size: var(--fs-2xs); text-decoration: underline; }
  .bank-item { display: inline-flex; flex-direction: column; align-items: center; gap: 3px; max-width: 100%; }
  .token.target.unaligned.flag-add { outline: 1px solid var(--warning); }
  .token.target.unaligned.flag-sugg { border-style: dotted; border-color: var(--warning); }
  .option { display: inline-flex; align-items: center; gap: 4px; font-size: var(--fs-3xs); color: var(--text-2); }
  .option .greek { font-family: var(--font-greek); }
  .null-word { position: relative; display: inline-flex; flex-direction: column; align-items: center; gap: 2px; border: 1px dashed var(--border-strong); background: var(--surface-2); color: var(--text-2); border-radius: 7px; padding: 4px 8px; }
  .null-word small { font-family: var(--font-ui); font-size: var(--fs-3xs); color: var(--text-3); }
  .menu-overlay { position: fixed; inset: 0; z-index: var(--z-dialog-over-dialog); display: grid; place-items: center; background: rgba(15, 20, 26, .2); }
  .issue-menu { background: var(--surface); border: 1px solid var(--border-strong); border-radius: 9px; box-shadow: 0 10px 30px rgba(0, 0, 0, .18); padding: 6px; display: grid; gap: 2px; min-width: 260px; }
  .issue-menu .menu-title { font-size: var(--fs-3xs); color: var(--text-3); padding: 4px 8px 6px; font-weight: 700; }
  .issue-menu button { border: 0; text-align: left; padding: 6px 8px; font-size: var(--fs-xs); border-radius: 6px; }
  .issue-menu button small { display: block; color: var(--text-3); font-size: var(--fs-3xs); }
  .issue-menu button:hover { background: var(--accent-bg); }
  .status { flex: none; border-radius: 999px; padding: 1px 8px; background: var(--surface-2); font-weight: 700; font-size: var(--fs-3xs); color: var(--text-2); white-space: nowrap; }
  .status.complete, .status.complete_cross_verse { color: var(--success); background: var(--success-bg); }
  .status.partial { color: var(--warning); background: var(--warning-bg); }
  .status.invalid { color: var(--danger); background: var(--danger-bg); }
  .error { border-radius: 8px; padding: 5px 10px; margin: 4px 10px 0; font-size: var(--fs-2xs); line-height: 1.45; flex-shrink: 0; background: var(--danger-bg); color: var(--danger); }
  /* The note and an error: over the foot of the tab, never a row of the page. */
  .toasts { position: absolute; left: 50%; bottom: 12px; z-index: 6; transform: translateX(-50%); display: flex; flex-direction: column; align-items: center; gap: 6px;
    width: max-content; max-width: min(560px, calc(100% - 24px)); pointer-events: none; }
  .toast { display: flex; align-items: flex-start; gap: 8px; box-sizing: border-box; max-width: 100%; padding: 6px 12px; border: 1px solid; border-radius: 8px;
    font-size: var(--fs-2xs); font-weight: 600; line-height: 1.4; box-shadow: 0 6px 20px rgba(0,0,0,.16); pointer-events: auto; }
  .toast.ok { border-color: color-mix(in srgb, var(--success) 35%, transparent); background: var(--success-bg); color: var(--success); }
  .toast.bad { border-color: color-mix(in srgb, var(--danger) 40%, transparent); background: var(--danger-bg); color: var(--danger); }
  .toast-close { flex: none; display: grid; place-items: center; width: 18px; height: 18px; padding: 0; border: 0; border-radius: 5px; background: transparent; color: inherit; }
  .toast-close :global(svg) { width: 12px; height: 12px; }
  .error-detail { margin-top: 4px; color: var(--text-2); }
  .error-detail summary { cursor: pointer; font-size: var(--fs-xs); }
  .error-detail code { display: block; margin-top: 4px; white-space: pre-wrap; overflow-wrap: anywhere; font-size: var(--fs-xs); }

  /* The verses to read: a quiet read-only card, as on the Word alignment tab. */
  .reading { padding: 8px 12px; border-radius: 8px; background: var(--surface-2); border-inline-start: 3px solid color-mix(in srgb, var(--accent) 40%, var(--border)); }
  .reading { padding-top: 4px; padding-bottom: 4px; }
  .range-reading { display: flex; align-items: baseline; gap: 8px; margin: 0; padding: 1px 0; border-top: 1px solid color-mix(in srgb, var(--border) 70%, transparent);
    font-family: var(--font-target); font-size: clamp(var(--fs-sm), 0.72rem + 0.6cqw, var(--fs-md)); line-height: 1.7; }
  .range-reading:first-child { border-top: 0; }
  .read-num { flex: none; min-width: 1.5em; text-align: end; font-family: var(--font-ui); font-size: var(--fs-3xs); font-weight: 700; color: var(--text-3); font-variant-numeric: tabular-nums; }
  .read-text { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .col { display: flex; flex-direction: column; min-height: 0; }
  /* #495: verseRowSync gives a verse block the height of its partner in the
     other column as min-height, measured border to border. */
  .verse-block { box-sizing: border-box; }
  /* The panel body is the scroller; this only keeps a wide line from drawing sideways (#72). */
  .scroll { overflow-x: clip; min-height: 0; flex: 1; }
  .verse-block { padding: 6px 0 10px; border-bottom: 1px dashed var(--border); }
  .verse-block:last-child { border-bottom: 0; }
  .verse-head { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; min-height: 24px; padding: 4px 0; position: sticky; top: 0; background: var(--surface); z-index: 3; font-size: var(--fs-2xs); }
  .vnum { font-weight: 800; color: var(--text); }
  .warn { color: var(--warning); }
  /* #136: the source cells flow in the source direction and wrap, so one verse
     occupies several short rows instead of one tall column. #493: a wrapping
     flex row, not the fixed-track grid it was -- a fixed track is one card
     wide, so a cell holding several target words stacked them one below
     another. Now a cell is one card wide at least and as wide as its own row
     of words needs, up to the column, and wraps from there, like the
     single-verse interlinear. Still no sideways scroll (#72): min(.., 100%)
     and max-width keep a cell inside the column, which `.scroll` would
     otherwise clip. */
  /* 13px on top: the merge button of a card in the first row sits 11px above
     it and was cut off by the edge above (2026-11-18, Joel). */
  .rows { display: flex; flex-wrap: wrap; align-items: flex-start; align-content: flex-start; gap: 10px 8px; padding: 13px 6px 4px; }
  .rows .empty { flex-basis: 100%; }
  /* Source word above its drop cell rather than beside it, matching the
     single-verse interlinear. */
  /* As wide as its source card, so the empty box is too (2026-11-17, Joel). */
  .row { display: flex; flex-direction: column; align-items: center; gap: 3px; min-width: 0; max-width: 100%; flex-shrink: 0; }
  /* Room for a merged group's ring, so it stands as far from its neighbours
     as two single cards do (2026-11-18, Joel). */
  .row.joined { box-sizing: border-box; padding-inline: 3px; }
  .token { display: inline-flex; flex-direction: column; align-items: center; gap: 2px; min-width: 44px; }
  /* max-width: 100% (was a fixed 160px): inside a flowed cell (#136) the label
     must ellipsize within its own track, or a long one widens the source column
     and squeezes the drop cell below it. */
  .token small { font-size: var(--fs-3xs); color: var(--text-3); max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  /* The gloss replaced the lemma here, so it must undo what the lemma needed:
     `.token.source` carries the Greek/Hebrew face and, for an OT book, dir=rtl
     -- both wrong for an English definition. Two lines rather than one
     ellipsized one, because at 150px a single line of definition is mostly the
     ellipsis; the unabridged text stays in the tooltip and the lexicon popup. */
  .gloss {
    font-family: var(--font-ui); direction: ltr; text-align: center;
    white-space: normal; line-height: 1.25; max-width: 120px;
    display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; line-clamp: 2;
  }
  .occ { margin-left: 3px; font-size: 0.8em; font-weight: 400; color: var(--text-3); }
  /* min-width: 0 overrides `.token`'s 62px so the source cell can shrink inside
     a flowed track (#136) and ellipsize, instead of overflowing it. */
  /* The cards and cells are the Word alignment tab's, value for value
     (2026-11-16, Joel): the tinted source card, the centred cell whose
     dashed box shows only while it is empty, the blue target words. */
  .token.source { background: var(--term-bg); border-color: color-mix(in srgb, var(--term) 22%, var(--border)); cursor: pointer; font-family: var(--font-greek); }
  .token.source:hover:not(:disabled) { border-color: var(--term); background: color-mix(in srgb, var(--term-bg) 55%, var(--surface)); }
  .token.source.hebrew { font-family: var(--font-hebrew); }
  .drop-cell { display: flex; flex-direction: row; flex-wrap: wrap; align-items: center; justify-content: center; align-content: flex-start;
    gap: 4px; width: 100%; box-sizing: border-box; min-height: 32px; padding: 3px; border-radius: 6px; border: 1px dashed transparent; }
  .drop-cell:has(.placeholder) { border-color: var(--border); }
  .drop-cell.drop-hover { background: var(--accent-bg); border-color: var(--accent); outline: 1px dashed var(--accent); }
  .bank.drop-hover { background: var(--accent-bg); outline: 2px dashed var(--accent); }
  .drop-cell .placeholder { color: var(--text-3); font-size: var(--fs-sm); line-height: 1; }
  .token.target { font-family: var(--font-target); touch-action: none; user-select: none; }
  .token.target.unaligned { background: var(--accent-bg); border-color: color-mix(in srgb, var(--accent) 35%, var(--border)); color: var(--text); }
  .token.picked { outline: 2px solid var(--accent); outline-offset: 1px; }
  .already-aligned { background: var(--surface-2); border: 1px solid var(--border); color: var(--text-3); border-radius: 6px; cursor: default; }
  .aligned-card { border: 1px solid color-mix(in srgb, var(--accent) 35%, var(--border)); border-radius: 6px; background: var(--accent-bg); }
  .linked-card { border: 1px dashed var(--accent); border-radius: 6px; background: var(--accent-bg); }
  .accounted { border: 1px dashed var(--accent); border-radius: 6px; background: var(--surface-2); color: var(--text-3); }
  .linked-card small, .accounted small { font-size: var(--fs-3xs); color: var(--accent); font-weight: 700; white-space: nowrap; }
  .linked-card.invalid { border-color: var(--danger); background: var(--danger-bg); }
  .linked-card.invalid small { color: var(--danger); }
  .bank { display: flex; flex-wrap: wrap; gap: 6px; min-height: 44px; align-content: flex-start; border-radius: 6px; padding: 12px 6px 6px; }
  .drag-ghost { position: fixed; z-index: var(--z-popover); transform: translate(-50%, -130%); pointer-events: none; background: var(--accent); color: white; font-family: var(--font-target); font-size: var(--fs-sm); font-weight: 700; border-radius: 7px; padding: 6px 10px; box-shadow: 0 8px 20px rgba(0,0,0,.28); }
  .empty { color: var(--text-3); font-size: var(--fs-xs); margin: 6px 10px; }
  /* In the Alignment tab (2026-11-15): the pane is the frame, so no backdrop,
     shadow or rounding. Last in the sheet, after the rules it changes. */
  .embedded.overlay { position: absolute; inset: 0; z-index: auto; display: block; padding: 0; background: var(--surface); }
  .embedded > .page { width: 100%; height: 100%; max-height: none; box-sizing: border-box; border-radius: 0; box-shadow: none; }
</style>
