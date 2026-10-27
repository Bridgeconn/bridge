<script lang="ts">
  // One column of the editor's side panels (Benz, 2026-10-09): its width is
  // the reviewer's, set by dragging its left edge; dragging that edge to the
  // right past the panel's minimum closes it on release (PanelResizeHandle,
  // shared with the floating Language QA box since #389). `keepMounted`
  // hides a closed panel instead of removing it, for panels that do work
  // while unseen (the review panel's live checks, Language QA's F8 walk).
  //
  // Undocked (#389 step 3, Benz 2026-10-23: a box inside the Bridge window,
  // never a second OS window): the same panel draws as a fixed box at its
  // saved place, moved by its grip, resized from its corner, closed by its ✕
  // or Escape, and docked back from its header. The box sits on --z-panel,
  // under every dialog, like the floating Language QA.
  import {
    PANEL_FLOAT_MIN, SIDE_PANEL_LIMITS, clampPanelFloat, clampPanelWidth, setSidePanel, sidePanels,
  } from "../editorPrefs";
  import type { PanelFloat, SidePanelId } from "../editorPrefs";
  import { foldedPanels } from "../panelFit";
  import PanelResizeHandle from "./PanelResizeHandle.svelte";

  export let id: SidePanelId;
  export let label: string;
  export let keepMounted = false;

  const MOVE_STEP = 16;

  let innerWidth = typeof window === "undefined" ? 1366 : window.innerWidth;
  let innerHeight = typeof window === "undefined" ? 768 : window.innerHeight;
  // The width while a drag is under way; saved once, when the drag ends.
  let dragWidth: number | null = null;
  let closing = false;
  // The box's place while it is being moved or resized; saved on release.
  let floatPreview: PanelFloat | null = null;

  $: limits = SIDE_PANEL_LIMITS[id];
  $: open = $sidePanels[id].open;
  // Open but folded to its rail entry because the window is too narrow (#324):
  // hidden like a closed panel, its saved state untouched.
  $: folded = open && $foldedPanels.has(id);
  // A column never takes more than 45% of the window, whatever was saved.
  $: maxWidth = Math.max(limits.min, Math.min(limits.max, Math.floor(innerWidth * 0.45)));
  $: width = Math.min(dragWidth ?? $sidePanels[id].width, maxWidth);
  const clamp = (px: number): number => Math.min(clampPanelWidth(id, px), maxWidth);
  // Undocked: the saved box, kept inside the window whatever size it is now.
  $: float = $sidePanels[id].float ?? null;
  $: box = float ? clampPanelFloat(floatPreview ?? float, innerWidth, innerHeight) : null;

  function onPreview(next: number | null, closingNow: boolean): void {
    dragWidth = next;
    closing = closingNow;
  }

  /** Drag the box by its grip (#389): the pointer's travel moves it; release saves. */
  function startMove(event: PointerEvent): void {
    if (event.button !== 0 || !float) return;
    event.preventDefault();
    const grip = event.currentTarget as HTMLElement;
    const start = { x: event.clientX, y: event.clientY, box: box ?? float };
    grip.setPointerCapture?.(event.pointerId);
    const move = (next: PointerEvent): void => {
      floatPreview = { ...start.box, x: start.box.x + (next.clientX - start.x), y: start.box.y + (next.clientY - start.y) };
    };
    const end = (): void => {
      grip.removeEventListener("pointermove", move);
      grip.removeEventListener("pointerup", end);
      grip.removeEventListener("pointercancel", end);
      if (floatPreview) setSidePanel(id, { float: clampPanelFloat(floatPreview, innerWidth, innerHeight) });
      floatPreview = null;
    };
    grip.addEventListener("pointermove", move);
    grip.addEventListener("pointerup", end);
    grip.addEventListener("pointercancel", end);
  }

  /** Resize the box from its bottom-right corner; release saves. */
  function startCornerResize(event: PointerEvent): void {
    if (event.button !== 0 || !float) return;
    event.preventDefault();
    event.stopPropagation();
    const corner = event.currentTarget as HTMLElement;
    const start = { x: event.clientX, y: event.clientY, box: box ?? float };
    corner.setPointerCapture?.(event.pointerId);
    const move = (next: PointerEvent): void => {
      floatPreview = {
        ...start.box,
        width: Math.max(PANEL_FLOAT_MIN.width, start.box.width + (next.clientX - start.x)),
        height: Math.max(PANEL_FLOAT_MIN.height, start.box.height + (next.clientY - start.y)),
      };
    };
    const end = (): void => {
      corner.removeEventListener("pointermove", move);
      corner.removeEventListener("pointerup", end);
      corner.removeEventListener("pointercancel", end);
      if (floatPreview) setSidePanel(id, { float: clampPanelFloat(floatPreview, innerWidth, innerHeight) });
      floatPreview = null;
    };
    corner.addEventListener("pointermove", move);
    corner.addEventListener("pointerup", end);
    corner.addEventListener("pointercancel", end);
  }

  /** The grip's keyboard: arrows move the box a step, Shift three; Escape closes. */
  function moveByKey(event: KeyboardEvent): void {
    if (!box) return;
    const step = event.shiftKey ? MOVE_STEP * 3 : MOVE_STEP;
    const delta = event.key === "ArrowLeft" ? { x: -step, y: 0 } : event.key === "ArrowRight" ? { x: step, y: 0 }
      : event.key === "ArrowUp" ? { x: 0, y: -step } : event.key === "ArrowDown" ? { x: 0, y: step } : null;
    if (!delta) return;
    event.preventDefault();
    setSidePanel(id, { float: clampPanelFloat({ ...box, x: box.x + delta.x, y: box.y + delta.y }, innerWidth, innerHeight) });
  }

  /** The corner's keyboard: arrows resize the box a step. */
  function resizeByKey(event: KeyboardEvent): void {
    if (!box) return;
    const step = event.shiftKey ? MOVE_STEP * 3 : MOVE_STEP;
    const delta = event.key === "ArrowLeft" ? { w: -step, h: 0 } : event.key === "ArrowRight" ? { w: step, h: 0 }
      : event.key === "ArrowUp" ? { w: 0, h: -step } : event.key === "ArrowDown" ? { w: 0, h: step } : null;
    if (!delta) return;
    event.preventDefault();
    setSidePanel(id, { float: clampPanelFloat({
      ...box, width: Math.max(PANEL_FLOAT_MIN.width, box.width + delta.w), height: Math.max(PANEL_FLOAT_MIN.height, box.height + delta.h),
    }, innerWidth, innerHeight) });
  }

  /** Escape anywhere in a floating box closes it, as its ✕ does. */
  function onBoxKeydown(event: KeyboardEvent): void {
    if (event.key !== "Escape" || !float) return;
    event.preventDefault();
    event.stopPropagation();
    setSidePanel(id, { open: false });
  }
