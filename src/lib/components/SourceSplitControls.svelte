<script lang="ts">
  import { get } from "svelte/store";
  import { project, alignmentStatusByVerse, noteAlignmentChanged, verseKey } from "../stores";
  import { bridge as api } from "../api/bridgeClient";
  import { bindReviewProject } from "../reviewProjectGuard";
  import { recheckVerse } from "../verseChecks";
  import { askConfirmation } from "../confirmAction";
  import { alignmentBusy } from "../alignmentWindow";
  import type { AlignmentContext } from "../types/finding";
  export let context: AlignmentContext;
  export let busy = false;
  export let onBusy: (value: boolean) => void = () => {};
  export let onChanged: (values: AlignmentContext[]) => void;
  const path = get(project)?.path || "";
  const bridge = bindReviewProject(api, path);
  let working = false, error = "";
  // 2026-11-18: nothing on the page starts a separation any more (a merged
  // group is split at its seam, which is an ordinary realign). Two things are
  // still finished here, both for a word named by the engine, never chosen:
  // a separation that was interrupted half way (`pending`), which the engine
  // makes every other alignment edit in the book wait for, and the undo of
  // the last one (`lastSplit`).
  $: pending = context.sourceLayout?.pending;
  $: lastSplit = context.sourceLayout?.lastSplit;
  async function finish(undo: boolean) {
    const waiting = undo ? lastSplit : pending;
    const chosen = context.topTokens.find((t) => `${t.word}\u241f${t.occurrence}\u241f${t.occurrences}` === waiting?.signature)?.id || "";
    if (!waiting || !chosen || busy || working) return;
    working = true; onBusy(true); alignmentBusy.set(true); error = "";
    try {
      if (!await askConfirmation(undo
        ? { title: "Undo source separation?", body: "Restore the original cross-verse group if its words have not acquired a new home.", confirmLabel: "Undo separation" }
        : { title: "Resume source separation?", body: "A separation of this source word was interrupted. Finish it so the alignment can be edited again. Source Scripture and token identities stay unchanged.", confirmLabel: "Resume separation" })) return;
      const result = await bridge.splitAlignmentSource(context.chapter, context.verse, chosen, waiting.direction || "left", context.alignment, undo);
      if (get(project)?.path !== path) return;
      onChanged(result.contexts);
      for (const updated of result.contexts) {
        const key = verseKey(updated.chapter, updated.verse);
        alignmentStatusByVerse.update((values) => ({ ...values, [key]: updated.status })); noteAlignmentChanged(key);
        await recheckVerse(updated.chapter, updated.verse, ["alignment"], { expectedPath: path });
      }
    } catch (cause) { error = String(cause); }
    finally { working = false; onBusy(false); alignmentBusy.set(false); }
  }
</script>
<!-- 2026-11-17 (Joel): the "Separate source word" picker and its two buttons
     are gone. This row shows only when there is something to say: an
     interrupted separation to resume, one that can be undone, or an error. -->
{#if pending || lastSplit || error}
  <div class="split-controls">
    {#if pending}<span>A source separation in this verse was interrupted.</span><button type="button" disabled={busy || working} on:click={() => finish(false)}>Resume separation</button>
    {:else if lastSplit}<button type="button" disabled={busy || working} on:click={() => finish(true)}>Undo separation</button>{/if}
    {#if error}<span role="alert">{error}</span>{/if}
  </div>
{/if}
<style>
  .split-controls { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; font-size: var(--fs-xs); padding: 6px 0; }
  button { font: inherit; padding: 5px; border: 1px solid var(--border-strong); border-radius: 6px; color: var(--text); background: var(--surface); }
  [role="alert"] { color: var(--danger); }
</style>
