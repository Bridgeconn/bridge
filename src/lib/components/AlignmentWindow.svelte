<script lang="ts">
  import { onMount } from "svelte";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { project, currentChapter, chapterVerseNums, alignmentRevisionByVerse } from "../stores";
  import { alignmentBusy, alignmentPinned, alignmentWindow, onAlignmentContext, sendAlignmentMessage, type AlignmentWindowContext } from "../alignmentWindow";
  import { crossVerseOpen } from "../alignmentUi";
  import { confirmRequest, answerConfirmation } from "../confirmAction";
  import ConfirmDialog from "./ConfirmDialog.svelte";
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
  function message(kind: "dock" | "close" | "pin" | "cross") { if (context?.project && !$alignmentBusy) void sendAlignmentMessage({ kind, path: context.project.path }); }
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
      await sendAlignmentMessage({ kind: "ready" });
    })().catch((cause) => error = String(cause));
    return () => { disposed = true; stops.forEach((fn) => fn()); answerConfirmation(false); };
  });
</script>
{#if error}<p role="alert">{error}</p>{/if}
{#if context?.open && context.project}
  {#key `${context.project.path}:${context.chapter}:${context.verse}:${context.mode}:${context.revision}`}
    {#if context.mode === "cross"}<CrossVerseAlignmentModal chapter={context.chapter} verse={context.verse} initialVerses={context.initialVerses} onClose={() => message("close")} onDetach={() => message("dock")} standalone onPin={() => message("pin")} />
    {:else}<AlignmentModal chapter={context.chapter} verse={context.verse} onClose={() => message("close")} onDetach={() => message("dock")} standalone onPin={() => message("pin")} />{/if}
  {/key}
{:else}<p>Open alignment from the Scripture editor.</p>{/if}
{#if $confirmRequest}<ConfirmDialog />{/if}
