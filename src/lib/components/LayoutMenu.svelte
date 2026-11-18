<script lang="ts">
  /** A layout picker (2026-11-16, Joel), after VS Code's "Editor Layout": a
   *  button that opens a small grid of split shapes and, last, "Reset to
   *  default". Used twice:
   *  - the editor's top bar, for the whole work area (EditorLayoutMenu.svelte
   *    passes editorTabs.ts's presets and actions);
   *  - the Word alignment bar, for its three panels (wordPanels.ts).
   *  It imports neither: the separate Alignment window draws the second, and
   *  must not load the editor's tab state, which saves itself.
   *  Each shape is drawn from its own definition, so the picture cannot
   *  disagree with the result. The list is moved to <body> while open, clear
   *  of anything that clips. */
  import { onDestroy } from "svelte";
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";
  import type { LayoutPreset, LayoutShape } from "../layoutShapes";

  export let presets: readonly LayoutPreset[];
  /** The preset in use, if the split is one of them. */
  export let current: string | null = null;
  export let onChoose: (id: string) => void;
  export let onReset: () => void;
  export let hint: string;
  export let resetHint: string;
  /** The button's side in px: 26 in the top bar, 28 in a panel bar. */
  export let size = 26;
  export let disabled = false;
  /** A grey hover, for a bar whose other icons have one (the alignment bar). */
  export let quiet = false;

  let open = false, place = "";
  let button: HTMLButtonElement, panel: HTMLElement | undefined;
  $: marked = current;

  type Box = { x: number; y: number; w: number; h: number };
  /** The shape's places as boxes of a 28 x 20 picture, 1.5 px apart. */
  function boxes(shape: LayoutShape, box: Box = { x: 1, y: 1, w: 26, h: 18 }): Box[] {
    if (typeof shape === "number") return [box];
    const ratio = shape.ratio ?? 0.5, gap = 1.5;
    if (shape.axis === "horizontal") {
      const w = (box.w - gap) * ratio;
      return [...boxes(shape.first, { ...box, w }), ...boxes(shape.second, { ...box, x: box.x + w + gap, w: box.w - gap - w })];
    }
    const h = (box.h - gap) * ratio;
    return [...boxes(shape.first, { ...box, h }), ...boxes(shape.second, { ...box, y: box.y + h + gap, h: box.h - gap - h })];
  }

  function toggle(): void {
    if (open) { open = false; return; }
    const r = button.getBoundingClientRect();
    place = `top:${r.bottom + 4}px;right:${Math.max(6, window.innerWidth - r.right)}px`;
    open = true;
  }
  function choose(id: string): void {
    open = false;
    onChoose(id);
  }
  function reset(): void {
    open = false;
    onReset();
  }
  function outside(event: Event): void {
    const target = event.target as Node;
    if (open && !panel?.contains(target) && !button?.contains(target)) open = false;
  }
  function key(event: KeyboardEvent): void {
    if (open && event.key === "Escape") { event.preventDefault(); event.stopPropagation(); open = false; button?.focus(); }
  }
  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy() { node.remove(); } };
  }
  const close = () => (open = false);
  // Capture: the top bar is a window-drag region, and the shell takes a
  // mousedown there before the page sees it.
  document.addEventListener("pointerdown", outside, true);
  document.addEventListener("keydown", key, true);
  window.addEventListener("resize", close);
  onDestroy(() => {
    document.removeEventListener("pointerdown", outside, true);
    document.removeEventListener("keydown", key, true);
    window.removeEventListener("resize", close);
  });
</script>

<button type="button" class="layout-button" class:open class:quiet bind:this={button} {disabled} aria-label="Layout" aria-haspopup="menu" aria-expanded={open}
  style:width={`${size}px`} style:height={`${size}px`}
  use:tooltip={open ? "" : hint} on:click={toggle}><UiIcon name="layout" /></button>
{#if open}
  <div class="layout-menu" role="menu" aria-label="Layout" style={place} bind:this={panel} use:portal>
    <div class="shapes">
      {#each presets as preset (preset.id)}
        <button type="button" role="menuitemradio" class="shape" class:current={marked === preset.id} aria-checked={marked === preset.id}
          aria-label={preset.label} use:tooltip={preset.label} on:click={() => choose(preset.id)}>
          <svg width="28" height="20" viewBox="0 0 28 20" aria-hidden="true">
            {#each boxes(preset.shape) as box}<rect x={box.x} y={box.y} width={box.w} height={box.h} rx="1.5" />{/each}
          </svg>
        </button>
      {/each}
    </div>
    <button type="button" role="menuitem" class="reset" use:tooltip={resetHint}
      on:click={reset}><UiIcon name="resetLayout" />Reset to default</button>
  </div>
{/if}

<style>
  /* The top bar's icon button (TopBar .settings-icon): grey, accent on an accent tint when pointed at. */
  .layout-button { flex: none; display: grid; place-items: center; padding: 0; border: 0; border-radius: 6px;
    background: transparent; color: var(--text-2); cursor: pointer; transition: color .15s, background .15s; }
  .layout-button :global(svg) { width: 16px; height: 16px; }
  .layout-button:hover:not(:disabled), .layout-button:focus-visible, .layout-button.open { background: var(--accent-bg); color: var(--accent); }
  .layout-button.quiet:hover:not(:disabled), .layout-button.quiet:focus-visible, .layout-button.quiet.open { background: var(--bg); color: var(--text); }
  .layout-button.quiet { border-radius: 7px; }
  .layout-button:focus-visible { outline: 2px solid var(--accent); outline-offset: -3px; }
  .layout-button:disabled { opacity: .5; cursor: not-allowed; }
  .layout-menu { position: fixed; z-index: var(--z-dropdown); box-sizing: border-box; padding: 4px;
    border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface); box-shadow: 0 8px 24px rgba(0,0,0,.14); }
  .shapes { display: grid; grid-template-columns: repeat(3, auto); gap: 2px; }
  .shape { display: grid; place-items: center; padding: 4px; border: 1px solid transparent; border-radius: 6px; background: transparent; color: var(--text-3); cursor: pointer; }
  .shape svg { display: block; }
  .shape rect { fill: currentColor; opacity: .45; }
  .shape:hover, .shape:focus-visible { background: var(--accent-bg); color: var(--accent); outline: none; }
  .shape:hover rect, .shape:focus-visible rect, .shape.current rect { opacity: .75; }
  .shape.current { border-color: var(--accent); color: var(--accent); }
  .reset { display: flex; align-items: center; gap: 6px; width: 100%; box-sizing: border-box; margin-top: 4px; padding: 6px 6px 4px; border: 0; border-top: 1px solid var(--border);
    background: transparent; color: var(--text-2); font: inherit; font-size: var(--fs-2xs); font-weight: 600; text-align: left; white-space: nowrap; cursor: pointer; }
  .reset :global(svg) { width: 14px; height: 14px; flex: none; }
  .reset:hover, .reset:focus-visible { color: var(--accent); outline: none; }
  @media (prefers-reduced-motion: reduce) { .layout-button { transition: none; } }
</style>