</script>

<svelte:window bind:innerWidth bind:innerHeight />

{#if open || keepMounted}
  {#if box}
    <!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
    <section class="side-panel floating" id={`side-panel-${id}`} aria-label={label} hidden={!open}
      class:moving={floatPreview !== null}
      style:left="{box.x}px" style:top="{box.y}px" style:width="{box.width}px" style:height="{box.height}px"
      on:keydown={onBoxKeydown}>
      <button type="button" class="float-grip" title="Drag to move; arrow keys move it; Escape closes"
        aria-label={`Move the ${label} panel`} on:pointerdown={startMove} on:keydown={moveByKey}>⋮⋮ {label}</button>
      <div class="float-body"><slot /></div>
      <!-- svelte-ignore a11y-no-noninteractive-tabindex a11y-no-noninteractive-element-interactions -->
      <div class="float-corner" role="separator" aria-orientation="horizontal" tabindex="0"
        aria-label={`Resize the ${label} panel; drag the corner or use the arrow keys`}
        title="Drag to resize" on:pointerdown={startCornerResize} on:keydown={resizeByKey} />
    </section>
  {:else}
    <section class="side-panel" id={`side-panel-${id}`} aria-label={label} hidden={!open || folded}
      class:closing style:width="{width}px" style:min-width="{limits.min}px">
      <PanelResizeHandle {label} {width} min={limits.min} max={maxWidth} initial={limits.initial}
        {onPreview} onCommit={(next) => setSidePanel(id, { width: clamp(next) })}
        onClose={() => setSidePanel(id, { open: false })} />
      <slot />
    </section>
  {/if}
{/if}

<style>
  /* Shrinks before the verse list does, down to its own minimum (#324); below
     that, panelFit.ts folds it to the rail instead of letting the row overflow. */
  .side-panel { position: relative; flex-shrink: 1; display: flex; flex-direction: column; min-height: 0;
    overflow: hidden; border-left: 1px solid var(--border); background: var(--surface); }
  .side-panel[hidden] { display: none; }
  .side-panel.closing { opacity: .55; }
  /* The undocked box (#389): fixed, under every dialog (--z-panel), with a
     grip above the panel's own header bar and a resize corner. */
  .side-panel.floating { position: fixed; z-index: var(--z-panel); flex-shrink: 0; min-width: 260px; min-height: 200px;
    border: 1px solid var(--border-strong); border-radius: 10px; box-shadow: 0 10px 30px rgba(15, 23, 42, .22); }
  .side-panel.floating.moving { opacity: .85; }
  .float-grip { flex-shrink: 0; display: block; width: 100%; padding: 2px 10px; border: 0;
    border-bottom: 1px solid var(--border); border-radius: 10px 10px 0 0; background: var(--surface-2);
    color: var(--text-3); font: inherit; font-size: var(--fs-3xs); font-weight: 700; text-align: left;
    cursor: move; touch-action: none; }
  .float-grip:hover { color: var(--text); }
  .float-grip:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .float-body { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
  .float-corner { position: absolute; right: 0; bottom: 0; width: 16px; height: 16px; cursor: nwse-resize; touch-action: none;
    background: linear-gradient(135deg, transparent 50%, var(--border-strong) 50%); border-radius: 0 0 10px 0; }
  .float-corner:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
</style>
