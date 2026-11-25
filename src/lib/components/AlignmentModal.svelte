<script lang="ts">
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";
  import "../alignmentCards.css";
  import { edgeScrollStep } from "../alignmentLayout";
  import SourceSplitControls from "./SourceSplitControls.svelte";
  import AlignmentResetControls from "./AlignmentResetControls.svelte";
  import { onMount } from "svelte";
  import { bridge as apiBridge } from "../api/bridgeClient";
  import { get } from "svelte/store";
  import { onDestroy } from "svelte";
  import { project as activeProject } from "../stores";
  import { bindReviewProject } from "../reviewProjectGuard";
  import { alignmentBusy, alignmentPinned } from "../alignmentWindow";
  import { askConfirmation } from "../confirmAction";
  import { BACKUPS_SHOWN, backupChange, backupLabel, backupTime } from "../alignmentBackups";
  const expectedPath = get(activeProject)?.path || "";
  const bridge = bindReviewProject(apiBridge, expectedPath);
  import { recheckVerse } from "../verseChecks";
  import { perfAbort, perfBegin, perfEnd, perfResponded } from "../perf";
  import {
    alignmentStatusByVerse, chapterVerseNums, checkStatusByVerse, noteAlignmentChanged, project, selectedVerse, targetDir, targetLang,
    verseDisplay, verseKey,
  } from "../stores";
  import { alignmentStatusLabel } from "../alignmentStatus";
  import { bookDisplayName } from "../utils/reportStats";
  import type { AlignmentContext, AlignmentToken, CrossVerseLink } from "../types/finding";
  import { createPointerDrag } from "../alignmentDrag";
  import { createMarquee } from "../marqueeSelect";
  import { alignmentBusyElsewhere, crossVerseOpen, holdAlignmentBusy, openCrossVerse, showAlignmentTab, watchAlignmentChanges } from "../alignmentUi";
  import {
    alignedTargetsFor, bottomIdsAfterDrop, bottomIdsAfterStep, groupForSource, groupForTarget, occurrenceLabel as occurrence,
    sourceColumns, topIdsFor, unaccountedTargets, undoTargetId, type DropSlot,
  } from "../alignmentGroups";
  import { SourceGlossCache } from "../lexiconGloss";
  import LexiconPopup from "./LexiconPopup.svelte";
  import LayoutMenu from "./LayoutMenu.svelte";
  import WordPanels from "./WordPanels.svelte";
  import WordPanel from "./WordPanel.svelte";
  import { WORD_PANEL_PRESETS, applyWordPanelPreset, resetWordPanels, wordPanelPreset, wordPanelTree } from "../wordPanels";

  export let chapter: string;
  export let verse: string;
  export let onClose: () => void;
  export let onDetach: (() => void) | null = null;
  export let onPin: (() => void) | null = null;
  /** Move to another verse of the chapter (the header's arrows). The
   *  separate window passes its own: the editor's selection is not its. */
  export let onVerse: ((verse: string) => void) | null = null;
  export let standalone = false;
  /** Drawn inside the editor's Alignment tab (2026-11-15), not over the
   *  window: no backdrop, it fills its pane, the tab closes it and Escape
   *  does not. */
  export let embedded = false;
  // 2026-11-15: this editor and the cross-verse page can be open together,
  // as two tabs. Busy is held per editor, so one finishing does not clear
  // the other's save.
  const busyHolder = {};
  onDestroy(() => holdAlignmentBusy(busyHolder, false));

  let context: AlignmentContext | null = null;
  // #409: the verse as continuous text, with its punctuation, to read while
  // aligning (translationCore's "Step 1. Read", target language only). It is
  // the verse's `display.plain` -- the engine's one USFM reader, never a
  // sentence rebuilt from the cards -- so moving a card cannot change it. The
  // editor has already read the open chapter into `verseDisplay`; a verse not
  // there yet (opened before the chapter finished loading) is read once.
  let readingFallback = "";
  let readingFallbackKey = "";
  $: readingText = $verseDisplay[verseKey(chapter, verse)]?.plain ?? (readingFallbackKey === verseKey(chapter, verse) ? readingFallback : "");
  $: if (!$verseDisplay[verseKey(chapter, verse)] && readingFallbackKey !== verseKey(chapter, verse)) {
    const key = verseKey(chapter, verse);
    readingFallbackKey = key;
    readingFallback = "";
    void Promise.resolve().then(() => bridge.getVerse(chapter, verse)).then((data) => {
      if (readingFallbackKey === key) readingFallback = data?.display?.plain ?? data?.text ?? "";
    }).catch(() => { /* the cards still work without the reading line */ });
  }
  let lexiconToken: AlignmentToken | null = null;
  let loading = true;
  let busy = false;
  $: holdAlignmentBusy(busyHolder, busy);
  let error = "";
  let notice = "";
  // 2026-11-16 (Joel): "saved" is a note over the foot of the tab that goes
  // by itself; it was a row above the verse, which pushed the page down and
  // stayed.
  let noticeTimer: ReturnType<typeof setTimeout> | undefined;
  $: { clearTimeout(noticeTimer); if (notice) noticeTimer = setTimeout(() => (notice = ""), 4000); }
  onDestroy(() => clearTimeout(noticeTimer));
  // 2026-11-25 (Joel): an error goes by itself too, as in the Verses panel
  // and on the Cross-verse tab: after ten seconds, held while it is pointed
  // at, and its close button clears it at once. It stayed until it was
  // closed. One shown in place of the verse (it could not be read) stays.
  const ERROR_MS = 10000;
  let errorTimer: ReturnType<typeof setTimeout> | undefined;
  function holdError(): void { clearTimeout(errorTimer); errorTimer = undefined; }
  function scheduleErrorClear(text: string, verseShown: boolean): void {
    holdError();
    if (text && verseShown) errorTimer = setTimeout(() => (error = ""), ERROR_MS);
  }
  $: scheduleErrorClear(error, Boolean(context));
  onDestroy(holdError);

  // Interlinear drag/click-to-align state. `picked` is the click-based
  // accessible alternative to dragging: click a target word to pick it up,
  // click a column (or the word bank) to drop it there — same one-step
  // "drop" semantics as dragging, just keyboard/click operable. Several words
  // can be picked together (#285): Ctrl-click adds or removes one, Shift-click
  // takes the run from the last picked word, in the word bank and in the
  // aligned columns alike; they are placed in one save, so one undo step.
  // `anchor` is the last word picked on its own, where a Shift-click starts.
  let picked: string[] = [];
  let anchor: string | null = null;

  // Pointer-based drag lives in alignmentDrag.ts (shared with the cross-verse
  // page, #116); see that file for why it is not native HTML5 drag-and-drop.
  // `data-drop-column` carries the source token id, `data-drop-bank` is "true".
  // A drag that starts on a picked word carries the whole selection; one that
  // starts elsewhere supersedes it, as a real drag always superseded pick-up.
  // `data-drop-slot` on an aligned card (#410) says which card the drop
  // landed on, so the words go before or after it instead of last -- and a
  // card dragged within its own column is reordered.
  const drag = createPointerDrag({
    onDragStart: (tokenId) => { if (!picked.includes(tokenId)) picked = []; },
    onDrop: ({ tokenId, column, bank, slot }) => {
      const ids = picked.includes(tokenId) ? picked : [tokenId];
      picked = [];
      if (column) dropOntoColumn(ids, column, slot ? { id: slot.value, after: slot.after } : null);
      else if (bank) returnToBank(ids);
    },
  });
  const dragState = drag.state;

  // On a long verse a column can be above or below what the Source words
  // panel is showing. While a word is dragged inside that panel, near its top
  // or bottom edge, the panel scrolls a few px per frame (edgeScrollStep).
  let dialogEl: HTMLElement | undefined;
  let headEl: HTMLElement | undefined;
  let edgeEl: HTMLElement | null = null;
  let edgeStep = 0, edgeRaf = 0;
  function trackEdge(event: PointerEvent): void {
    edgeEl = $dragState.tokenId && $dragState.moved ? dialogEl?.querySelector<HTMLElement>('[data-word-panel="source"] .body') ?? null : null;
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

  // 2026-11-16 (Joel): the header's verse arrows. They move the editor's
  // selected verse, which this editor follows; pinned, it stays, so they are off.
  $: verseList = ($chapterVerseNums[chapter] ?? []).filter((v) => v !== "front");
  $: verseIndex = verseList.indexOf(verse);
  $: previousVerse = verseIndex > 0 ? verseList[verseIndex - 1] : undefined;
  $: nextVerse = verseIndex < verseList.length - 1 ? verseList[verseIndex + 1] : undefined;
  function goToVerse(target: string | undefined): void {
    if (!target || busy || $alignmentPinned) return;
    if (onVerse) onVerse(target); else selectedVerse.set(target);
  }

  // 2026-11-16 (Joel): reset and the backups are one menu on the bar (they
  // were a "History and reset" section under the target words). The menu is
  // drawn at the root, `fixed`, like the drag ghost: the bar clips its own.
  let menuOpen = false, menuPlace = "", resetPending = false;
  let menuButton: HTMLButtonElement | undefined, menuEl: HTMLElement | undefined;
  function toggleMenu(): void {
    if (menuOpen || !menuButton) { menuOpen = false; return; }
    const r = menuButton.getBoundingClientRect();
    menuPlace = `top:${r.bottom + 4}px;right:${Math.max(6, window.innerWidth - r.right)}px;max-height:${Math.max(160, window.innerHeight - r.bottom - 16)}px`;
    menuOpen = true;
  }
  function onMenuOutside(event: Event): void {
    const target = event.target as Node;
    if (menuOpen && !menuEl?.contains(target) && !menuButton?.contains(target)) menuOpen = false;
  }
  function onMenuClick(event: Event): void {
    if ((event.target as HTMLElement).closest("button")) menuOpen = false;
  }
  // #410: rubber-band selection in the word bank. Press on empty space, drag
  // a rectangle, and the unaligned words it touches are picked -- the same
  // `picked` list Ctrl-click and Shift-click fill, so the words then move
  // together by one drag or one column click. With Ctrl held at the press the
  // rectangle adds to what was picked; otherwise it replaces it.
  let pickedBeforeMarquee: string[] = [];
  const marquee = createMarquee({
    onStart: (additive) => { pickedBeforeMarquee = additive ? picked : []; },
    onChange: (hits) => {
      picked = [...pickedBeforeMarquee, ...hits.filter((id) => !pickedBeforeMarquee.includes(id))];
    },
    onEnd: (hits) => { if (hits.length) anchor = hits[hits.length - 1]; },
  });
  const marqueeState = marquee.state;

  $: carried = $dragState.tokenId ? (picked.includes($dragState.tokenId) ? picked : [$dragState.tokenId]) : [];
  $: ghostLabel = carried.length
    ? (context?.bottomTokens ?? []).filter((t) => carried.includes(t.id)).map((t) => t.word).join(" ")
    : "";

  /** The target words that can be picked, in verse order: every word of the
   *  verse except one a cross-verse link accounts for. A Shift-click takes a
   *  run of this list. */
  $: pickable = context ? context.bottomTokens.filter((t) => !accountedIds.has(t.id)).map((t) => t.id) : [];
  $: pickedWords = (context?.bottomTokens ?? []).filter((t) => picked.includes(t.id)).map((t) => t.word);

  // Resolved lexicon glosses for the source tokens: the English sense goes
  // under the word and the lemma moves into the tooltip, because a lemma is
  // one more Greek/Hebrew string and tells a non-reader of those scripts
  // nothing. Fetched once on load — source tokens don't change across
  // alignment edits. `glossVersion` is what makes the labels re-render when
  // the lookups land.
  const glosses = new SourceGlossCache();
  let glossVersion = 0;

  onMount(load);

  onMount(() => drag.attach(window));
  onMount(() => marquee.attach(window));

  async function load() {
    loading = true;
    error = "";
    try {
      context = await bridge.getAlignment(chapter, verse);
      void glosses.load(context.topTokens).then(() => (glossVersion = glosses.version));
    } catch (value) {
      error = value instanceof Error ? value.message : String(value);
    } finally {
      loading = false;
    }
  }

  // The verse was written somewhere else (the Cross-verse tab, the verse
  // editor, an automatic pass): read it again, quietly, once nothing is
  // saving. Without this the next save here is refused as stale.
  let changedOutside = false;
  onDestroy(watchAlignmentChanges(() => [verseKey(chapter, verse)], () => busy, () => { changedOutside = true; }));
  $: if (changedOutside && !$alignmentBusy && !loading) { changedOutside = false; void reloadFromOutside(); }
  async function reloadFromOutside() {
    if (expectedPath && get(activeProject)?.path !== expectedPath) return;
    try {
      const next = await bridge.getAlignment(chapter, verse);
      if (busy) { changedOutside = true; return; }
      context = next;
      picked = [];
      void glosses.load(next.topTokens).then(() => (glossVersion = glosses.version));
    } catch { /* the next save here reports it */ }
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
  const exactTime = (timestamp: string): string => { const date = new Date(timestamp); return Number.isNaN(date.getTime()) ? timestamp : date.toLocaleString(); };

  // #117: a word that a cross-verse link accounts for is still in the tC word
  // bank (translationCore alignment is verse-local) but is no longer a gap.
  $: unalignedCount = context ? unaccountedTargets(context).length : 0;
  $: accountedIds = new Set(context?.crossVerseAccountedIds ?? []);
  $: linkedCount = context ? context.crossVerseAccounted + context.crossVerseRealized : 0;
  $: accountedNote = linkedCount > 0
    ? `${linkedCount} word${linkedCount === 1 ? "" : "s"} linked across verses (Bridge-private; completion stays with translationCore).`
    : "";

  // #148: the book is not in the modal's props, but it is in the project store
  // and both call sites are inside the open book. `bookName` can be a vernacular
  // header name (import reads USFM \h/\toc2) and falls back to the raw book id
  // when the tC manifest has no project.name -- so the code only joins the name
  // when it adds something, or the title reads "gen (GEN)".
  $: bookLabel = $project ? bookDisplayName($project) : "";
  $: bookCode = $project ? $project.bookId.toUpperCase() : "";
  $: reference = bookLabel && bookLabel.toLowerCase() !== bookCode.toLowerCase()
    ? `${bookLabel} (${bookCode}) ${chapter}:${verse}`
    : `${bookCode ? `${bookCode} ` : ""}${chapter}:${verse}`;

  // #148: the structural issues live behind a red button in the status row
  // rather than an always-open block. Hover reveals, click pins.
  let issuesPinned = false;
  let issuesHovered = false;
  $: issuesOpen = issuesPinned || issuesHovered;
  let issuesWrap: HTMLElement | null = null;

  // Same capture-phase outside-pointerdown close as FindingContextMenu.
  onMount(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (!issuesPinned) return;
      if (issuesWrap && event.target instanceof Node && issuesWrap.contains(event.target)) return;
      issuesPinned = false;
    };
    window.addEventListener("pointerdown", onPointerDown, true);
    return () => window.removeEventListener("pointerdown", onPointerDown, true);
  });

  function onEscape() {
    if (menuOpen) { menuOpen = false; return; }
    if (busy || lexiconToken) return;
    // A pinned popover swallows the first Escape; a second one closes the modal.
    if (issuesPinned) { issuesPinned = false; return; }
    // So does a selection (#285): Escape puts the picked words down first.
    if (picked.length) { picked = []; return; }
    if (!embedded) onClose();
  }

  async function refreshChecks(updated: AlignmentContext, message: string) {
    if (expectedPath && get(activeProject)?.path !== expectedPath) return;
    context = updated;
    const key = verseKey(chapter, verse);
    alignmentStatusByVerse.update((values) => ({ ...values, [key]: updated.status }));
    // Every save, unalign, undo and restore lands here; the Source text panel
    // re-reads the verse on this, not on the status, which most edits keep (#291).
    noteAlignmentChanged(key);
    checkStatusByVerse.update((values) => ({ ...values, [key]: "pending" }));
    try {
      // Only the alignment checks: the verse's other findings are kept, and
      // Greek Room runs on demand (#251, #252).
      await recheckVerse(chapter, verse, ["alignment"], { expectedPath });
      if (expectedPath && get(activeProject)?.path !== expectedPath) return;
      notice = `${message} The alignment checks are current.`;
    } catch (value) {
      if (expectedPath && get(activeProject)?.path !== expectedPath) return;
      checkStatusByVerse.update((values) => ({ ...values, [key]: "failed" }));
      error = `${message} The save succeeded, but rechecking failed: ${value instanceof Error ? value.message : String(value)}`;
    }
  }

  // `perfAction`: a PERF_ACTIONS name to time this mutation under (#412):
  // begun now, responded at the busy state, ended once the saved placement
  // and its re-check are in and the next operation is accepted; a failure
  // records no sample.
  async function mutate(action: () => Promise<AlignmentContext>, message: string, perfAction = "") {
    // Not while the other alignment tab is saving: it is about to change
    // what this one shows.
    if (busy || alignmentBusyElsewhere(busyHolder)) return;
    if (perfAction) perfBegin(perfAction);
    busy = true;
    if (perfAction) perfResponded(perfAction);
    error = "";
    notice = "";
    try {
      await refreshChecks(await action(), message);
    } catch (value) {
      error = value instanceof Error ? value.message : String(value);
    } finally {
      busy = false;
      if (perfAction) {
        if (error) perfAbort(perfAction); else void perfEnd(perfAction);
      }
    }
  }

  // 2026-11-16 (Joel, from the team): a cross-verse link is shown and removed
  // here as it is on the Cross-verse page, so removing a word behaves the same
  // on both. Making a link stays on that page: the other verse's words are
  // not on this one. Same call as that page's x, one link at a time.
  function linkForBottom(ctx: AlignmentContext, bottomId: string): CrossVerseLink | undefined {
    return ctx.crossVerseLinks.find((link) => link.targetBottomId === bottomId && link.state === "active");
  }
  function linksForSource(ctx: AlignmentContext | null, topId: string): CrossVerseLink[] {
    return (ctx?.crossVerseLinks ?? []).filter((link) => link.sourceTopId === topId);
  }
  function removeLink(link: CrossVerseLink) {
    void mutate(async () => {
      const result = await bridge.crossVerseUnlink(link.id);
      const here = (c: AlignmentContext) => c.chapter === chapter && c.verse === verse;
      const other = here(result.source) ? result.target : result.source;
      // The other end is another verse: its status, its readers (the
      // Cross-verse tab, the Source text panel) and its alignment checks.
      if (!here(other) && (!expectedPath || get(activeProject)?.path === expectedPath)) {
        const key = verseKey(other.chapter, other.verse);
        alignmentStatusByVerse.update((values) => ({ ...values, [key]: other.status }));
        noteAlignmentChanged(key);
        try { await recheckVerse(other.chapter, other.verse, ["alignment"], { expectedPath }); } catch { /* this verse's recheck reports */ }
      }
      return here(result.source) ? result.source : result.target;
    }, "Cross-verse link removed.");
  }

  // Every drop/click-drop realigns the source column's FULL target set
  // (existing members + the newly placed words); bottomIdsAfterDrop explains
  // why. Several words picked together (#285) are one realign call, so one
  // history row, one undo step and one re-check.
  function dropOntoColumn(targetIds: string[], sourceId: string, at: DropSlot | null = null) {
    if (!context || targetIds.length === 0) return;
    const bottomIds = bottomIdsAfterDrop(context, sourceId, targetIds, at);
    if (!bottomIds) return; // already in this column, in place
    // Every source word of the column (#207): a drop on a joined column must
    // not split it back into one word's group.
    const topIds = topIdsFor(context, sourceId);
    const moved = bottomIds.length - (groupForSource(context, sourceId)?.bottomIds.length ?? 0);
    void mutate(
      () => bridge.realignWords(chapter, verse, topIds, bottomIds, context!.alignment),
      moved > 1 ? `${moved} words placed together.` : moved === 0 ? "Word order changed." : "Alignment saved.",
      "alignment.drop",
    );
  }

  // #410: the click-operable way to reorder a column: the up and down
  // buttons on an aligned card move it one place. Same realign call as a
  // drop, so one undo step.
  function stepWithinColumn(sourceId: string, targetId: string, delta: -1 | 1) {
    if (!context) return;
    const bottomIds = bottomIdsAfterStep(context, sourceId, targetId, delta);
    if (!bottomIds) return;
    void mutate(
      () => bridge.realignWords(chapter, verse, topIdsFor(context!, sourceId), bottomIds, context!.alignment),
      "Word order changed.",
      "alignment.drop",
    );
  }

  // #207: a source word split into several tokens whose translation is one
  // joined target word is one tC group with several topWords. The engine's
  // realign has always accepted that; the surface could not ask for it.
  // "Join" folds a column into the one before it (split source words sit
  // side by side); "Split" takes the last source word out again, which the
  // engine keeps as its own empty group. Neither needs a target word
  // (2026-11-18, Joel and the team): two columns with nothing under them
  // merge, and a merged column whose target word was taken away splits.
  $: columns = context ? sourceColumns(context) : [];
  function columnBottomIds(ids: string[]): string[] {
    return context ? (alignedTargetsFor(context, ids[0]).map((t) => t.id)) : [];
  }
  function joinWithPrevious(index: number) {
    if (!context || index <= 0) return;
    const previous = columns[index - 1];
    const current = columns[index];
    const bottomIds = [...columnBottomIds(previous.ids), ...columnBottomIds(current.ids)];
    void mutate(
      () => bridge.realignWords(chapter, verse, [...previous.ids, ...current.ids], bottomIds, context!.alignment),
      "Source words joined.",
    );
  }
  // 2026-11-17 (Joel): a merged column splits at the seam that was clicked,
  // with no left or right to choose. The words before the seam keep the
  // target words; the ones after it become their own column, in place, so
  // the source order never changes.
  function splitAt(index: number, place: number) {
    if (!context) return;
    const column = columns[index];
    const bottomIds = columnBottomIds(column.ids);
    if (place <= 0 || place >= column.ids.length) return;
    void mutate(
      () => bridge.realignWords(chapter, verse, column.ids.slice(0, place), bottomIds, context!.alignment),
      "Source words split.",
    );
  }

  // The aligned ones among `targetIds` go back in one unalign call; a word
  // already in the bank has nowhere to go.
  function returnToBank(targetIds: string[]) {
    if (!context) return;
    const aligned = targetIds.filter((id) => groupForTarget(context!, id));
    if (aligned.length === 0) return;
    void mutate(
      () => bridge.unalignWords(chapter, verse, aligned, context!.alignment),
      aligned.length > 1 ? `${aligned.length} words returned to the word bank.` : "Returned to word bank.",
    );
  }

  // A plain click picks one word up, or puts the only picked word down: the
  // one-word path as it was. Ctrl (or ⌘) adds or removes a word; Shift takes
  // the run from the anchor to this word, in verse order (#285).
  function handleWordClick(id: string, event?: MouseEvent) {
    if (busy) return;
    if (drag.consumeSuppressedClick(id)) return;
    if (event?.ctrlKey || event?.metaKey) {
      picked = picked.includes(id) ? picked.filter((p) => p !== id) : [...picked, id];
      anchor = id;
      return;
    }
    if (event?.shiftKey && anchor && anchor !== id) {
      const from = pickable.indexOf(anchor);
      const to = pickable.indexOf(id);
      if (from >= 0 && to >= 0) {
        // 2026-11-17 (Joel): the run takes only words in the same place as the
        // one clicked. From one unaligned word to another it skips the words
        // between them that are already aligned (they sit in a column, and
        // were being picked up and moved with the rest); between two aligned
        // words it skips the unaligned ones. A box drawn over the same words
        // has always done this.
        const placed = (p: string): boolean => Boolean(context && groupForTarget(context, p));
        const want = placed(id);
        const run = pickable.slice(Math.min(from, to), Math.max(from, to) + 1).filter((p) => p === anchor || placed(p) === want);
        picked = [...picked, ...run.filter((p) => !picked.includes(p))];
        return;
      }
    }
    picked = picked.length === 1 && picked[0] === id ? [] : [id];
    anchor = id;
  }

  function handleColumnClick(sourceId: string) {
    if (!picked.length || busy) return;
    const ids = picked;
    picked = [];
    dropOntoColumn(ids, sourceId);
  }

  function handleBankAreaClick() {
    // The click that ends a rubber-band selection must not put it down (#410).
    if (marquee.consumeSuppressedClick()) return;
    if (!picked.length || busy) return;
    const ids = picked;
    picked = [];
    returnToBank(ids);
  }

  function startPointerTrack(event: PointerEvent, id: string) {
    if (busy) return;
    drag.start(event, id);
  }

  function startMarquee(event: PointerEvent) {
    if (busy) return;
    marquee.start(event, event.currentTarget as Element);
  }

  // #122: each undo is a `restore` row whose backup is the pre-undo state, and
  // alignment.undo restores the newest backup, so a second press re-applied
  // what the first undid. Undo now names the backup it wants (the newest edit
  // not yet undone, undoTargetId) through alignment.restore; the engine path
  // is unchanged. Disabled once every edit is undone.
  $: undoId = context ? undoTargetId(context.history) : null;
  function undo() {
    if (!context || !undoId) return;
    const id = undoId;
    void mutate(
      () => bridge.restoreAlignment(chapter, verse, id, context!.alignment),
      "Last alignment change undone.",
    );
  }

  // One backup from the menu's list. Asked first: it is one click on a row.
  async function restoreBackup(item: { id: string; timestamp: string; operation: string }) {
    if (!context || busy) return;
    const ok = await askConfirmation({ title: `Restore this backup of ${chapter}:${verse}?`,
      body: `The alignment of this verse goes back to how it was ${backupChange(item.operation)}: ${backupTime(item.timestamp)}.`,
      confirmLabel: "Go back to this version" });
    if (!ok || !context) return;
    void mutate(
      () => bridge.restoreAlignment(chapter, verse, item.id, context!.alignment),
      "Selected alignment backup restored.",
    );
  }
