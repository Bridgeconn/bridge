<script lang="ts">
  import { onMount } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import { recheckVerse } from "../verseChecks";
  import {
    alignmentStatusByVerse, checkStatusByVerse, noteAlignmentChanged, project, targetLang,
    verseKey,
  } from "../stores";
  import { alignmentStatusLabel } from "../alignmentStatus";
  import { bookDisplayName } from "../utils/reportStats";
  import type { AlignmentContext, AlignmentToken } from "../types/finding";
  import { createPointerDrag } from "../alignmentDrag";
  import { openCrossVerse } from "../alignmentUi";
  import {
    alignedTargetsFor, bottomIdsAfterDrop, groupForSource, groupForTarget, occurrenceLabel as occurrence,
    sourceColumns, topIdsFor, unaccountedTargets, undoTargetId,
  } from "../alignmentGroups";
  import { SourceGlossCache } from "../lexiconGloss";
  import LexiconPopup from "./LexiconPopup.svelte";

  export let chapter: string;
  export let verse: string;
  export let onClose: () => void;

  let context: AlignmentContext | null = null;
  let lexiconToken: AlignmentToken | null = null;
  let loading = true;
  let busy = false;
  let error = "";
  let notice = "";
  let restoreId = "";

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
  const drag = createPointerDrag({
    onDragStart: (tokenId) => { if (!picked.includes(tokenId)) picked = []; },
    onDrop: ({ tokenId, column, bank }) => {
      const ids = picked.includes(tokenId) ? picked : [tokenId];
      picked = [];
      if (column) dropOntoColumn(ids, column);
      else if (bank) returnToBank(ids);
    },
  });
  const dragState = drag.state;

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

  async function load() {
    loading = true;
    error = "";
    try {
      context = await bridge.getAlignment(chapter, verse);
      restoreId = context.history[0]?.id ?? "";
      void glosses.load(context.topTokens).then(() => (glossVersion = glosses.version));
    } catch (value) {
      error = value instanceof Error ? value.message : String(value);
    } finally {
      loading = false;
    }
  }

  // `glossVersion` is read, not used, so Svelte re-invokes these once the
  // lexicon lookups resolve.
  function sourceGloss(token: AlignmentToken, _version: number): string {
    return glosses.glossFor(token).short;
  }

  function sourceTitle(token: AlignmentToken, _version: number): string {
    return glosses.glossFor(token).title;
  }

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

  // #148: the four counts are a partition of the chapter's verses -- one
  // increment per verse in `alignment_status` (bridge_service.py) -- so their
  // total is the chapter's verse count, and saying so is what makes the row
  // readable. "Chapter:" alone read as a count of chapters.
  $: chapterVerseTotal = context
    ? context.chapterStatus.complete + (context.chapterStatus.complete_cross_verse ?? 0) + context.chapterStatus.partial
      + context.chapterStatus.untouched + context.chapterStatus.invalid
    : 0;

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
    if (busy || lexiconToken) return;
    // A pinned popover swallows the first Escape; a second one closes the modal.
    if (issuesPinned) { issuesPinned = false; return; }
    // So does a selection (#285): Escape puts the picked words down first.
    if (picked.length) { picked = []; return; }
    onClose();
  }

  async function refreshChecks(updated: AlignmentContext, message: string) {
    context = updated;
    restoreId = updated.history[0]?.id ?? "";
    const key = verseKey(chapter, verse);
    alignmentStatusByVerse.update((values) => ({ ...values, [key]: updated.status }));
    // Every save, unalign, undo and restore lands here; the Source text panel
    // re-reads the verse on this, not on the status, which most edits keep (#291).
    noteAlignmentChanged(key);
    checkStatusByVerse.update((values) => ({ ...values, [key]: "pending" }));
    try {
      // Only the alignment checks: the verse's other findings are kept, and
      // Greek Room runs on demand (#251, #252).
      await recheckVerse(chapter, verse, ["alignment"]);
      notice = `${message} The alignment checks are current.`;
    } catch (value) {
      checkStatusByVerse.update((values) => ({ ...values, [key]: "failed" }));
      error = `${message} The save succeeded, but rechecking failed: ${value instanceof Error ? value.message : String(value)}`;
    }
  }

  async function mutate(action: () => Promise<AlignmentContext>, message: string) {
    if (busy) return;
    busy = true;
    error = "";
    notice = "";
    try {
      await refreshChecks(await action(), message);
    } catch (value) {
      error = value instanceof Error ? value.message : String(value);
    } finally {
      busy = false;
    }
  }

  // Every drop/click-drop realigns the source column's FULL target set
  // (existing members + the newly placed words); bottomIdsAfterDrop explains
  // why. Several words picked together (#285) are one realign call, so one
  // history row, one undo step and one re-check.
  function dropOntoColumn(targetIds: string[], sourceId: string) {
    if (!context || targetIds.length === 0) return;
    const bottomIds = bottomIdsAfterDrop(context, sourceId, targetIds);
    if (!bottomIds) return; // already in this column
    // Every source word of the column (#207): a drop on a joined column must
    // not split it back into one word's group.
    const topIds = topIdsFor(context, sourceId);
    const moved = bottomIds.length - (groupForSource(context, sourceId)?.bottomIds.length ?? 0);
    void mutate(
      () => bridge.realignWords(chapter, verse, topIds, bottomIds, context!.alignment),
      moved > 1 ? `${moved} words placed together.` : "Alignment saved.",
    );
  }

  // #207: a source word split into several tokens whose translation is one
  // joined target word is one tC group with several topWords. The engine's
  // realign has always accepted that; the surface could not ask for it.
  // "Join" folds a column into the one before it (split source words sit
  // side by side); "Split" takes the last source word out again, which the
  // engine keeps as its own empty group. realign needs at least one target
  // word, so a join of two empty columns and a split of a joined column with
  // no target are disabled rather than refused after the click.
  $: columns = context ? sourceColumns(context) : [];
  function columnBottomIds(ids: string[]): string[] {
    return context ? (alignedTargetsFor(context, ids[0]).map((t) => t.id)) : [];
  }
  function joinWithPrevious(index: number) {
    if (!context || index <= 0) return;
    const previous = columns[index - 1];
    const current = columns[index];
    const bottomIds = [...columnBottomIds(previous.ids), ...columnBottomIds(current.ids)];
    if (bottomIds.length === 0) return;
    void mutate(
      () => bridge.realignWords(chapter, verse, [...previous.ids, ...current.ids], bottomIds, context!.alignment),
      "Source words joined.",
    );
  }
  function splitLast(index: number) {
    if (!context) return;
    const column = columns[index];
    const bottomIds = columnBottomIds(column.ids);
    if (column.ids.length < 2 || bottomIds.length === 0) return;
    void mutate(
      () => bridge.realignWords(chapter, verse, column.ids.slice(0, -1), bottomIds, context!.alignment),
      "Source word split out.",
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
        const run = pickable.slice(Math.min(from, to), Math.max(from, to) + 1);
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
    if (!picked.length || busy) return;
    const ids = picked;
    picked = [];
    returnToBank(ids);
  }

  function startPointerTrack(event: PointerEvent, id: string) {
    if (busy) return;
    drag.start(event, id);
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

  function restore() {
    if (!context || !restoreId) return;
    void mutate(
      () => bridge.restoreAlignment(chapter, verse, restoreId, context!.alignment),
      "Selected alignment backup restored.",
    );
  }
</script>

<svelte:window on:keydown={(event) => event.key === "Escape" && onEscape()} />

<div class="overlay" role="presentation">
  <section class="modal" role="dialog" aria-modal="true" aria-label={`Word alignment ${reference}`}>
    <header>
      <div>
        <div class="eyebrow">WORD ALIGNMENT</div>
        <h2>{reference} — align source and target words</h2>
        <button
          type="button"
          class="cross-verse-link"
          on:click={() => { onClose(); openCrossVerse(verse); }}
          disabled={busy}
          title="See this verse beside its neighbours"
        >Cross-verse alignment ›</button>
      </div>
      <button class="close" on:click={onClose} disabled={busy} aria-label="Close alignment editor">×</button>
    </header>

    {#if loading}
      <div class="loading"><span class="spin" /> Loading alignment…</div>
    {:else if context}
      <div class="summary">
        <span class="status {context.status}">Verse: {alignmentStatusLabel(context.status)}</span>
        <span class="tally">
          Chapter {chapter} — {chapterVerseTotal} verse{chapterVerseTotal === 1 ? "" : "s"}:
          <span title="Every target word is placed, and no source word is left without one.">{context.chapterStatus.complete} complete</span> ·
          {#if context.chapterStatus.complete_cross_verse}<span title="Every remaining word is accounted for by a cross-verse link or a null decision; translationCore itself cannot mark these complete.">{context.chapterStatus.complete_cross_verse} via cross-verse</span> ·{/if}
          <span title="Some target words are placed, but the word bank is not empty or a source word has none.">{context.chapterStatus.partial} partial</span> ·
          <span title="No target word has been placed in this verse yet.">{context.chapterStatus.untouched} untouched</span>
          {#if context.chapterStatus.invalid}· <span class="danger" title="Marked invalid in translationCore.">{context.chapterStatus.invalid} invalid</span>{/if}
        </span>
        {#if context.issues.length > 0}
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
        {/if}
      </div>

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

      {#if notice}<div class="notice">✓ {notice}</div>{/if}
      {#if error}<div class="error">{error}</div>{/if}

      <div class="workspace">
        <section class="source-bank">
          <div class="panel-title">
            <span>Source words</span>
            <small>Click a word for its lexicon entry — its target words sit in the column beneath it</small>
          </div>
          <div class="interlinear" dir={context.sourceDirection}>
          {#each columns as column, index (column.ids.join("+"))}
            {@const src = column.tokens[0]}
            {@const label = column.tokens.map((t) => t.word).join(" ")}
            <div class="column" class:joined={column.ids.length > 1}>
              <div class="source-words">
                {#if index > 0}
                  <button
                    type="button"
                    class="join-x"
                    on:click|stopPropagation={() => joinWithPrevious(index)}
                    disabled={busy || columnBottomIds(columns[index - 1].ids).length + columnBottomIds(column.ids).length === 0}
                    aria-label={`Join ${label} with the previous source word`}
                    title={columnBottomIds(columns[index - 1].ids).length + columnBottomIds(column.ids).length === 0
                      ? "Drop a target word on one of the two columns first, then join"
                      : "Join with the previous source word: one target word for both"}
                  >⟵</button>
                {/if}
                {#each column.tokens as token (token.id)}
                  <button
                    class="token source"
                    on:click={() => (lexiconToken = token)}
                    disabled={busy}
                    title={sourceTitle(token, glossVersion)}
                  >
                    <span>{token.word}{#if token.occurrences > 1}<span class="occ">{occurrence(token)}</span>{/if}</span>
                    {#if sourceGloss(token, glossVersion)}<small class="gloss">{sourceGloss(token, glossVersion)}</small>{/if}
                  </button>
                {/each}
                {#if column.ids.length > 1}
                  <button
                    type="button"
                    class="join-x"
                    on:click|stopPropagation={() => splitLast(index)}
                    disabled={busy || columnBottomIds(column.ids).length === 0}
                    aria-label={`Split ${column.tokens[column.tokens.length - 1].word} out of this column`}
                    title="Split the last source word out of this column"
                  >⟶</button>
                {/if}
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
                {#each alignedTargetsFor(context, src.id) as item (item.id)}
                  <!-- The word itself can be picked up and moved to another
                       column, alone or with others (#285); × still returns it. -->
                  <div class="token target aligned-card" class:picked={picked.includes(item.id)} title={`Aligned to ${label}`}>
                    <button
                      type="button"
                      class="pick"
                      on:pointerdown={(event) => startPointerTrack(event, item.id)}
                      on:click|stopPropagation={(event) => handleWordClick(item.id, event)}
                      disabled={busy}
                      aria-label={`Pick up ${item.word} from ${label}`}
                      aria-pressed={picked.includes(item.id)}
                    ><span class="word">{item.word}{#if item.occurrences > 1}<span class="occ">{occurrence(item)}</span>{/if}</span></button>
                    <button
                      type="button"
                      class="unalign-x"
                      on:click|stopPropagation={() => returnToBank([item.id])}
                      disabled={busy}
                      aria-label={`Unalign ${item.word} from ${label}`}
                      title="Remove from this column"
                    >×</button>
                  </div>
                {:else}
                  <span class="placeholder" aria-hidden="true">·</span>
                {/each}
              </div>
            </div>
          {:else}
            <p class="empty">No source tokens are present in this verse.</p>
          {/each}
          </div>
        </section>

        <section class="word-bank">
          <div class="panel-title">
            <span class="panel-label">
              Target words
              {#if unalignedCount > 0}
                <span class="chip remaining">{unalignedCount} remaining</span>
              {/if}
              {#if linkedCount > 0}
                <span class="chip linked" title={accountedNote}>↔ {linkedCount} linked across verses</span>
              {/if}
              {#if picked.length > 1}
                <span class="chip picked-count" role="status" title={pickedWords.join(" ")}>{picked.length} picked · click a column to place them, Esc to put them down</span>
              {/if}
            </span>
            <small>In verse order — drag an unaligned (blue) word into a column above, or click it then click a column. Ctrl-click adds a word, Shift-click a run, to place several at once</small>
          </div>
          <div
            class="tokens bank-tokens"
            class:drop-hover={$dragState.overBank !== null}
            data-drop-bank="true"
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
                <span class="token target already-aligned accounted" title="Accounted for by a cross-verse link (see Cross-verse alignment)"><span class="word">{item.word}{#if item.occurrences > 1}<span class="occ">{occurrence(item)}</span>{/if}</span><small>↔</small></span>
              {:else if groupForTarget(context, item.id)}
                <span class="token target already-aligned" title={`Already aligned`}><span class="word">{item.word}{#if item.occurrences > 1}<span class="occ">{occurrence(item)}</span>{/if}</span></span>
              {:else}
                <button
                  type="button"
                  class="token target unaligned"
                  class:picked={picked.includes(item.id)}
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
        </section>
      </div>

      <footer>
        <div class="history-controls">
          <button on:click={undo} disabled={busy || !undoId}
            title="Steps back through your changes, one per press">Undo last change</button>
          <select bind:value={restoreId} disabled={busy || context.history.length === 0} aria-label="Alignment backup">
            {#each context.history as item}
              <option value={item.id}>{item.timestamp} · {item.operation}</option>
            {/each}
          </select>
          <button on:click={restore} disabled={busy || !restoreId}>Restore selected</button>
        </div>
        <div class="completion">
          {#if context.completionState === "completed"}<span class="completed">✓ Human-completed</span>{/if}
        </div>
      </footer>
    {:else if error}
      <div class="error">{error}</div>
    {/if}
  </section>
</div>

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

<style>
  .overlay { position: fixed; inset: 0; z-index: var(--z-dialog); background: rgba(15, 20, 26, .58); display: grid; place-items: center; padding: 24px; }
  .modal { width: min(1040px, 100%); max-height: calc(100vh - 48px); overflow: auto; background: var(--surface); border-radius: 16px; box-shadow: 0 24px 80px rgba(0,0,0,.24); padding: 20px; color: var(--text); }
  header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; border-bottom: 1px solid var(--border); padding-bottom: 14px; }
  .eyebrow { color: var(--accent); font-size: var(--fs-2xs); letter-spacing: .12em; font-weight: 800; }
  h2 { margin: 4px 0 0; font-size: var(--fs-2xl); }
  button, select { font: inherit; }
  button { border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); border-radius: 7px; padding: 7px 10px; cursor: pointer; }
  button:hover:not(:disabled) { border-color: var(--accent); }
  button:disabled { opacity: .5; cursor: not-allowed; }
  .close { border: 0; font-size: var(--fs-5xl); padding: 0 5px; color: var(--text-2); }
  .cross-verse-link { border: 0; background: none; padding: 4px 0 0; color: var(--accent); font-size: var(--fs-xs); font-weight: 600; }
  .cross-verse-link:hover:not(:disabled) { text-decoration: underline; }
  .loading { padding: 36px; display: flex; gap: 10px; justify-content: center; color: var(--text-2); }
  .spin { width: 12px; height: 12px; border: 2px solid var(--accent-bg); border-top-color: var(--accent); border-radius: 50%; animation: spin .8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .summary { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; font-size: var(--fs-xs); color: var(--text-2); padding: 12px 0; }
  .status { border-radius: 999px; padding: 3px 8px; background: var(--surface-2); font-weight: 700; }
  .status.complete, .status.complete_cross_verse, .completed { color: var(--success); background: #EAF7EF; }
  .status.partial { color: var(--warning); background: var(--warning-bg); }
  .status.invalid, .danger { color: var(--danger); }
  .tally span { border-bottom: 1px dotted var(--border-strong); cursor: help; }
  .tally span.danger { border-bottom-color: currentColor; }
  /* #148: the structural issues sit behind this button instead of an open block
     above the columns. Anchored, not a centred overlay like LexiconPopup -- it
     belongs to the row it came from. It opens downward near the top of a modal
     that scrolls, so it stays inside and needs no portal. */
  .issues-wrap { position: relative; margin-left: auto; }
  .issues-button { border: 0; background: none; padding: 3px 6px; font-size: var(--fs-xs); font-weight: 700; color: var(--danger); border-radius: 7px; }
  .issues-button:hover:not(:disabled), .issues-button[aria-expanded="true"] { background: var(--danger-bg); border-color: transparent; }
  .issues-panel {
    position: absolute; top: calc(100% + 4px); right: 0; z-index: var(--z-dropdown); width: max(260px, 26vw);
    background: #FFF5F5; color: var(--danger); border: 1px solid var(--danger); border-radius: 9px;
    padding: 10px 12px; font-size: var(--fs-sm); line-height: 1.45; text-align: left;
    box-shadow: 0 10px 28px rgba(0,0,0,.16);
  }
  .issues-panel div + div { margin-top: 6px; }
  .source-warning, .notice, .error, .alignment-flag { border-radius: 9px; padding: 10px 12px; margin-bottom: 12px; font-size: var(--fs-sm); line-height: 1.45; }
  .source-warning { display: flex; flex-direction: column; gap: 3px; background: var(--warning-bg); color: var(--warning); }
  .alignment-flag { background: var(--warning-bg); color: var(--warning); font-weight: 600; }
  .already-aligned.accounted { border-style: dashed; border-color: var(--accent); flex-direction: row; gap: 5px; }
  .already-aligned.accounted small { color: var(--accent); font-weight: 700; }
  .notice { background: #EAF7EF; color: var(--success); }
  .error { background: #FFF0F0; color: var(--danger); }
  .workspace { display: flex; flex-direction: column; gap: 14px; }
  /* #72: the columns flow left-to-right and wrap, the way a printed interlinear
     reads, instead of sitting on one line behind a horizontal scrollbar. Each
     source word still sits directly above its own target chips -- only the
     single continuous reading line is broken, into several. flex-wrap rather
     than the cross-verse page's auto-fill grid (#136): the unit there is a
     side-by-side source+cell pair needing a consistent track, here it is a
     self-sizing stacked column, so natural widths pack a line tighter.
     `flex-shrink: 0` stays on .column -- wrapping is what absorbs the overflow
     now, columns still must not be squeezed. The max-height caps a long verse
     so the word bank and the footer controls stay on screen: the pointer drag
     has no auto-scroll, so a column you cannot see at the same time as the bank
     is unreachable by drag. */
  .interlinear {
    display: flex; flex-wrap: wrap; align-content: flex-start; gap: 16px 10px;
    overflow-x: hidden; overflow-y: auto; max-height: 48vh;
    padding: 12px 6px; border: 1px solid var(--border); border-radius: 10px; min-height: 128px;
  }
  /* The source column is Hebrew for an OT book and Greek for an NT one, so
     the face keys off the `dir` the markup already sets from
     context.sourceDirection rather than being hardcoded to either. */
  .interlinear[dir="rtl"] { font-family: var(--font-hebrew); }
  .interlinear[dir="ltr"] { font-family: var(--font-greek); }
  /* max-width so a column can never be wider than the box and be silently
     clipped by the overflow-x above on a narrow window. */
  .column { display: flex; flex-direction: column; align-items: center; gap: 6px; min-width: 76px; max-width: 100%; flex-shrink: 0; }
  .target-cell {
    display: flex; flex-direction: column; align-items: center; gap: 4px; width: 100%; box-sizing: border-box;
    min-height: 36px; justify-content: flex-end; padding: 4px; border-radius: 8px;
  }
  .target-cell.drop-hover { background: var(--accent-bg); outline: 2px dashed var(--accent); }
  .target-cell .placeholder { color: var(--text-3); font-size: var(--fs-xl); line-height: 1; padding-bottom: 6px; }
  .panel-title { display: flex; justify-content: space-between; gap: 10px; align-items: center; flex-wrap: wrap; font-size: var(--fs-sm); font-weight: 700; margin-bottom: 10px; }
  .panel-title small { color: var(--text-3); font-weight: 400; }
  .panel-label { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
  /* #148: the counts the "Not fully aligned" banner used to spell out across two
     full-width lines, as chips beside the heading they are about. */
  .chip { border-radius: 999px; padding: 2px 9px; font-size: var(--fs-2xs); font-weight: 700; }
  .chip.remaining { color: var(--warning); background: var(--warning-bg); }
  .chip.linked { color: var(--accent); background: var(--accent-bg); cursor: help; }
  .token { display: inline-flex; flex-direction: column; align-items: center; gap: 2px; min-width: 62px; }
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
  .column .token.source { width: 100%; background: #F6F1FF; cursor: pointer; }
  /* On the target token itself, not on .aligned-card .word: this one rule
     covers the aligned cards inside the interlinear -- where it also has to
     undo the source face inherited from .interlinear -- and the word bank
     tokens outside it. */
  .token.target { font-family: var(--font-target); touch-action: none; user-select: none; }
  .token.target.unaligned { background: #EFF7FF; border-color: var(--border-strong); color: var(--text); }
  .token.picked { outline: 2px solid var(--accent); outline-offset: 1px; }
  .already-aligned {
    background: var(--surface-2); border: 1px solid var(--border); color: var(--text-3);
    padding: 7px 10px; border-radius: 7px; cursor: default;
  }
  .aligned-card {
    flex-direction: row; align-items: center; gap: 4px; min-width: 0;
    border: 1px solid var(--border-strong); border-radius: 7px; padding: 5px 6px 5px 10px;
    background: #EFF7FF; color: var(--text); cursor: default; font: inherit;
  }
  .aligned-card .word { font-size: var(--fs-sm); }
  /* #285: the word of an aligned card is a pick-up button, drawn as the plain
     word; the card shows the pick, like a bank word does. */
  .aligned-card .pick { border: 0; background: none; padding: 0; margin: 0; font: inherit; color: inherit; cursor: pointer; touch-action: none; user-select: none; }
  .aligned-card.picked { outline: 2px solid var(--accent); outline-offset: 1px; }
  .chip.picked-count { color: var(--accent); background: var(--accent-bg); font-weight: 600; }
  .unalign-x {
    border: 0; background: none; padding: 0; width: 16px; height: 16px; line-height: 1;
    display: inline-flex; align-items: center; justify-content: center; border-radius: 50%;
    color: var(--text-2); font-size: var(--fs-md); cursor: pointer; flex-shrink: 0;
  }
  .unalign-x:hover:not(:disabled) { color: var(--danger); background: var(--danger-bg); }
  /* #207: a joined column shows every source word of its group side by side;
     the arrow buttons join a column with the one before it or split the last
     word out again. */
  .source-words { display: flex; align-items: stretch; gap: 3px; width: 100%; }
  .column.joined .source-words .token.source { width: auto; flex: 1; }
  .join-x { border: 1px solid var(--border); background: var(--surface); color: var(--text-2); border-radius: 4px; font-size: var(--fs-xs); padding: 0 3px; cursor: pointer; line-height: 1; }
  .join-x:hover:not(:disabled) { color: var(--accent); border-color: var(--accent); }
  .join-x:disabled { opacity: 0.4; cursor: default; }
  .word-bank, .source-bank { border: 1px solid var(--border); border-radius: 10px; padding: 12px; }
  /* The interlinear carries its own border today; inside the titled section it
     would be a second box around the same thing. */
  .source-bank .interlinear { border: 0; border-radius: 0; padding: 0; }
  .bank-tokens { display: flex; flex-wrap: wrap; gap: 7px; min-height: 46px; align-content: flex-start; border-radius: 8px; padding: 4px; }
  .bank-tokens.drop-hover { background: var(--accent-bg); outline: 2px dashed var(--accent); }
  .drag-ghost {
    position: fixed; z-index: var(--z-popover); transform: translate(-50%, -130%); pointer-events: none;
    background: var(--accent); color: white; font-family: var(--font-target); font-size: var(--fs-sm); font-weight: 700;
    border-radius: 7px; padding: 6px 10px; box-shadow: 0 8px 20px rgba(0,0,0,.28);
  }
  .empty { color: var(--text-3); font-size: var(--fs-xs); margin: 6px; }
  footer { display: flex; justify-content: space-between; gap: 12px; align-items: center; flex-wrap: wrap; }
  .history-controls, .completion { display: flex; align-items: center; gap: 7px; }
  select { border: 1px solid var(--border-strong); border-radius: 7px; padding: 7px; max-width: 235px; color: var(--text); background: var(--surface); }
  .completed { font-size: var(--fs-xs); font-weight: 700; padding: 5px 8px; border-radius: 999px; }
  @media (max-width: 780px) {
    .modal { padding: 14px; }
    footer { align-items: stretch; }
    .history-controls, .completion { flex-wrap: wrap; }
  }
</style>
