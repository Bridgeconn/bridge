<script lang="ts">
  import { onMount } from "svelte";
  import { emitTo } from "@tauri-apps/api/event";
  import { project, currentChapter, selectedVerse, chapterVerseNums, verseTexts, verseDisplay, findingsByVerse,
    nativeChecksByVerse, aiCheckReviewsByVerse, checkStatusByVerse, alignmentStatusByVerse, localUserId, reviewerMode,
    focusedFindingId, selectedVerseSet, checkingProgress, alignmentRevisionByVerse, languageQaFindingsByVerse } from "../stores";
  import { languageQaChannel, nudgeLanguageQa } from "../languageQaInline";
  import { openAlignment } from "../alignmentUi";
  import { paratextReviewQueueOpen } from "../paratextNotes";
  import { startVerseEdit, setPendingAcceptFinding } from "../verseEditor";
  import { revealFinding } from "../findingFocus";
  import { SIDE_PANEL_ORDER, sidePanels, setSidePanel, type SidePanelId } from "../editorPrefs";
  import { panelWindow, panelDesktop, panelLabel, onPanelMessage, type PanelContext } from "../panelWindow";
  export let onNavigate: (book: string, chapter: string, verse: string) => void | Promise<void>;
  export let onRefresh: () => Promise<void>;
  export let onSettings: () => void;
  let started = false, error = "";
  let shown = new Set<SidePanelId>();
  let chain = Promise.resolve();
  $: context = { project: $project, chapter: $currentChapter, verse: $selectedVerse,
    chapters: $chapterVerseNums, texts: $verseTexts, display: $verseDisplay, findings: $findingsByVerse,
    native: $nativeChecksByVerse, ai: $aiCheckReviewsByVerse, checks: $checkStatusByVerse, alignment: $alignmentStatusByVerse,
    languageQa: $languageQaChannel, user: $localUserId, mode: $reviewerMode, panels: $sidePanels,
    focused: $focusedFindingId, selection: $selectedVerseSet, progress: $checkingProgress,
    revisions: $alignmentRevisionByVerse, inline: $languageQaFindingsByVerse } satisfies Omit<PanelContext, "open">;
  $: if (started) schedule(context);
  function schedule(value: typeof context) {
    chain = chain.then(() => value === context ? synchronize(value) : undefined).catch(cause => { error = String(cause); });
  }
  async function synchronize(value: typeof context) {
    for (const id of SIDE_PANEL_ORDER) {
      const open = !!value.project && value.panels[id].open && !!value.panels[id].detached;
      try {
        if (open && !shown.has(id)) { await panelWindow(id, "open"); shown.add(id); }
        if (value !== context) return;
        await emitTo(panelLabel(id), `panel-context-${id}`, { ...value, open });
        if (!open && shown.has(id)) { await panelWindow(id, "hide"); shown.delete(id); }
      } catch (cause) { error = `Could not show ${id} separately: ${String(cause)}`; shown.delete(id); setSidePanel(id, { detached: false }); }
    }
  }
  onMount(() => {
    if (!panelDesktop()) return;
    let disposed = false, stop = () => {};
    void onPanelMessage(message => {
      if (!SIDE_PANEL_ORDER.includes(message.id)) return;
      if (message.kind === "ready") { void synchronize(context).catch(cause => error = String(cause)); return; }
      if (message.path !== $project?.path || !$sidePanels[message.id].detached) return;
      // Closing its own window also ends "separate window": opened again, the
      // panel is a tab (Joel, 2026-11-14).
      if (message.kind === "close") setSidePanel(message.id, { open: false, detached: false });
      else if (message.kind === "dock") setSidePanel(message.id, { detached: false, float: null });
      else if (message.kind === "changed") void onRefresh().catch(cause => error = String(cause));
      else if (message.kind === "settings") onSettings();
      else if (message.kind === "reviewQueue") paratextReviewQueueOpen.set(true);
      else if (message.kind === "focus" && message.findingId) void revealFinding(message.findingId);
      else if (message.kind === "alignment") openAlignment(message.chapter || $currentChapter, message.verse || $selectedVerse || "");
      else if (message.kind === "edit") void (async () => {
        await onNavigate(message.book || $project!.bookId, message.chapter || $currentChapter, message.verse || "");
        if (message.path === $project?.path && startVerseEdit(message.chapter || $currentChapter, message.verse || $selectedVerse || "", message.caret)) {
          if (message.acceptFindingId) setPendingAcceptFinding(message.acceptFindingId);
        }
      })().catch(cause => error = String(cause));
      else if (message.kind === "navigate") void Promise.resolve(onNavigate(message.book || $project!.bookId, message.chapter || $currentChapter, message.verse || "")).catch(cause => error = String(cause));
      nudgeLanguageQa();
    }).then(unlisten => { if (disposed) unlisten(); else { stop = unlisten; started = true; } }).catch(cause => error = String(cause));
    return () => { disposed = true; stop(); };
  });
</script>
{#if error}<p class="panel-error" role="alert">{error}<button type="button" on:click={() => error = ""}>Dismiss</button></p>{/if}
<style>.panel-error { position: fixed; bottom: 40px; left: 12px; z-index: 90; background: var(--surface); color: var(--danger); padding: 12px; border: 1px solid var(--danger); max-width: 500px; }</style>