</script>

<svelte:window on:pointerdown|capture={onMenuOutside} on:resize={() => (menuOpen = false)} on:keydown={(event) => event.key === "Escape" && onEscape()} on:pointermove={trackEdge} on:pointerup={() => (edgeStep = 0)} />

<!-- 2026-11-16 (Joel): a one-line header that stays at the top, then three
     panels: the verse to read, the source words with their target words
     beneath, and the target words (WordPanels / WordPanel, wordPanels.ts).
     The panels are split from the bar's layout picker or by dragging a
     panel's title row; they fill the tab and share its width and height, and
     the lines between them drag. A panel with more words than room scrolls
     inside itself; a word box never does. It was one fixed column
     (2026-11-14), and before that AlignmentWorkspace's movable areas, which
     the cross-verse page still uses. -->
<div class="overlay" class:embedded role="presentation">
  <section class="modal alignment-cards" role={embedded ? "region" : "dialog"} aria-modal={embedded ? undefined : "true"} aria-label={`Word alignment ${reference}`} bind:this={dialogEl}>
    <header bind:this={headEl}>
      <!-- 2026-11-16 (Joel): the Verses panel's bar (EditorHeader): same height
           and type. The tab names the editor and the top bar the book, so the
           heading is kept for screen readers only. -->
      <h2 class="sr-only">Word alignment · {reference}</h2>
      <div class="place" role="group" aria-label="Verse navigation">
        <span class="bar-word">Chapter {chapter}</span>
        <span class="rule" aria-hidden="true" />
        <span class="bar-word">Verse {verse}</span>
        {#if verseList.length}<span class="bar-word of">of {verseList.length}</span>{/if}
        <span class="steps">
          <button type="button" class="tool" aria-label="Previous verse" disabled={busy || $alignmentPinned || !previousVerse}
            use:tooltip={$alignmentPinned ? "Pinned to this verse. Unpin to move" : previousVerse ? "Previous verse" : "Already at the first verse"}
            on:click={() => goToVerse(previousVerse)}><UiIcon name="chevronLeft" /></button>
          <button type="button" class="tool" aria-label="Next verse" disabled={busy || $alignmentPinned || !nextVerse}
            use:tooltip={$alignmentPinned ? "Pinned to this verse. Unpin to move" : nextVerse ? "Next verse" : "Already at the last verse"}
            on:click={() => goToVerse(nextVerse)}><UiIcon name="chevronRight" /></button>
        </span>
      </div>
      {#if context}<span class="status {context.status}">Verse: {alignmentStatusLabel(context.status)}</span>{/if}
      {#if context?.completionState === "completed"}<span class="completed">✓ Human-completed</span>{/if}
      <div class="tools">
        {#if context}
          <button type="button" class="tool" aria-label="Undo last change" disabled={busy || !undoId} on:click={undo}
            use:tooltip={"Undo last change: steps back through your changes, one per press"}><UiIcon name="undo" /></button>
          <button type="button" class="tool" class:alert={resetPending} bind:this={menuButton} aria-label="Reset and backups" aria-haspopup="menu" aria-expanded={menuOpen}
            use:tooltip={menuOpen ? "" : "Reset this verse, or go back to an earlier version"} on:click={toggleMenu}><UiIcon name="more" /></button>
        {/if}
        <LayoutMenu size={28} quiet presets={WORD_PANEL_PRESETS} current={wordPanelPreset($wordPanelTree)} onChoose={applyWordPanelPreset} onReset={resetWordPanels}
          hint="Layout: arrange the verse, the source words and the target words"
          resetHint="The verse on top, source and target words side by side, standard text sizes" />
        <button type="button" class="tool" aria-label={$alignmentPinned ? "Follow editor (verse is pinned)" : "Pin verse (following editor)"} aria-pressed={$alignmentPinned} disabled={busy}
          use:tooltip={$alignmentPinned ? "Pinned to this verse. Click to follow the verse selected in the editor" : "Following the editor's verse. Click to pin this verse"}
          on:click={() => onPin ? onPin() : alignmentPinned.update((v) => !v)}><UiIcon name={$alignmentPinned ? "pin" : "follow"} /></button>
        <!-- A tab that is open already is shown, not opened again on this verse (2026-11-16). -->
        <button type="button" class="tool" aria-label="Cross-verse alignment" disabled={busy}
          use:tooltip={$crossVerseOpen && !standalone ? "Cross-verse alignment is already open. Click to show it" : "Cross-verse alignment: this verse beside its neighbours"}
          on:click={() => { if (!embedded) onClose(); if ($crossVerseOpen && !standalone) showAlignmentTab("cross"); else openCrossVerse(verse); }}><UiIcon name="link" /></button>
        {#if onDetach && !standalone}<button type="button" class="tool" aria-label="Move to separate window" disabled={busy} use:tooltip={"Move to separate window"} on:click={onDetach}><UiIcon name="detach" /></button>{/if}
        {#if !embedded}<button type="button" class="tool" on:click={onClose} disabled={busy} aria-label="Close alignment editor" use:tooltip={"Close"}><UiIcon name="close" /></button>{/if}
      </div>
    </header>

    {#if loading}
      <div class="loading"><span class="spin" /> Loading alignment…</div>
    {:else if context}
      <!-- 2026-11-16 (Joel): the chapter's tally row is gone; the status bar
           under the editor has the chapter's alignment counts. The row is
           drawn only for a verse with structural issues, for their button. -->
      {#if context.issues.length > 0}
        <div class="summary">
          <span
            class="issues-wrap"
            bind:this={issuesWrap}
            role="presentation"
            on:mouseenter={() => (issuesHovered = true)}
            on:mouseleave={() => (issuesHovered = false)}
            on:focusin={() => (issuesHovered = true)}
            on:focusout={() => (issuesHovered = false)}
          >
            <button
              type="button"
              class="issues-button"
              aria-expanded={issuesOpen}
              aria-controls="alignment-issues"
              on:click={() => (issuesPinned = !issuesPinned)}
            >⚠ {context.issues.length} issue{context.issues.length === 1 ? "" : "s"}</button>
            {#if issuesOpen}
              <div class="issues-panel" id="alignment-issues" role="status">
                {#each context.issues as issue}<div>⚠ {issue}</div>{/each}
              </div>
            {/if}
          </span>
        </div>
      {/if}

      {#if !context.sourceAvailable}
        <div class="source-warning">
          <strong>Original-language source unavailable</strong>
          <span>{context.sourceMessage}</span>
        </div>
      {:else if context.status === "invalid"}
        <!-- #149: this is the translationCore invalid marker, which is not the
             structural-issues list -- the old wording claimed it was. -->
        <div class="alignment-flag">⚑ Marked invalid in translationCore.</div>
      {/if}

      {#if resetPending}<div class="alignment-flag">A reset of this verse was interrupted. Finish it from the menu on the bar (Resume reset) before other alignment changes.</div>{/if}
      <WordPanels>
        <WordPanel id="read">
          <div class="reading" role="region" aria-label={`Read ${reference}`}>
            {#if readingText}
              <p class="reading-text" dir={$targetDir} lang={$targetLang}>{readingText}</p>
            {:else}
              <p class="reading-empty">The verse text is not available to read.</p>
            {/if}
          </div>
        </WordPanel>

        <WordPanel id="source">
          <svelte:fragment slot="tools">
            <button type="button" class="hint" aria-label="Source words help"
              use:tooltip={"Click a word for its lexicon entry. Its target words sit in a row beneath it. Drag a target word along its row, or use its arrows, to change their order."}><UiIcon name="info" /></button>
          </svelte:fragment>
          <SourceSplitControls {context} {busy} onBusy={(value) => busy = value} onChanged={(values) => { context = values.find((v) => v.chapter === chapter && v.verse === verse) || context; }} />
          <div class="interlinear" dir={context.sourceDirection}>
          {#each columns as column, index (column.ids.join("+"))}
            {@const src = column.tokens[0]}
            {@const label = column.tokens.map((t) => t.word).join(" ")}
            <div class="column" class:joined={column.ids.length > 1}>
              <div class="source-words" class:joined={column.ids.length > 1}>
                {#each column.tokens as token, place (token.id)}
                  {#if place > 0}
                    <span class="seam"><button type="button" class="seam-split" on:click|stopPropagation={() => splitAt(index, place)} disabled={busy}
                      aria-label={`Split ${label} before ${token.word}`}
                      use:tooltip={"Split here"}><UiIcon name="unmerge" /></button></span>
                  {/if}
                  <div class="source-card">
                  {#if place === 0 && index > 0}
                    <span class="card-tools source-tools">
                      <button type="button" class="card-btn merge" on:click|stopPropagation={() => joinWithPrevious(index)} disabled={busy}
                        aria-label={`Join ${label} with the previous source word`}
                        use:tooltip={"Merge with the previous word: one target word for both"}><UiIcon name="merge" /></button>
                    </span>
                  {/if}
                  <button class="token source" dir={context.sourceDirection} on:click={() => (lexiconToken = token)} disabled={busy}
                    use:tooltip={sourceHint(token, glossVersion)}>
                    <span class="word">{token.word}{#if token.occurrences > 1}<span class="occ">{occurrence(token)}</span>{/if}</span>
                    {#if sourceGloss(token, glossVersion)}<small class="gloss">{sourceGloss(token, glossVersion)}</small>{/if}
                  </button>
                  </div>
                {/each}
              </div>
              <div
                class="target-cell"
                class:drop-hover={$dragState.overColumn === src.id}
                data-drop-column={src.id}
                dir={context.targetDirection}
                lang={$targetLang}
                role="button"
                tabindex="0"
                aria-label={picked.length > 1 ? `Align ${picked.length} picked-up words to ${label}`
                  : picked.length ? `Align picked-up word to ${label}` : `Target words aligned to ${label}`}
                on:click={() => handleColumnClick(src.id)}
                on:keydown={(event) => (event.key === "Enter" || event.key === " ") && (event.preventDefault(), handleColumnClick(src.id))}
              >
                {#each alignedTargetsFor(context, src.id) as item, at (item.id)}
                  {@const count = groupForSource(context, src.id)?.bottomIds.length ?? 0}
                  <!-- The word itself can be picked up and moved to another
                       column, alone or with others (#285). data-drop-slot
                       (#410): a drop on the card lands before or after it.
                       Its controls are one small toolbar on its top edge,
                       shown while the card is pointed at or focused
                       (2026-11-16): earlier and later when the column holds
                       several words, then remove. They were at the card's
                       two sides, where a neighbour's got in the way. -->
                  <div
                    class="token target aligned-card"
                    class:picked={picked.includes(item.id)}
                    class:insert-before={$dragState.moved && $dragState.overSlot?.value === item.id && !$dragState.overSlot.after}
                    class:insert-after={$dragState.moved && $dragState.overSlot?.value === item.id && $dragState.overSlot.after}
                    data-drop-slot={item.id}
                  >
                    <button
                      type="button"
                      class="pick"
                      on:pointerdown={(event) => startPointerTrack(event, item.id)}
                      on:click|stopPropagation={(event) => handleWordClick(item.id, event)}
                      disabled={busy}
                      aria-label={`Pick up ${item.word} from ${label}`}
                      aria-pressed={picked.includes(item.id)}
                    ><span class="word">{item.word}{#if item.occurrences > 1}<span class="occ">{occurrence(item)}</span>{/if}</span></button>
                    <span class="card-tools">
                      {#if count > 1}
                        <button type="button" class="card-btn step" on:click|stopPropagation={() => stepWithinColumn(src.id, item.id, -1)}
                          disabled={busy || at === 0} aria-label={`Move ${item.word} earlier`} use:tooltip={"Move earlier"}><UiIcon name="chevronLeft" /></button>
                        <button type="button" class="card-btn step" on:click|stopPropagation={() => stepWithinColumn(src.id, item.id, 1)}
                          disabled={busy || at === count - 1} aria-label={`Move ${item.word} later`} use:tooltip={"Move later"}><UiIcon name="chevronRight" /></button>
                      {/if}
                      <button type="button" class="card-btn unalign-x" on:click|stopPropagation={() => returnToBank([item.id])} disabled={busy}
                        aria-label={`Unalign ${item.word} from ${label}`} use:tooltip={"Remove"}><UiIcon name="close" /></button>
                    </span>
                  </div>
                {:else}
                  {#if !column.tokens.some((t) => linksForSource(context, t.id).length)}<span class="placeholder" aria-hidden="true">·</span>{/if}
                {/each}
                {#each column.tokens as linkedSource (linkedSource.id)}
                  {#each linksForSource(context, linkedSource.id) as link (link.id)}
                    <span class="token target link-card" class:invalid={link.state === "invalid"}
                      use:tooltip={link.state === "invalid"
                        ? (link.invalidReason ?? "This link no longer applies.")
                        : `Realized in verse ${link.target.verse} by ${link.target.word}. Bridge-private link; translationCore alignment is unchanged.`}>
                      <span class="word">{link.target.word}</span>
                      <small>{link.state === "invalid" ? "link invalid" : "↔"} v.{link.target.verse}</small>
                      <span class="card-tools"><button type="button" class="card-btn unalign-x" on:click|stopPropagation={() => removeLink(link)} disabled={busy}
                        aria-label={`Remove cross-verse link from ${linkedSource.word} to ${link.target.word} in verse ${link.target.verse}`}
                        use:tooltip={"Remove this cross-verse link"}><UiIcon name="close" /></button></span>
                    </span>
                  {/each}
                {/each}
              </div>
            </div>
          {:else}
            <p class="empty">No source tokens are present in this verse.</p>
          {/each}
          </div>
        </WordPanel>

        <WordPanel id="target">
          <svelte:fragment slot="tools">
            {#if picked.length > 1}
              <span class="chip picked-count" role="status" use:tooltip={`${pickedWords.join(" ")}. Click a column to place them, or press Esc to put them down`}>{picked.length} picked</span>
            {/if}
            {#if linkedCount > 0}
              <span class="chip linked" use:tooltip={accountedNote}>↔ {linkedCount} linked across verses</span>
            {/if}
            {#if unalignedCount > 0}
              <span class="chip remaining">{unalignedCount} remaining</span>
            {/if}
            <button type="button" class="hint" aria-label="Target words help"
              use:tooltip={"In verse order. Drag an unaligned (blue) word into a column, or click it then click a column. Ctrl-click adds a word, Shift-click a run, or drag a box anywhere in this panel to select several, then drag them to a column together. A click on empty space puts them down."}><UiIcon name="info" /></button>
          </svelte:fragment>
          <!-- The whole panel body is the word bank (2026-11-16): a selection
               box starts anywhere in it, a word can be dropped anywhere in it,
               and a click on its empty space puts the picked words down. -->
          <div
            class="tokens bank-tokens"
            class:drop-hover={$dragState.overBank !== null}
            class:marquee-active={$marqueeState.moved}
            data-drop-bank="true"
            on:pointerdown={startMarquee}
            dir={context.targetDirection}
            lang={$targetLang}
            role="button"
            tabindex="0"
            aria-label={picked.length > 1 ? `Return ${picked.length} picked-up words to the word bank`
              : picked.length ? "Return picked-up word to the word bank" : "Word bank"}
            on:click={handleBankAreaClick}
            on:keydown={(event) => (event.key === "Enter" || event.key === " ") && (event.preventDefault(), handleBankAreaClick())}
          >
            {#each context.bottomTokens as item (item.id)}
              {#if accountedIds.has(item.id)}
                {@const accountedBy = linkForBottom(context, item.id)}
                <span class="token target already-aligned accounted"
                  use:tooltip={accountedBy ? `Realizes ${accountedBy.source.word} from verse ${accountedBy.source.verse}. Bridge-private link; this word stays in the word bank for translationCore.` : "Accounted for by a cross-verse link (see Cross-verse alignment)"}>
                  <span class="word">{item.word}{#if item.occurrences > 1}<span class="occ">{occurrence(item)}</span>{/if}</span>
                  <small>↔{#if accountedBy} v.{accountedBy.source.verse}{/if}</small>
                  {#if accountedBy}
                    <span class="card-tools"><button type="button" class="card-btn unalign-x" on:click|stopPropagation={() => removeLink(accountedBy)} disabled={busy}
                      aria-label={`Remove cross-verse link from ${accountedBy.source.word} in verse ${accountedBy.source.verse} to ${item.word}`}
                      use:tooltip={"Remove this cross-verse link"}><UiIcon name="close" /></button></span>
                  {/if}
                </span>
              {:else if groupForTarget(context, item.id)}
                <span class="token target already-aligned" use:tooltip={"Already aligned"}><span class="word">{item.word}{#if item.occurrences > 1}<span class="occ">{occurrence(item)}</span>{/if}</span></span>
              {:else}
                <button
                  type="button"
                  class="token target unaligned"
                  class:picked={picked.includes(item.id)}
                  data-marquee-item={item.id}
                  aria-pressed={picked.includes(item.id)}
                  on:pointerdown={(event) => startPointerTrack(event, item.id)}
                  on:click|stopPropagation={(event) => handleWordClick(item.id, event)}
                  disabled={busy}
                ><span class="word">{item.word}{#if item.occurrences > 1}<span class="occ">{occurrence(item)}</span>{/if}</span></button>
              {/if}
            {:else}
              <p class="empty">This verse has no target words.</p>
            {/each}
          </div>
        </WordPanel>
      </WordPanels>
    {:else if error}
      <div class="error">{error}</div>
    {/if}
  </section>
  {#if context && (notice || error)}
    <div class="toasts">
      {#if error}
        <!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
        <div class="toast bad" role="alert" on:mouseenter={holdError} on:mouseleave={() => scheduleErrorClear(error, Boolean(context))}><span>{error}</span>
          <button type="button" class="toast-close" aria-label="Dismiss this message" on:click={() => (error = "")}><UiIcon name="close" /></button></div>
      {/if}
      {#if notice}<div class="toast ok" role="status">✓ {notice}</div>{/if}
    </div>
  {/if}
</div>

{#if context}
  <!-- svelte-ignore a11y-click-events-have-key-events -->
  <div class="menu" role="menu" tabindex="-1" aria-label="Reset and backups" hidden={!menuOpen} style={menuPlace} bind:this={menuEl} on:click={onMenuClick}>
    <AlignmentResetControls menu {context} {busy} onBusy={(value) => busy = value} onPending={(value) => (resetPending = value)} onError={(message) => (error = message)}
      onChanged={(values) => { context = values.find((v) => v.chapter === chapter && v.verse === verse) || context; }} />
    <div class="menu-label">Go back to an earlier version</div>
    {#each context.history.slice(0, BACKUPS_SHOWN) as item (item.id)}
      <button type="button" role="menuitem" class="menu-item" disabled={busy} use:tooltip={exactTime(item.timestamp)} on:click={() => void restoreBackup(item)}>{backupLabel(item)}</button>
    {:else}
      <div class="menu-empty">None yet: one is kept for each change.</div>
    {/each}
  </div>
{/if}

{#if lexiconToken}
  <LexiconPopup
    token={lexiconToken}
    direction={context?.sourceDirection ?? "rtl"}
    onClose={() => (lexiconToken = null)}
  />
{/if}

{#if $dragState.tokenId && $dragState.moved}
  <div class="drag-ghost" lang={$targetLang} style="left:{$dragState.ghost.x}px; top:{$dragState.ghost.y}px;">{ghostLabel}</div>
{/if}
{#if $marqueeState.moved && $marqueeState.rect}
  <div class="marquee" aria-hidden="true" style="left:{$marqueeState.rect.left}px; top:{$marqueeState.rect.top}px; width:{$marqueeState.rect.width}px; height:{$marqueeState.rect.height}px;"></div>
{/if}

<style>
  .overlay { position: fixed; inset: 0; z-index: var(--z-dialog); background: rgba(15, 20, 26, .58); display: grid; place-items: center; padding: 24px; }
  /* About 95% of the window (#484). The one scroller (#485); every block
     inside carries its own 14px side padding, so the header and the target
     words, which stick to its top and bottom, reach both edges. */
  .modal { width: min(95vw, 100%); max-height: calc(100vh - 48px); overflow: auto; background: var(--surface); border-radius: 12px; box-shadow: 0 24px 80px rgba(0,0,0,.24); padding: 0; color: var(--text); container-type: inline-size; font-size: var(--fs-xs); }
  /* The bar: the Verses panel's (EditorHeader): 36px, one row that never
     wraps, the same type sizes and 28px icon buttons. In a narrow pane the
     status chips go first, then "of N". */
  header { position: sticky; top: 0; z-index: 4; display: flex; align-items: center; gap: 8px; height: 36px; min-height: 36px; box-sizing: border-box; padding: 0 10px; overflow: hidden; background: var(--surface); border-bottom: 1px solid var(--border); }
  .sr-only { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
  .place { display: flex; align-items: center; gap: 6px; flex: none; }
  .bar-word { font-size: var(--fs-xs); font-weight: 700; color: var(--text); white-space: nowrap; }
  .bar-word.of { font-size: var(--fs-2xs); font-weight: 600; color: var(--text-2); }
  .rule { width: 1px; height: 18px; flex: none; background: var(--border); }
  .steps { display: inline-flex; align-items: center; gap: 2px; }
  .tools { display: flex; align-items: center; gap: 2px; flex: none; margin-left: auto; }
  button { font: inherit; }
  button { border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); border-radius: 6px; padding: 4px 9px; cursor: pointer; }
  button:hover:not(:disabled) { border-color: var(--accent); }
  button:disabled { opacity: .5; cursor: not-allowed; }
  /* The editor's icon buttons: grey at rest, a grey square on hover, the
     accent colour when on (the left rail's style). */
  .tool, .hint { display: grid; place-items: center; flex: none; width: 28px; height: 28px; padding: 0; border: 0; border-radius: 7px; background: transparent; color: var(--text-2); }
  .tool :global(svg) { width: 16px; height: 16px; }
  .tool:hover:not(:disabled), .hint:hover { background: var(--bg); color: var(--text); }
  .tool[aria-pressed="true"], .tool[aria-pressed="true"]:hover:not(:disabled) { color: var(--accent); }
  .tool:focus-visible, .hint:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .hint { width: 20px; height: 20px; color: var(--text-3); cursor: help; }
  .hint :global(svg) { width: 14px; height: 14px; }
  .loading { padding: 36px; display: flex; gap: 10px; justify-content: center; color: var(--text-2); }
  .spin { width: 12px; height: 12px; border: 2px solid var(--accent-bg); border-top-color: var(--accent); border-radius: 50%; animation: spin .8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { .toast.ok { animation: none; } }
  .summary { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 10px; font-size: var(--fs-2xs); color: var(--text-2); padding: 4px 14px; }
  .status, .completed { flex: none; border-radius: 999px; padding: 1px 8px; background: var(--surface-2); color: var(--text-2); font-size: var(--fs-3xs); font-weight: 700; white-space: nowrap; }
  .status.complete, .status.complete_cross_verse, .completed { color: var(--success); background: var(--success-bg); }
  .status.partial { color: var(--warning); background: var(--warning-bg); }
  .status.invalid { color: var(--danger); }
  .status.invalid { background: var(--danger-bg); }
  /* #148: the structural issues sit behind this button instead of an open block
     above the columns. Anchored, not a centred overlay like LexiconPopup -- it
     belongs to the row it came from. It opens downward near the top of a modal
     that scrolls, so it stays inside and needs no portal. */
  .issues-wrap { position: relative; margin-left: auto; }
  .issues-button { border: 0; background: none; padding: 1px 6px; font-size: var(--fs-2xs); font-weight: 700; color: var(--danger); border-radius: 6px; }
  .issues-button:hover:not(:disabled), .issues-button[aria-expanded="true"] { background: var(--danger-bg); border-color: transparent; }
  .issues-panel {
    position: absolute; top: calc(100% + 4px); right: 0; z-index: var(--z-dropdown); width: min(320px, 80cqw);
    background: var(--surface); color: var(--danger); border: 1px solid var(--danger); border-radius: 8px;
    padding: 8px 10px; font-size: var(--fs-xs); line-height: 1.45; text-align: left;
    box-shadow: 0 10px 28px rgba(0,0,0,.16);
  }
  .issues-panel div + div { margin-top: 6px; }
  .source-warning, .error, .alignment-flag { border-radius: 6px; padding: 5px 10px; margin: 0 14px 6px; font-size: var(--fs-2xs); line-height: 1.45; }
  .source-warning { display: flex; flex-direction: column; gap: 3px; background: var(--warning-bg); color: var(--warning); }
  .alignment-flag { background: var(--warning-bg); color: var(--warning); font-weight: 600; }
  .already-aligned.accounted { position: relative; border-style: dashed; border-color: var(--accent); flex-direction: row; gap: 5px; }
  .already-aligned.accounted small { color: var(--accent); font-weight: 700; }
  /* 2026-11-16: a source word realized in another verse, under its column:
     the Cross-verse page's linked card, with the same x. */
  .link-card { position: relative; flex-direction: row; align-items: center; gap: 4px; min-width: 0; border: 1px dashed var(--accent); border-radius: 6px; background: var(--accent-bg); color: var(--text); cursor: default; }
  .link-card .word { font-size: var(--fs-sm); }
  .link-card small { color: var(--accent); font-weight: 700; white-space: nowrap; }
  .link-card.invalid { border-color: var(--danger); background: var(--danger-bg); }
  .link-card.invalid small { color: var(--danger); }
  .error { background: var(--danger-bg); color: var(--danger); }
  /* The saved note and an error: over the foot of the tab, never a row of
     the page. */
  .toasts { position: absolute; left: 50%; bottom: 12px; z-index: 6; transform: translateX(-50%); display: flex; flex-direction: column; align-items: center; gap: 6px;
    width: max-content; max-width: min(520px, calc(100% - 24px)); pointer-events: none; }
  .toast { display: flex; align-items: flex-start; gap: 8px; box-sizing: border-box; max-width: 100%; padding: 6px 12px; border: 1px solid; border-radius: 8px;
    font-size: var(--fs-2xs); font-weight: 600; line-height: 1.4; box-shadow: 0 6px 20px rgba(0,0,0,.16); pointer-events: auto; }
  .toast.ok { border-color: color-mix(in srgb, var(--success) 35%, transparent); background: var(--success-bg); color: var(--success); animation: toast-in .15s ease-out; }
  .toast.bad { border-color: color-mix(in srgb, var(--danger) 40%, transparent); background: var(--danger-bg); color: var(--danger); }
  .toast-close { flex: none; display: grid; place-items: center; width: 18px; height: 18px; padding: 0; border: 0; border-radius: 5px; background: transparent; color: inherit; }
  .toast-close :global(svg) { width: 12px; height: 12px; }
  @keyframes toast-in { from { opacity: 0; transform: translateY(6px); } }
  /* #409: the verse to read, in the editor's verse type: a quiet read-only
     card with a mark down its leading edge, not something to drag. Its text
     grows and shrinks a little with the panel's width (cqw: the panel is the
     container), then with the panel's own text size. */
  .reading { padding: 8px 12px; border-radius: 8px; background: var(--surface-2); border-inline-start: 3px solid color-mix(in srgb, var(--accent) 40%, var(--border)); }
  .reading-text { margin: 0; font-family: var(--font-target); font-size: clamp(var(--fs-sm), 0.72rem + 1cqw, var(--fs-lg)); line-height: 1.7; color: var(--text); overflow-wrap: anywhere; white-space: normal; }
  .reading-empty { margin: 0; font-size: var(--fs-2xs); color: var(--text-3); }
  /* #72: the columns flow in the source's direction and wrap, the way a
     printed interlinear reads, instead of sitting on one line behind a
     horizontal scrollbar. Each source word still sits directly above its own
     target chips. `flex-shrink: 0` stays on .column -- wrapping is what
     absorbs the overflow, columns must not be squeezed. #485: no height limit
     and no scrolling inside -- the block grows to the verse and the dialog is
     the one scroller; the edge auto-scroll during a drag (trackEdge) keeps a
     column reachable from the target words on a long verse. overflow-x: clip,
     not hidden, so this is not a scroll container. */
  .interlinear {
    display: flex; flex-wrap: wrap; align-content: flex-start; gap: 10px 8px;
    overflow-x: clip;
    /* 13px on top: the merge button of a card in the first row sits 11px
       above it and was cut off by the panel's edge (2026-11-18, Joel). */
    padding: 13px 6px 4px;
  }
  /* The source column is Hebrew for an OT book and Greek for an NT one, so
     the face keys off the `dir` the markup already sets from
     context.sourceDirection rather than being hardcoded to either. */
  .interlinear[dir="rtl"] { font-family: var(--font-hebrew); }
  .interlinear[dir="ltr"] { font-family: var(--font-greek); }
  /* max-width so a column can never be wider than the box and be silently
     clipped by the overflow-x above on a narrow window. */
  /* No minimum of its own (2026-11-17, Joel): a column is as wide as its
     source card, so its empty box is too; target words placed in it widen
     it. */
  .column { display: flex; flex-direction: column; align-items: center; gap: 3px; min-width: 0; max-width: 100%; flex-shrink: 0; }
  /* A merged group's ring is drawn 3px outside its cards, which ate into the
     space to the next column. The column makes that room itself, so the ring
     stands as far from its neighbours as two single cards do from each other
     (2026-11-18, Joel). */
  .column.joined { box-sizing: border-box; padding-inline: 3px; }
  /* #493: the target words of a column sit in a row and wrap, in the target
     language's direction (the cell's `dir`). The cell is the drop target, so
     an empty one shows a dashed box to drop on. */
  .target-cell {
    display: flex; flex-direction: row; flex-wrap: wrap; align-items: center; justify-content: center; align-content: flex-start;
    gap: 4px; width: 100%; box-sizing: border-box;
    min-height: 32px; padding: 3px; border-radius: 6px; border: 1px dashed transparent;
  }
  .target-cell:has(.placeholder) { border-color: var(--border); }
  .target-cell.drop-hover { background: var(--accent-bg); border-color: var(--accent); outline: 1px dashed var(--accent); }
  .target-cell .placeholder { color: var(--text-3); font-size: var(--fs-sm); line-height: 1; }
  /* #148: the counts, as chips beside the heading they are about. */
  .chip { flex: none; border-radius: 999px; padding: 1px 8px; font-size: var(--fs-3xs); font-weight: 700; white-space: nowrap; }
  .chip.remaining { color: var(--warning); background: var(--warning-bg); }
  .chip.linked { color: var(--accent); background: var(--accent-bg); cursor: help; }
  .token { display: inline-flex; flex-direction: column; align-items: center; gap: 2px; min-width: 44px; }
  .token small { font-size: var(--fs-3xs); color: var(--text-3); max-width: 130px; overflow: hidden; text-overflow: ellipsis; }
  /* The gloss replaced the lemma here, so it must undo what the lemma needed:
     `.interlinear` sets the Greek/Hebrew face and, for an OT book, dir=rtl --
     both wrong for an English definition. Clamped to two lines so a long
     definition cannot stretch the interlinear row taller than the words in it;
     the unabridged text stays in the tooltip and the lexicon popup. */
  .gloss {
    font-family: var(--font-ui); direction: ltr; text-align: center;
    white-space: normal; line-height: 1.25; max-width: 120px;
    display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; line-clamp: 2;
  }
  .occ { margin-left: 3px; font-size: 0.8em; font-weight: 400; color: var(--text-3); }
  /* Source words are tinted cards again (2026-11-16, Joel), in the term
     colour so they are not mistaken for target words, which are the accent. */
  .column .token.source { background: var(--term-bg); border-color: color-mix(in srgb, var(--term) 22%, var(--border)); cursor: pointer; }
  .column .token.source:hover:not(:disabled) { border-color: var(--term); background: color-mix(in srgb, var(--term-bg) 55%, var(--surface)); }
  /* On the target token itself, not on .aligned-card .word: this one rule
     covers the aligned cards inside the interlinear -- where it also has to
     undo the source face inherited from .interlinear -- and the target words
     outside it. */
  .token.target { font-family: var(--font-target); touch-action: none; user-select: none; }
  .token.target.unaligned { background: var(--accent-bg); border-color: color-mix(in srgb, var(--accent) 35%, var(--border)); color: var(--text); }
  .token.picked { outline: 2px solid var(--accent); outline-offset: 1px; }
  .already-aligned {
    background: var(--surface-2); border: 1px solid var(--border); color: var(--text-3);
    border-radius: 6px; cursor: default;
  }
  .aligned-card {
    position: relative; flex-direction: row; align-items: center; gap: 3px; min-width: 0;
    border: 1px solid color-mix(in srgb, var(--accent) 35%, var(--border)); border-radius: 6px;
    background: var(--accent-bg); color: var(--text); cursor: default; font: inherit;
  }
  .aligned-card .word { font-size: var(--fs-sm); }
  /* #285: the word of an aligned card is a pick-up button, drawn as the plain
     word; the card shows the pick, like a bank word does. */
  .aligned-card .pick { border: 0; background: none; padding: 0; margin: 0; font: inherit; color: inherit; cursor: pointer; touch-action: none; user-select: none; }
  .aligned-card.picked { outline: 2px solid var(--accent); outline-offset: 1px; }
  /* #410: where a dragged word will land inside the column -- a bar on the
     side of the card where the word will go (#493: the row reads in the
     cell's direction, so the sides swap for right-to-left). */
  .aligned-card.insert-before { box-shadow: -4px 0 0 0 var(--accent); }
  .aligned-card.insert-after { box-shadow: 4px 0 0 0 var(--accent); }
  .target-cell[dir="rtl"] .aligned-card.insert-before { box-shadow: 4px 0 0 0 var(--accent); }
  .target-cell[dir="rtl"] .aligned-card.insert-after { box-shadow: -4px 0 0 0 var(--accent); }
  /* A card's controls (2026-11-16): one small toolbar on its top edge, at
     the end of the word, shown while the card is pointed at or focused, like
     a tab's close. It overlaps the card, so the pointer never leaves the
     card on the way to it, and it stays inside the card's own width, so a
     neighbour's never gets in the way. Earlier and later come in reading
     order (the row follows the cell's direction). */
  .card-tools { position: absolute; z-index: 2; top: -11px; inset-inline-end: -5px; display: none; align-items: center; gap: 1px; padding: 1px;
    border: 1px solid var(--border-strong); border-radius: 999px; background: var(--surface); box-shadow: 0 2px 6px rgba(0,0,0,.16); }
  .token:hover > .card-tools, .token:focus-within > .card-tools { display: inline-flex; }
  .card-tools .card-btn { display: grid; place-items: center; width: 16px; height: 16px; padding: 0; border: 0; border-radius: 50%; background: transparent; color: var(--text-2); opacity: 1; cursor: pointer; }
  .card-tools .card-btn :global(svg) { width: 9px; height: 9px; stroke-width: 3; }
  .card-tools .card-btn:disabled { opacity: .3; cursor: default; }
  .card-tools .card-btn.unalign-x:hover:not(:disabled), .card-tools .card-btn.unalign-x:focus-visible { color: var(--danger); background: var(--danger-bg); }
  .card-tools .card-btn.step:hover:not(:disabled), .card-tools .card-btn.step:focus-visible { color: var(--accent); background: var(--accent-bg); }
  .target-cell[dir="rtl"] .card-btn.step :global(svg) { transform: scaleX(-1); }
  .chip.picked-count { color: var(--accent); background: var(--accent-bg); font-weight: 600; }
  /* #207: a joined column shows every source word of its group side by side;
     the arrow buttons join a column with the one before it or split the last
     word out again. */
  .source-words { display: flex; align-items: stretch; justify-content: center; gap: 3px; width: 100%; }
  /* Each word fills its own card, in a merged group too, so no bare strip
     shows between a short word and the seam (2026-11-18, Joel). */
  .source-words .source-card > .token.source { flex: 1 1 auto; }
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
  /* The target words fill their panel: the whole body takes a drop, starts
     a selection box and clears the selection on a click. No height limit and
     no scrolling inside (#485). */
  .bank-tokens { flex: 1; display: flex; flex-wrap: wrap; gap: 6px; min-height: 44px; align-content: flex-start; border-radius: 6px; padding: 12px 6px 6px; }
  .bank-tokens.drop-hover { background: var(--accent-bg); outline: 2px dashed var(--accent); }
  /* #410: while a selection box is drawn the bank is not text to select. */
  .bank-tokens { touch-action: none; }
  .bank-tokens.marquee-active { user-select: none; cursor: crosshair; }
  .marquee {
    position: fixed; z-index: var(--z-popover); pointer-events: none;
    border: 1px solid var(--accent); background: color-mix(in srgb, var(--accent) 14%, transparent); border-radius: 3px;
  }
  .drag-ghost {
    position: fixed; z-index: var(--z-popover); transform: translate(-50%, -130%); pointer-events: none;
    background: var(--accent); color: white; font-family: var(--font-target); font-size: var(--fs-sm); font-weight: 700;
    border-radius: 7px; padding: 6px 10px; box-shadow: 0 8px 20px rgba(0,0,0,.28);
  }
  .empty { color: var(--text-3); font-size: var(--fs-xs); margin: 6px; }
  /* Reset and the backups: closed until asked for. */
  /* The bar's "Reset and backups" menu, under its button. */
  .menu { position: fixed; z-index: var(--z-dropdown); box-sizing: border-box; min-width: 230px; max-width: min(340px, calc(100vw - 12px)); overflow-y: auto; padding: 4px;
    border: 1px solid var(--border-strong); border-radius: 10px; background: var(--surface); color: var(--text); font-size: var(--fs-2xs); box-shadow: 0 12px 32px rgba(0,0,0,.16); }
  .menu[hidden] { display: none; }
  .menu-label { margin-top: 4px; padding: 7px 8px 3px; border-top: 1px solid var(--border); color: var(--text-3); font-size: var(--fs-3xs); font-weight: 700; }
  .menu-item { display: block; width: 100%; padding: 6px 8px; border: 0; border-radius: 6px; background: none; color: var(--text); text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .menu-item:hover:not(:disabled) { background: var(--bg); }
  .menu-empty { padding: 4px 8px 6px; color: var(--text-3); }
  .tool.alert { color: var(--danger); }
  /* A narrow pane (a split beside the verses): the chapter tally and the
     words "Cross-verse alignment" give way first. */
  @container (max-width: 520px) {
    header .status, header .completed { display: none; }
    .summary { padding-left: 10px; padding-right: 10px; }
    .source-warning, .error, .alignment-flag { margin-left: 10px; margin-right: 10px; }
  }
  /* In the Alignment tab (2026-11-15): the pane is the frame, so no backdrop,
     shadow or rounding. Last in the sheet, after the rules it changes. */
  .embedded.overlay { position: absolute; inset: 0; z-index: auto; display: block; padding: 0; background: var(--surface); }
  .embedded > .modal { width: 100%; height: 100%; max-height: none; box-sizing: border-box; border-radius: 0; box-shadow: none; }
  /* A column: the header, any flag rows, then the panels take what is left
     (WordPanels is `flex: 1`). Last, with the rules above it changes. */
  .modal { display: flex; flex-direction: column; }
</style>
