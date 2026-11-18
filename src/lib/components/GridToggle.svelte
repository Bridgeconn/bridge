<script lang="ts">
  /** A grid of numbers, each switched on or off (2026-11-16, Joel): the
   *  Cross-verse tab's "which verses of the range are shown". An icon button
   *  opens the same grid as GridPicker (the Verses panel's chapter picker),
   *  but every number that is on is drawn as chosen, and a click switches one
   *  on or off without closing the grid. It replaced a row of chips under
   *  the bar. Arrow keys move, Enter or Space switches, Escape closes. The
   *  grid is moved to <body> while open: its panel scrolls and may be drawn
   *  at another text size. */
  import { onDestroy, tick } from "svelte";
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";

  export let options: readonly string[];
  export let selected: readonly string[];
  /** What the control is, for its accessible name: "Verses shown". */
  export let label: string;
  export let item = "verse";
  export let disabled = false;
  export let onToggle: (value: string) => void = () => {};

  const MAX_COLUMNS = 8;
  let columns = MAX_COLUMNS;
  let open = false, place = "", active = 0;
  let trigger: HTMLButtonElement, grid: HTMLElement | undefined;
  $: partial = selected.length < options.length;

  async function show(): Promise<void> {
    if (!options.length || disabled) return;
    const rect = trigger.getBoundingClientRect();
    const room = Math.max(0, window.innerWidth - 12);
    columns = Math.max(2, Math.min(MAX_COLUMNS, options.length, Math.floor((room - 26 + 4) / 38)));
    const width = columns * 38 - 4 + 26;
    const left = Math.max(6, Math.min(rect.right - width, window.innerWidth - 6 - width));
    place = `left:${left}px;top:${rect.bottom + 4}px;width:${width}px;max-height:${Math.max(140, window.innerHeight - rect.bottom - 16)}px`;
    active = Math.max(0, options.findIndex((option) => selected.includes(option)));
    open = true;
    await focusActive();
  }
  function hide(refocus: boolean): void {
    if (!open) return;
    open = false;
    if (refocus) trigger?.focus();
  }
  async function focusActive(): Promise<void> {
    await tick();
    const cell = grid?.querySelector<HTMLElement>(`[data-index="${active}"]`);
    cell?.focus();
    cell?.scrollIntoView?.({ block: "nearest" });
  }
  function onGridKey(event: KeyboardEvent): void {
    const last = options.length - 1;
    const to = event.key === "ArrowRight" ? Math.min(last, active + 1) : event.key === "ArrowLeft" ? Math.max(0, active - 1)
      : event.key === "ArrowDown" ? Math.min(last, active + columns) : event.key === "ArrowUp" ? Math.max(0, active - columns)
      : event.key === "Home" ? 0 : event.key === "End" ? last : -1;
    if (to >= 0) { event.preventDefault(); active = to; void focusActive(); }
    else if (event.key === "Tab") hide(false);
  }
  function outside(event: Event): void {
    const target = event.target as Node;
    if (open && !grid?.contains(target) && !trigger?.contains(target)) hide(false);
  }
  function key(event: KeyboardEvent): void {
    if (open && event.key === "Escape") { event.preventDefault(); event.stopPropagation(); hide(true); }
  }
  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy() { node.remove(); } };
  }
  const onResize = () => hide(false);
  document.addEventListener("pointerdown", outside, true);
  document.addEventListener("keydown", key, true);
  window.addEventListener("resize", onResize);
  onDestroy(() => {
    document.removeEventListener("pointerdown", outside, true);
    document.removeEventListener("keydown", key, true);
    window.removeEventListener("resize", onResize);
  });
</script>

<button type="button" class="trigger" class:open class:partial bind:this={trigger} {disabled} aria-label={label} aria-haspopup="true" aria-expanded={open}
  use:tooltip={open ? "" : `${label}: ${selected.length} of ${options.length}. Choose which ${item}s of the range to show`}
  on:click={() => (open ? hide(false) : void show())}><UiIcon name="filter" /></button>
{#if open}
  <!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
  <div class="panel" style={place} role="group" aria-label={label} tabindex="-1" bind:this={grid} use:portal on:keydown={onGridKey}>
    {#each options as option, index (option)}
      <button type="button" class="cell" class:current={selected.includes(option)} aria-pressed={selected.includes(option)}
        aria-label={`${item[0].toUpperCase()}${item.slice(1)} ${option}`} data-index={index} tabindex={index === active ? 0 : -1}
        on:focus={() => (active = index)} on:click={() => onToggle(option)}>{option}</button>
    {/each}
  </div>
{/if}

<style>
  /* A panel title row's icon button; the accent colour while some are hidden. */
  .trigger { flex: none; display: grid; place-items: center; width: 24px; height: 24px; padding: 0; border: 0; border-radius: 6px; background: transparent; color: var(--text-2); cursor: pointer; }
  .trigger :global(svg) { width: 14px; height: 14px; }
  .trigger:hover:not(:disabled), .trigger:focus-visible, .trigger.open { background: var(--bg); color: var(--text); }
  .trigger.partial, .trigger.partial:hover:not(:disabled) { color: var(--accent); }
  .trigger:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .trigger:disabled { opacity: .5; cursor: not-allowed; }
  /* The chapter picker's grid and cells (EditorHeader.svelte, GridPicker.svelte), value for value. */
  .panel { position: fixed; z-index: var(--z-dropdown); box-sizing: border-box; display: grid; grid-template-columns: repeat(auto-fill, 34px); gap: 4px; align-content: start; justify-content: center;
    padding: 8px 4px 8px 8px; overflow-x: hidden; overflow-y: auto; scrollbar-gutter: stable; border: 1px solid var(--border-strong); border-radius: 10px; background: var(--surface); box-shadow: 0 12px 32px rgba(0,0,0,.16); }
  .cell { position: relative; display: grid; place-items: center; width: 34px; height: 30px; padding: 0; border: 0; border-radius: 6px; background: transparent;
    color: var(--text-3); font: inherit; font-size: var(--fs-2xs); font-weight: 600; cursor: pointer; }
  .cell:hover, .cell:focus-visible { background: var(--accent-bg); color: var(--accent); outline: none; }
  .cell.current { background: var(--accent); color: #fff; }
  .cell.current:hover, .cell.current:focus-visible { background: color-mix(in srgb, var(--accent) 85%, #000); color: #fff; }
</style>
