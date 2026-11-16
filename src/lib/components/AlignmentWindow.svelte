<script lang="ts">
  import { onMount } from "svelte";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { project, currentChapter, chapterVerseNums, alignmentRevisionByVerse } from "../stores";
  import { alignmentBusy, alignmentPinned, alignmentWindow, onAlignmentContext, sendAlignmentMessage, type AlignmentWindowContext } from "../alignmentWindow";
  import { alignmentOpen, crossVerseOpen } from "../alignmentUi";
  import { confirmRequest, answerConfirmation } from "../confirmAction";
  import ConfirmDialog from "./ConfirmDialog.svelte";
  import WindowBar from "./WindowBar.svelte";
  import AlignmentModal from "./AlignmentModal.svelte";
  import CrossVerseAlignmentModal from "./CrossVerseAlignmentModal.svelte";
  let context: AlignmentWindowContext | null = null, pending: AlignmentWindowContext | null = null;
  let error = "";
  let seen: Record<string, number> = {};
  function apply(value: AlignmentWindowContext) {
    if ($alignmentBusy && value.project?.path === context?.project?.path) { pending = value; return; }
    pending = null;
    if (value.project?.path !== context?.project?.path) { seen = {}; alignmentRevisionByVerse.set({}); }
    answerConfirmation(false);
    project.set(value.project); currentChapter.set(value.chapter);
    chapterVerseNums.set({ [value.chapter]: value.verses }); alignmentPinned.set(value.pinned); context = value;
  }
  $: if (!$alignmentBusy && pending) { const value = pending; pending = null; apply(value); }
  $: if (context?.project) void sendAlignmentMessage({ kind: "busy", path: context.project.path, busy: $alignmentBusy });
  function message(kind: "dock" | "close" | "pin" | "cross" | "word") { if (context?.project && !$alignmentBusy) void sendAlignmentMessage({ kind, path: context.project.path }); }
  onMount(() => {
    let disposed = false; const stops: (() => void)[] = [];
    const keep = (fn: () => void) => disposed ? fn() : stops.push(fn);
    void (async () => {
      keep(await onAlignmentContext(apply));
      keep(await getCurrentWindow().onCloseRequested((e) => { e.preventDefault(); message("close"); }));
      keep(alignmentRevisionByVerse.subscribe((values) => {
        if (context?.project) for (const [key, count] of Object.entries(values)) {
          if (count > (seen[key] || 0)) { seen[key] = count; const [chapter, verse] = key.split(":"); void sendAlignmentMessage({ kind: "saved", path: context.project.path, chapter, verse }); }
        }
      }));
      keep(crossVerseOpen.subscribe((value) => { if (value) { message("cross"); crossVerseOpen.set(false); } }));
      // The cross-verse page's Word alignment icon, in this window: the tab opens in the main window.
      keep(alignmentOpen.subscribe((value) => { if (value) { message("word"); alignmentOpen.set(false); } }));
      await sendAlignmentMessage({ kind: "ready" });
    })().catch((cause) => error = String(cause));
    return () => { disposed = true; stops.forEach((fn) => fn()); answerConfirmation(false); };
  });
</script>
<!-- 2026-11-14 (Joel): the app's own title bar, the one Close this window has.
     The editor below it is drawn as it is in the Alignment tab (`embedded`):
     no backdrop, no close or dock button of its own; the pin stays. -->
<main class="alignment-window">
  <WindowBar title={context?.mode === "cross" ? "Cross-verse alignment" : "Word alignment"} onClose={() => message("close")} closeDisabled={$alignmentBusy} />
  {#if error}<p role="alert">{error}</p>{/if}
  <div class="stage">
    {#if context?.open && context.project}
      {#key `${context.project.path}:${context.chapter}:${context.verse}:${context.mode}:${context.revision}`}
        {#if context.mode === "cross"}<CrossVerseAlignmentModal chapter={context.chapter} verse={context.verse} initialVerses={context.initialVerses} onClose={() => message("close")} standalone embedded onPin={() => message("pin")} />
        {:else}<AlignmentModal chapter={context.chapter} verse={context.verse} onClose={() => message("close")} standalone embedded onPin={() => message("pin")}
          onVerse={(verse) => { if (context?.project && !$alignmentBusy) void sendAlignmentMessage({ kind: "verse", path: context.project.path, chapter: context.chapter, verse }); }} />{/if}
      {/key}
    {:else}<p class="waiting">Open alignment from the Scripture editor.</p>{/if}
  </div>
</main>
{#if $confirmRequest}<ConfirmDialog />{/if}
<style>
  .alignment-window { height: 100vh; display: flex; flex-direction: column; overflow: hidden; min-width: 0; background: var(--surface); }
  .stage { position: relative; flex: 1; min-height: 0; min-width: 0; }
  .waiting { padding: 24px; color: var(--text-2); }
</style>
