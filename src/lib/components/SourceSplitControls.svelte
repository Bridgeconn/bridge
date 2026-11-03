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
  let chosen = "", working = false, error = "";
  $: eligible = context.topTokens.filter((t) => context.sourceLayout?.pending?.signature === `${t.word}\u241f${t.occurrence}\u241f${t.occurrences}` || context.groups.some((g) => g.topIds.length > 1 && g.topIds.includes(t.id))
    || context.crossVerseGroups?.some((g) => g.state === "active" && g.sourceTopIds.length > 1 && g.sourceTopIds.includes(t.id)));
  $: if (context.sourceLayout?.pending && !chosen) chosen = eligible[0]?.id || "";
  async function separate(direction: "left" | "right", undo = false) {
    if (undo) chosen = context.topTokens.find((t) => `${t.word}\u241f${t.occurrence}\u241f${t.occurrences}` === context.sourceLayout?.lastSplit?.signature)?.id || "";
    if (!chosen || busy || working) return;
    working = true; onBusy(true); alignmentBusy.set(true); error = "";
    try {
      if (!await askConfirmation({ title: undo ? "Undo source separation?" : "Separate source word?", body: undo ? "Restore the original cross-verse group if its words have not acquired a new home." : "The chosen word becomes unaligned on the selected side. Existing target words stay with the remaining source group. Source Scripture and token identities stay unchanged.", confirmLabel: undo ? "Undo separation" : `Separate ${direction}` })) return;
      direction = (undo ? context.sourceLayout?.lastSplit?.direction : context.sourceLayout?.pending?.direction) || direction;
      const result = await bridge.splitAlignmentSource(context.chapter, context.verse, chosen, direction, context.alignment, undo);
      if (get(project)?.path !== path) return;
      onChanged(result.contexts); chosen = "";
      for (const updated of result.contexts) {
        const key = verseKey(updated.chapter, updated.verse);
        alignmentStatusByVerse.update((values) => ({ ...values, [key]: updated.status })); noteAlignmentChanged(key);
        await recheckVerse(updated.chapter, updated.verse, ["alignment"], { expectedPath: path });
      }
    } catch (cause) { error = String(cause); }
    finally { working = false; onBusy(false); alignmentBusy.set(false); }
  }
</script>
{#if eligible.length || context.sourceLayout?.lastSplit}
  <div class="split-controls">
    <label>Separate source word <select bind:value={chosen} disabled={busy || working}><option value="">Choose a grouped word…</option>{#each eligible as token}<option value={token.id}>{token.word} ({token.occurrence}/{token.occurrences})</option>{/each}</select></label>
    <button type="button" disabled={busy || working || !chosen} on:click={() => separate("left")}>Separate left</button>
    <button type="button" disabled={busy || working || !chosen} on:click={() => separate("right")}>Separate right</button>
    {#if context.sourceLayout?.lastSplit}<button type="button" disabled={busy || working} on:click={() => separate("left", true)}>Undo separation</button>{/if}
    {#if error}<span role="alert">{error}</span>{/if}
  </div>
{/if}
<style>
  .split-controls { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; font-size: var(--fs-xs); padding: 6px 0; }
  button, select { font: inherit; padding: 5px; border: 1px solid var(--border-strong); border-radius: 6px; color: var(--text); background: var(--surface); }
  [role="alert"] { color: var(--danger); }
</style>
