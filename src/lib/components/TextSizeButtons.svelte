<script lang="ts">
  /** A− and A+ for a panel's header: one step smaller or larger of a text
   *  size, off at either end, the size said in the hint. The Verses header's
   *  pair (EditorHeader) and, since #519, a reference tab's, each on its own
   *  size (`scale`). */
  import type { Writable } from "svelte/store";
  import { tooltip } from "../tooltip";
  import { TEXT_SCALES, bumpScale } from "../editorPrefs";

  /** The size these buttons step: a multiple of the normal size. */
  export let scale: Writable<number>;

  $: smallest = $scale === TEXT_SCALES[0];
  $: largest = $scale === TEXT_SCALES[TEXT_SCALES.length - 1];
  $: percent = `${Math.round($scale * 100)}%`;
</script>

<span class="text-size" role="group" aria-label="Text size">
  <button type="button" class="ui-icon-btn hdr-btn size-btn smaller" disabled={smallest} aria-label="Smaller text"
    use:tooltip={smallest ? `Smallest text size (${percent})` : `Smaller text (now ${percent})`}
    on:click={() => bumpScale(scale, -1)}>A<span aria-hidden="true">−</span></button>
  <button type="button" class="ui-icon-btn hdr-btn size-btn larger" disabled={largest} aria-label="Larger text"
    use:tooltip={largest ? `Largest text size (${percent})` : `Larger text (now ${percent})`}
    on:click={() => bumpScale(scale, 1)}>A<span aria-hidden="true">+</span></button>
</span>

<style>
  .text-size { display: inline-flex; align-items: center; gap: 2px; }
  /* The app's icon button (index.css .ui-icon-btn), at the header's size. */
  .hdr-btn { width: 28px; height: 28px; min-height: 28px; border-radius: 7px; }
  .size-btn { display: inline-flex; align-items: baseline; justify-content: center; gap: 1px; font: inherit; font-weight: 700; line-height: 28px; }
  .size-btn.smaller { font-size: var(--fs-3xs); }
  .size-btn.larger { font-size: var(--fs-sm); }
  .size-btn span { font-size: var(--fs-3xs); font-weight: 700; }
</style>
