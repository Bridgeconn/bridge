<script lang="ts">
  import { onMount } from "svelte";
  import { get } from "svelte/store";
  import { bridge as api } from "../api/bridgeClient";
  import { bindReviewProject } from "../reviewProjectGuard";
  import { project, alignmentStatusByVerse, noteAlignmentChanged, verseKey } from "../stores";
  import { alignmentBusy } from "../alignmentWindow";
  import { askConfirmation } from "../confirmAction";
  import { recheckVerse } from "../verseChecks";
  import type { AlignmentContext } from "../types/finding";
  export let context: AlignmentContext;
  export let busy = false;
  export let onChanged: (contexts: AlignmentContext[]) => void;
  export let onBusy: (value: boolean) => void = () => {};
  /** Told whether a reset was interrupted and waits to be resumed. */
  export let onPending: (value: boolean) => void = () => {};
  /** Drawn as rows of a menu (the Word alignment bar, 2026-11-16), not as
   *  two buttons. "Undo reset" is then listed only while it can be used, and
   *  an error goes to `onError`: the menu closes on a click. */
  export let menu = false;
  export let onError: (message: string) => void = () => {};
  const path = get(project)?.path || "";
  const bridge = bindReviewProject(api, path);
  let working = false, error = "";
  let status: Awaited<ReturnType<typeof api.alignmentResetStatus>> | null = null;
  async function load() { try { status = await bridge.alignmentResetStatus(context.chapter, context.verse); } catch { status = null; } onPending(!!status?.pending); }
  onMount(load);
  $: { context.alignment; void load(); }
  // 2026-11-16 (Joel): nothing to clear, nothing to click. Unknown (the
  // status could not be read) stays clickable; the engine decides.
  $: nothing = !!status && !status.pending && status.groups + status.links + status.decisions === 0;
  async function run(undo = false) {
    if (working || busy || get(alignmentBusy)) return;
    working = true; onBusy(true); alignmentBusy.set(true); error = "";
    try {
      const preview = await bridge.alignmentResetStatus(context.chapter, context.verse);
      const partners = preview.partners;
      const ok = await askConfirmation({ title: `${undo ? "Undo reset" : "Reset verse alignment"} ${context.chapter}:${context.verse}?`,
        body: undo ? "Restore the groups, cross-verse links and no-counterpart decisions saved before reset. Newer alignment work will not be overwritten." :
          `Clear ${preview.groups} alignment groups, ${preview.links} cross-verse groups and ${preview.decisions} no-counterpart decisions for this verse.${partners.length ? ` Linked references: ${partners.join(", ")}.` : ""} Scripture stays unchanged. Undo reset is available until affected alignment or text changes.`,
        confirmLabel: undo ? "Undo reset" : "Reset verse alignment", danger: !undo });
      if (!ok || get(project)?.path !== path) return;
      const result = undo ? await bridge.restoreAlignmentReset(context.chapter, context.verse) : await bridge.resetAlignment(context.chapter, context.verse, preview.alignment, preview.token);
      if (get(project)?.path !== path) return;
      onChanged(result.contexts);
      for (const updated of result.contexts) {
        const key = verseKey(updated.chapter, updated.verse);
        alignmentStatusByVerse.update((values) => ({ ...values, [key]: updated.status }));
        noteAlignmentChanged(key);
        await recheckVerse(updated.chapter, updated.verse, ["alignment"], { expectedPath: path });
      }
    } catch (cause) { error = String(cause); onError(error); }
    finally { await load(); working = false; onBusy(false); alignmentBusy.set(false); }
  }
</script>
{#if menu}
  <button type="button" role="menuitem" class="item danger" disabled={busy || working || nothing} on:click={() => run()}>
    {status?.pending ? "Resume reset" : "Reset verse alignment…"}{#if nothing}<small>Nothing is aligned in this verse</small>{/if}</button>
  {#if status?.canUndo}<button type="button" role="menuitem" class="item" disabled={busy || working} on:click={() => run(true)}>Undo reset</button>{/if}
  {#if status?.pending}<span class="note" role="status">Recovery pending at {status.chapter}:{status.verse}; resume there before other alignment changes.</span>{/if}
{:else}
<div class="reset-controls">
  <button type="button" disabled={busy || working || nothing} title={nothing ? "Nothing is aligned in this verse" : undefined} on:click={() => run()}>{status?.pending ? "Resume reset" : "Reset verse alignment"}</button>
  <button type="button" disabled={busy || working || !status?.canUndo} on:click={() => run(true)}>Undo reset</button>
  {#if status?.pending}<span role="status">Recovery pending at {status.chapter}:{status.verse}; resume there before other alignment changes.</span>{/if}
  {#if error}<span role="alert">{error}</span>{/if}
</div>
{/if}
<style>
  .reset-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; font-size: var(--fs-xs); }
  button { font: inherit; border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); border-radius: 6px; padding: 5px 8px; cursor: pointer; }
  button:disabled { opacity: .5; cursor: default; }
  [role="alert"] { color: var(--danger); }
  .item { display: block; width: 100%; padding: 6px 8px; border: 0; border-radius: 6px; background: none; text-align: left; font-size: inherit; }
  .item:hover:not(:disabled) { background: var(--bg); }
  .item.danger:not(:disabled) { color: var(--danger); }
  .item small { display: block; color: var(--text-3); font-size: var(--fs-3xs); }
  .note { display: block; padding: 4px 8px; color: var(--warning); }
</style>
