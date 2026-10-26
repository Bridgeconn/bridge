<script lang="ts">
  // One column of the editor's side panels (Benz, 2026-10-09): its width is
  // the reviewer's, set by dragging its left edge; dragging that edge to the
  // right past the panel's minimum closes it on release. `keepMounted` hides a
  // closed panel instead of removing it, for panels that do work while unseen
  // (the review panel's live checks, Language QA's F8 walk).
  import { SIDE_PANEL_LIMITS, clampPanelWidth, setSidePanel, sidePanels } from "../editorPrefs";
  import type { SidePanelId } from "../editorPrefs";
  import { foldedPanels } from "../panelFit";

  export let id: SidePanelId;
  export let label: string;
  export let keepMounted = false;

  /** How far below the minimum a drag must go before release closes the panel. */
  const CLOSE_PAST = 60;
  const KEY_STEP = 16;

  let innerWidth = typeof window === "undefined" ? 1366 : window.innerWidth;
  // The width while a drag is under way; saved once, when the drag ends.
  let dragWidth: number | null = null;
  let closing = false;

  $: limits = SIDE_PANEL_LIMITS[id];
  $: open = $sidePanels[id].open;
  // Open but folded to its rail entry because the window is too narrow (#324):
  // hidden like a closed panel, its saved state untouched.
  $: folded = open && $foldedPanels.has(id);
  // A column never takes more than 45% of the window, whatever was saved.
  $: maxWidth = Math.max(limits.min, Math.min(limits.max, Math.floor(innerWidth * 0.45)));
  $: width = Math.min(dragWidth ?? $sidePanels[id].width, maxWidth);
  const clamp = (px: number): number => Math.min(clampPanelWidth(id, px), maxWidth);

  /** The handle is on the left edge: moving it left widens the column, right
   * narrows it, and far enough right closes it. */
  function startResize(event: PointerEvent): void {
    if (event.button !== 0) return;
    event.preventDefault();
    const handle = event.currentTarget as HTMLElement;
    const startX = event.clientX;
    const startWidth = width;
    handle.setPointerCapture?.(event.pointerId);
    const move = (next: PointerEvent): void => {
      const raw = startWidth + (startX - next.clientX);
      closing = raw < limits.min - CLOSE_PAST;
      dragWidth = clamp(raw);
    };
    const end = (): void => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      handle.removeEventListener("pointercancel", end);
      if (closing) setSidePanel(id, { open: false });
      else if (dragWidth !== null) setSidePanel(id, { width: dragWidth });
      dragWidth = null;
      closing = false;
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
  }

  function resizeByKey(event: KeyboardEvent): void {
    const step = event.shiftKey ? KEY_STEP * 3 : KEY_STEP;
    const next = event.key === "ArrowLeft" ? width + step
      : event.key === "ArrowRight" ? width - step
      : event.key === "Home" ? limits.min
      : event.key === "End" ? maxWidth
      : null;
    if (next === null) return;
    event.preventDefault();
    setSidePanel(id, { width: clamp(next) });
  }
</script>

<svelte:window bind:innerWidth />

{#if open || keepMounted}
  <section class="side-panel" id={`side-panel-${id}`} aria-label={label} hidden={!open || folded}
    class:closing style:width="{width}px" style:min-width="{limits.min}px">
    <!-- svelte-ignore a11y-no-noninteractive-tabindex a11y-no-noninteractive-element-interactions -->
    <div class="resize-handle" class:dragging={dragWidth !== null}
      role="separator" aria-orientation="vertical"
      aria-label={`Resize the ${label} panel; drag far to the right to close it`}
      aria-valuemin={limits.min} aria-valuemax={maxWidth} aria-valuenow={width}
      tabindex="0" title="Drag to resize; drag far to the right to close. Double-click to reset."
      on:pointerdown={startResize} on:keydown={resizeByKey}
      on:dblclick={() => setSidePanel(id, { width: limits.initial })} />
    {#if closing}<div class="close-hint" aria-hidden="true">Release to close</div>{/if}
    <slot />
  </section>
{/if}

<style>
  /* Shrinks before the verse list does, down to its own minimum (#324); below
     that, panelFit.ts folds it to the rail instead of letting the row overflow. */
  .side-panel { position: relative; flex-shrink: 1; display: flex; flex-direction: column; min-height: 0;
    overflow: hidden; border-left: 1px solid var(--border); background: var(--surface); }
  .side-panel[hidden] { display: none; }
  .side-panel.closing { opacity: .55; }
  .resize-handle { position: absolute; top: 0; bottom: 0; left: -3px; width: 6px; z-index: 5; cursor: col-resize;
    touch-action: none; }
  .resize-handle:hover, .resize-handle:focus-visible, .resize-handle.dragging {
    background: color-mix(in srgb, var(--accent) 45%, transparent); outline: none; }
  .closing .resize-handle { background: var(--danger); }
  .close-hint { position: absolute; top: 8px; left: 50%; transform: translateX(-50%); z-index: 6;
    padding: 3px 8px; border-radius: 6px; background: var(--danger); color: white; font-size: var(--fs-3xs);
    font-weight: 700; pointer-events: none; }
</style>
