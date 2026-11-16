<script lang="ts">
  import { onMount } from "svelte";
  import { project, currentChapter, selectedVerse, verseNums, verseTexts, alignmentRevisionByVerse, noteAlignmentChanged, alignmentStatusByVerse, verseKey } from "../stores";
  import { bridge } from "../api/bridgeClient";
  import { alignmentOpen, alignmentKey, alignmentPane, alignmentDetachedMode, closeAlignment, closeCrossVerse, closeWordAlignment, crossVerseOpen, crossVerseAnchor, crossVerseInitialVerses, holdAlignmentBusy, openAlignment, openCrossVerse } from "../alignmentUi";
  import { alignmentBusy, alignmentPinned, alignmentDetached, alignmentDesktop, alignmentWindow, onAlignmentMessage, sendAlignmentContext, type AlignmentWindowContext, type AlignmentMessage } from "../alignmentWindow";
  // 2026-11-15: this draws nothing but an error. It decides which verse the
  // alignment editors are on and keeps the separate window in step; in the main
  // window they are the work area's two alignment tabs (AlignmentTabPane.svelte),
  // which draws what `alignmentPane` holds. The one separate window holds one
  // of the two (`alignmentDetachedMode`); the other stays a tab.
  import { onDestroy } from "svelte";
  let anchor: { chapter: string; verse: string; path: string; verses: string[] } | null = null;
  let error = "", started = false, visible = false, revision = 0;
  let previousPath = $project?.path;
  $: if ($project?.path !== previousPath) { close(); anchor = null; previousPath = $project?.path; }
  $: open = Boolean($project && ($alignmentOpen || $crossVerseOpen));
  $: if (!open && !$alignmentBusy) anchor = null;
  $: if (open && !$alignmentBusy && (!$alignmentPinned || !anchor)) {
    const verse = ($selectedVerse || $crossVerseAnchor) || $alignmentKey.split(":")[1] || "1";
    // A chapter change sets the chapter first and the verse once its verses
    // are read: stay on the old chapter until then, so no editor is opened on
    // a verse the new chapter may not have (2026-11-16).
    const arriving = Boolean(anchor && anchor.chapter !== $currentChapter && !$verseNums.includes(verse));
    if (anchor && $crossVerseOpen && !arriving && (anchor.chapter !== $currentChapter || anchor.verse !== verse)) crossVerseInitialVerses.set([]);
    if (!arriving) anchor ={ chapter: $currentChapter, verse, path: $project!.path, verses: [...$verseNums] };
  }
  $: { $verseTexts; $alignmentRevisionByVerse; revision += 1; }
  // The editor in the separate window, while there is one.
  $: outside = $alignmentDetached ? $alignmentDetachedMode : null;
  $: outsideOpen = Boolean($project && (outside === "cross" ? $crossVerseOpen : outside === "word" ? $alignmentOpen : false));
  $: context = { project: $project, chapter: anchor?.chapter || $currentChapter, verse: anchor?.verse || "1",
    verses: anchor?.verses || [], initialVerses: $crossVerseInitialVerses, mode: $alignmentDetachedMode,
    open: outsideOpen, pinned: $alignmentPinned, revision } satisfies AlignmentWindowContext;
  let sync = Promise.resolve();
  $: if (started) { const value = context; sync = sync.then(async () => {
    if (value !== context) return;
    try {
      if (value.open && !visible) { await alignmentWindow("open"); visible = true; }
      await sendAlignmentContext(value);
      if (!value.open && visible) { await alignmentWindow("hide"); visible = false; }
    } catch (cause) { error = String(cause); alignmentDetached.set(false); visible = false; }
  }); }
  const close = closeAlignment;
  $: wordHere = Boolean($project && $alignmentOpen && outside !== "word");
  $: crossHere = Boolean($project && $crossVerseOpen && outside !== "cross");
  $: alignmentPane.set(anchor && (wordHere || crossHere)
    ? { path: anchor.path, chapter: anchor.chapter, verse: anchor.verse, word: wordHere, cross: crossHere, canDetach: started } : null);
  const windowBusy = {};
  onDestroy(() => alignmentPane.set(null));
  async function receive(message: AlignmentMessage) {
    if (message.kind === "ready") { await sendAlignmentContext(context); return; }
    if (message.path !== $project?.path || !$alignmentDetached) return;
    if (message.kind === "busy") holdAlignmentBusy(windowBusy, message.busy);
    else if (message.kind === "saved") {
      const key = verseKey(message.chapter, message.verse); noteAlignmentChanged(key);
      const updated = await bridge.getAlignment(message.chapter, message.verse);
      if (message.path === $project?.path) alignmentStatusByVerse.update((values) => ({ ...values, [key]: updated.status }));
    } else if (message.kind === "verse") {
      // The separate window's verse arrows (2026-11-16): the editor's selection moves, and the window follows it.
      if (!$alignmentBusy && !$alignmentPinned && message.chapter === $currentChapter && $verseNums.includes(message.verse)) selectedVerse.set(message.verse);
    } else if (message.kind === "pin") alignmentPinned.update((v) => !v);
    else if (message.kind === "dock" && !$alignmentBusy) alignmentDetached.set(false);
    else if (message.kind === "cross" && !$alignmentBusy) openCrossVerse(context.verse);
    else if (message.kind === "word" && !$alignmentBusy) openAlignment(context.chapter, context.verse);
    // Closing its own window closes the editor in it and ends "separate
    // window": opened again, that editor is a tab (Joel, 2026-11-14).
    else if (message.kind === "close" && !$alignmentBusy) {
      if ($alignmentDetachedMode === "cross") closeCrossVerse(); else closeWordAlignment();
      alignmentDetached.set(false);
    }
  }
  onMount(() => {
    if (!alignmentDesktop()) return;
    let stopped = false, stop = () => {};
    void onAlignmentMessage((message) => { void receive(message).catch((cause) => error = String(cause)); }).then((fn) => { if (stopped) fn(); else { stop = fn; started = true; } }).catch((cause) => { error = String(cause); alignmentDetached.set(false); });
    return () => { stopped = true; stop(); };
  });
</script>
{#if error}<p role="alert">Alignment window: {error}</p>{/if}
