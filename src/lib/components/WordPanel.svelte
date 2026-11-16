<script lang="ts">
  /** One panel of the Word alignment tab (2026-11-16, Joel): a title row and
   *  a body. The whole title row drags the panel (WordPanels owns the drag);
   *  the controls in it still click. At its right end: the panel's text size
   *  (A− A+, shown while the row is pointed at or focused, so three panels do
   *  not show six buttons), then whatever the page puts in `tools`: counts
   *  and the info hint. The body's content is drawn at the panel's own text
   *  size; the body itself scrolls, with the app's thin scrollbar. */
  import { getContext } from "svelte";
  import { tooltip } from "../tooltip";
  import { WORD_PANEL_SCALES, wordPanelLayout, type PanelLayout, type WordPanelId } from "../wordPanels";

  export let id: WordPanelId;

  const panels = getContext<{ beginMove: (id: WordPanelId, event: PointerEvent) => void; layout: PanelLayout } | undefined>("word-panels");
  const layout = panels?.layout ?? wordPanelLayout;
  const scales = layout.scales;
  $: title = layout.titles[id];
  $: scale = $scales[id];
  $: smallest = scale === WORD_PANEL_SCALES[0];
  $: largest = scale === WORD_PANEL_SCALES[WORD_PANEL_SCALES.length - 1];
  $: percent = `${Math.round(scale * 100)}%`;
</script>

<section class="word-panel" data-word-panel={id} style:grid-area={id} aria-label={title}>
  <!-- svelte-ignore a11y-no-static-element-interactions -->
  <div class="bar" on:pointerdown={(event) => panels?.beginMove(id, event)}>
    <span class="name">{title}</span>
    <span class="tools">
      <span class="size" role="group" aria-label={`${title} text size`}>
        <button type="button" class="size-btn smaller" disabled={smallest} aria-label={`Smaller ${title.toLowerCase()} text`}
          use:tooltip={smallest ? `Smallest text size (${percent})` : `Smaller text (now ${percent})`}
          on:click={() => layout.bumpScale(id, -1)}>A<span aria-hidden="true">−</span></button>
        <button type="button" class="size-btn larger" disabled={largest} aria-label={`Larger ${title.toLowerCase()} text`}
          use:tooltip={largest ? `Largest text size (${percent})` : `Larger text (now ${percent})`}
          on:click={() => layout.bumpScale(id, 1)}>A<span aria-hidden="true">+</span></button>
      </span>
      <slot name="tools" />
    </span>
  </div>
  <!-- The text size is set on the content, not on the scroller: zoom on the
       scroller made its scrollbar thicker too (2026-11-16). -->
  <div class="body" data-panel-body={id} data-scale={scale}><div class="scaled" style:zoom={scale === 1 ? null : scale}><slot /></div></div>
</section>

<style>
  .word-panel { display: flex; flex-direction: column; min-width: 0; min-height: 0; overflow: hidden; box-sizing: border-box; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); container-type: inline-size; }
  /* The whole row drags, with no colour of its own. */
  .bar { flex: none; display: flex; align-items: center; gap: 8px; min-height: 30px; box-sizing: border-box; padding: 2px 6px 2px 10px; cursor: grab; touch-action: none; user-select: none; }
  .name { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--fs-2xs); font-weight: 700; color: var(--text-2); }
  .tools { margin-left: auto; display: flex; align-items: center; justify-content: flex-end; gap: 6px; min-width: 0; }
  .size { display: inline-flex; align-items: center; gap: 1px; opacity: 0; transition: opacity .12s; }
  .bar:hover .size, .bar:focus-within .size { opacity: 1; }
  .size-btn { display: inline-flex; align-items: baseline; justify-content: center; gap: 1px; width: 24px; height: 24px; padding: 0; border: 0; border-radius: 6px; background: transparent;
    color: var(--text-2); font: inherit; font-weight: 700; line-height: 24px; cursor: pointer; }
  .size-btn.smaller { font-size: var(--fs-3xs); }
  .size-btn.larger { font-size: var(--fs-xs); }
  .size-btn span { font-size: var(--fs-3xs); }
  .size-btn:hover:not(:disabled), .size-btn:focus-visible { background: var(--bg); color: var(--text); }
  .size-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .size-btn:disabled { opacity: .4; cursor: not-allowed; }
  /* A panel with more words than room scrolls here; the row above stays. */
  .body { flex: 1; display: flex; flex-direction: column; min-width: 0; min-height: 0; overflow-x: hidden; overflow-y: auto; padding: 0 10px 10px; }
  .scaled { flex: 1; display: flex; flex-direction: column; min-width: 0; }
  @media (prefers-reduced-motion: reduce) { .size { transition: none; } }
</style>
