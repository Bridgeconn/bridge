<script lang="ts">
  import { onMount } from "svelte";
  import { project, currentChapter, selectedVerse, verseNums, verseTexts, alignmentRevisionByVerse, noteAlignmentChanged, alignmentStatusByVerse, verseKey } from "../stores";
  import { bridge } from "../api/bridgeClient";
  import { alignmentOpen, alignmentKey, crossVerseOpen, crossVerseAnchor, crossVerseInitialVerses, openCrossVerse } from "../alignmentUi";
  import { alignmentBusy, alignmentPinned, alignmentDetached, alignmentDesktop, alignmentWindow, onAlignmentMessage, sendAlignmentContext, type AlignmentWindowContext, type AlignmentMessage } from "../alignmentWindow";
  import AlignmentModal from "./AlignmentModal.svelte";
  import CrossVerseAlignmentModal from "./CrossVerseAlignmentModal.svelte";
  let anchor: { chapter: string; verse: string; path: string; verses: string[] } | null = null;
  let error = "", started = false, visible = false, revision = 0;
  let previousPath = $project?.path;
  $: if ($project?.path !== previousPath) { close(); anchor = null; previousPath = $project?.path; }
  $: open = Boolean($project && ($alignmentOpen || $crossVerseOpen));
  $: if (!open && !$alignmentBusy) anchor = null;
  $: if (open && !$alignmentBusy && (!$alignmentPinned || !anchor)) {
    const verse = ($selectedVerse || $crossVerseAnchor) || $alignmentKey.split(":")[1] || "1";
    if (anchor && $crossVerseOpen && (anchor.chapter !== $currentChapter || anchor.verse !== verse)) crossVerseInitialVerses.set([]);
    anchor = { chapter: $currentChapter, verse, path: $project!.path, verses: [...$verseNums] };
  }
  $: { $verseTexts; $alignmentRevisionByVerse; revision += 1; }
  $: context = { project: $project, chapter: anchor?.chapter || $currentChapter, verse: anchor?.verse || "1",
    verses: anchor?.verses || [], initialVerses: $crossVerseInitialVerses, mode: $crossVerseOpen ? "cross" : "word",
    open: open && $alignmentDetached, pinned: $alignmentPinned, revision } satisfies AlignmentWindowContext;
  let sync = Promise.resolve();
  $: if (started) { const value = context; sync = sync.then(async () => {
    if (value !== context) return;
    try {
      if (value.open && !visible) { await alignmentWindow("open"); visible = true; }
      await sendAlignmentContext(value);
      if (!value.open && visible) { await alignmentWindow("hide"); visible = false; }
    } catch (cause) { error = String(cause); alignmentDetached.set(false); visible = false; }
  }); }
  function close() { alignmentOpen.set(false); crossVerseOpen.set(false); alignmentBusy.set(false); }
  async function receive(message: AlignmentMessage) {
    if (message.kind === "ready") { await sendAlignmentContext(context); return; }
    if (message.path !== $project?.path || !$alignmentDetached) return;
    if (message.kind === "busy") alignmentBusy.set(message.busy);
    else if (message.kind === "saved") {
      const key = verseKey(message.chapter, message.verse); noteAlignmentChanged(key);
      const updated = await bridge.getAlignment(message.chapter, message.verse);
      if (message.path === $project?.path) alignmentStatusByVerse.update((values) => ({ ...values, [key]: updated.status }));
    } else if (message.kind === "pin") alignmentPinned.update((v) => !v);
    else if (message.kind === "dock" && !$alignmentBusy) alignmentDetached.set(false);
    else if (message.kind === "cross" && !$alignmentBusy) openCrossVerse(context.verse);
    else if (message.kind === "close" && !$alignmentBusy) close();
  }
  onMount(() => {
    if (!alignmentDesktop()) return;
    let stopped = false, stop = () => {};
    void onAlignmentMessage((message) => { void receive(message).catch((cause) => error = String(cause)); }).then((fn) => { if (stopped) fn(); else { stop = fn; started = true; } }).catch((cause) => { error = String(cause); alignmentDetached.set(false); });
    return () => { stopped = true; stop(); };
  });
</script>
{#if error}<p role="alert">Alignment window: {error}</p>{/if}
{#if open && anchor && !$alignmentDetached}
  {#key `${anchor.path}:${anchor.chapter}:${anchor.verse}:${context.mode}`}
    {#if context.mode === "cross"}
      <CrossVerseAlignmentModal chapter={anchor.chapter} verse={anchor.verse} initialVerses={$crossVerseInitialVerses} onClose={close} onDetach={started ? () => alignmentDetached.set(true) : null} />
    {:else}
      <AlignmentModal chapter={anchor.chapter} verse={anchor.verse} onClose={close} onDetach={started ? () => alignmentDetached.set(true) : null} />
    {/if}
  {/key}
{/if}
