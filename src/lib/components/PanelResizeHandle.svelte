<script lang="ts">
  // The left-edge handle every panel closes with (#389 step 1): one
  // implementation for the docked columns (SidePanel) and the floating
  // Language QA box on the other screens. Dragging left widens the panel,
  // right narrows it, and further right than `closePast` below the minimum
  // closes it on release; while past that point the handle turns red and a
  // "Release to close" pill shows (the parent dims itself from onPreview).
  // Keyboard: ←/→ by a step, Shift for three, Home/End for the limits;
  // double-click resets to `initial`.
  export let label: string;
  /** The width shown now (a drag in progress included). */
  export let width: number;
  export let min: number;
  export let max: number;
  export let initial: number;
  /** How far below the minimum a drag must go before release closes the panel. */
  export let closePast = 60;
  /** During a drag: the clamped width to show, and whether release would close.
   *  Called once more with null when the drag ends. */
  export let onPreview: (width: number | null, closing: boolean) => void = () => {};
  /** A width to keep: a key press, a double-click reset, or a drag's end. */
  export let onCommit: (width: number) => void;
  export let onClose: () => void;

  const KEY_STEP = 16;
  let dragging = false;
  let closing = false;

  const clamp = (px: number): number => Math.round(Math.min(max, Math.max(min, px)));

  function startResize(event: PointerEvent): void {
    if (event.button !== 0) return;
    event.preventDefault();
    const handle = event.currentTarget as HTMLElement;
    const startX = event.clientX;
    const startWidth = width;
    let previewed: number | null = null;
    handle.setPointerCapture?.(event.pointerId);
    dragging = true;
    const move = (next: PointerEvent): void => {
      const raw = startWidth + (startX - next.clientX);
      closing = raw < min - closePast;
      previewed = clamp(raw);
      onPreview(previewed, closing);
    };
    const end = (): void => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      handle.removeEventListener("pointercancel", end);
      const close = closing;
      dragging = false;
      closing = false;
      onPreview(null, false);
      if (close) onClose();
      else if (previewed !== null) onCommit(previewed);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
  }

  function resizeByKey(event: KeyboardEvent): void {
    const step = event.shiftKey ? KEY_STEP * 3 : KEY_STEP;
    const next = event.key === "ArrowLeft" ? width + step
      : event.key === "ArrowRight" ? width - step
      : event.key === "Home" ? min
      : event.key === "End" ? max
      : null;
    if (next === null) return;
    event.preventDefault();
    onCommit(clamp(next));
  }
</script>

<!-- svelte-ignore a11y-no-noninteractive-tabindex a11y-no-noninteractive-element-interactions -->
<div class="resize-handle" class:dragging class:closing
  role="separator" aria-orientation="vertical"
  aria-label={`Resize the ${label} panel; drag far to the right to close it`}
  aria-valuemin={min} aria-valuemax={max} aria-valuenow={width}
  tabindex="0" title="Drag to resize; drag far to the right to close. Double-click to reset."
  on:pointerdown={startResize} on:keydown={resizeByKey}
  on:dblclick={() => onCommit(initial)} />
{#if closing}<div class="close-hint" aria-hidden="true">Release to close</div>{/if}

<style>
  .resize-handle { position: absolute; top: 0; bottom: 0; left: -3px; width: 6px; z-index: 5; cursor: col-resize;
    touch-action: none; }
  .resize-handle:hover, .resize-handle:focus-visible, .resize-handle.dragging {
    background: color-mix(in srgb, var(--accent) 45%, transparent); outline: none; }
  .resize-handle.closing { background: var(--danger); }
  .close-hint { position: absolute; top: 8px; left: 50%; transform: translateX(-50%); z-index: 6;
    padding: 3px 8px; border-radius: 6px; background: var(--danger); color: white; font-size: var(--fs-3xs);
    font-weight: 700; pointer-events: none; }
</style>
