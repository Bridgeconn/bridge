<script lang="ts">
  /** A number picker drawn as the Verses panel's chapter picker is
   *  (EditorHeader.svelte): a small button showing the choice, which opens a
   *  grid of every option. Used for the Cross-verse bar's From and To
   *  (2026-11-16, Joel), in place of the browser's own drop-down list.
   *  Arrow keys move in the grid, Home and End jump, Enter or a click
   *  chooses, Escape closes. The grid is moved to <body> while open, clear of
   *  the bar, which clips. */
  import { onDestroy, tick } from "svelte";
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";

  export let value: string;
  export let options: readonly string[];
  /** What the control is, for its accessible name: "From", "To". */
  export let label: string;
  /** What one option is, for the hints: "verse". */
  export let item = "verse";
  export let disabled = false;
  export let onChange: (value: string) => void = () => {};

  const MAX_COLUMNS = 8;
  let columns = MAX_COLUMNS;
  let open = false, place = "", active = 0;
  let trigger: HTMLButtonElement, grid: HTMLElement | undefined;

  async function show(): Promise<void> {
    if (!options.length || disabled) return;
    const rect = trigger.getBoundingClientRect();
    // 34 px cells, 4 px gaps, 8 px padding and a 1 px border each side, and
    // 8 px for the scrollbar: the chapter picker's sizes.
    const room = Math.max(0, window.innerWidth - 12);
    columns = Math.max(2, Math.min(MAX_COLUMNS, options.length, Math.floor((room - 26 + 4) / 38)));
    const width = columns * 38 - 4 + 26;
    const left = Math.max(6, Math.min(rect.left, window.innerWidth - 6 - width));
    place = `left:${left}px;top:${rect.bottom + 4}px;width:${width}px;max-height:${Math.max(140, window.innerHeight - rect.bottom - 16)}px`;
    active = Math.max(0, options.indexOf(value));
    open = true;
    await focusActive();
  }
  function hide(refocus: boolean): void {
    if (!open) return;
    open = false;
    if (refocus) trigger?.focus();
  }
  function choose(next: string): void {
    hide(true);
    if (next !== value) onChange(next);
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

<button type="button" class="trigger" class:open bind:this={trigger} {disabled}
  aria-label={`${label}: ${item} ${value}. Choose a ${item}`} aria-haspopup="listbox" aria-expanded={open}
  use:tooltip={open ? "" : `Choose a ${item}`}
  on:click={() => (open ? hide(false) : void show())}
  on:keydown={(event) => { if (event.key === "ArrowDown" && !open) { event.preventDefault(); void show(); } }}>
  <span class="number">{value || "–"}</span><UiIcon name="chevronDown" />
</button>
{#if open}
  <!-- svelte-ignore a11y-no-static-element-interactions -->
  <div class="panel" style={place} role="listbox" aria-label={`${label}: ${item}s`} tabindex="-1" bind:this={grid} use:portal on:keydown={onGridKey}>
    {#each options as option, index (option)}
      <button type="button" class="cell" class:current={option === value} role="option" aria-selected={option === value}
        data-index={index} tabindex={index === active ? 0 : -1}
        on:focus={() => (active = index)} on:click={() => choose(option)}>{option}</button>
    {/each}
  </div>
{/if}

<style>
  /* The chapter picker's trigger, grid and cells (EditorHeader.svelte), value for value. */
  .trigger { display: inline-flex; align-items: center; gap: 2px; height: 24px; min-width: 44px; box-sizing: border-box; padding: 0 4px 0 8px;
    border: 1px solid var(--border); border-radius: 7px; background: var(--surface); color: var(--text); font: inherit; font-size: var(--fs-2xs); font-weight: 700;
    line-height: 1; cursor: pointer; transition: color .15s, background .15s, border-color .15s; }
  .number { flex: 1; text-align: left; }
  .trigger :global(svg) { width: 14px; height: 14px; flex: none; color: var(--text-3); transition: transform .15s; }
  .trigger:hover:not(:disabled), .trigger.open { border-color: transparent; background: var(--accent-bg); color: var(--accent); }
  .trigger:hover:not(:disabled) :global(svg), .trigger.open :global(svg) { color: var(--accent); }
  .trigger.open :global(svg) { transform: rotate(180deg); }
  .trigger:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
  .trigger:disabled { opacity: .5; cursor: not-allowed; }
  .panel { position: fixed; z-index: var(--z-dropdown); box-sizing: border-box; display: grid; grid-template-columns: repeat(auto-fill, 34px); gap: 4px; align-content: start; justify-content: center;
    padding: 8px 4px 8px 8px; overflow-x: hidden; overflow-y: auto; scrollbar-gutter: stable; border: 1px solid var(--border-strong); border-radius: 10px; background: var(--surface); box-shadow: 0 12px 32px rgba(0,0,0,.16); }
  .cell { position: relative; display: grid; place-items: center; width: 34px; height: 30px; padding: 0; border: 0; border-radius: 6px; background: transparent;
    color: var(--text); font: inherit; font-size: var(--fs-2xs); font-weight: 600; cursor: pointer; }
  .cell:hover, .cell:focus-visible { background: var(--accent-bg); color: var(--accent); outline: none; }
  .cell.current { background: var(--accent); color: #fff; }
  @media (prefers-reduced-motion: reduce) { .trigger, .trigger :global(svg) { transition: none; } }
</style>
