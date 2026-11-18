<script lang="ts">
  /** The Verses panel's legend (2026-11-15): an (i) in the header that opens
   *  a short list of what each mark in the verse list means, drawn with the
   *  real mark styles (index.css) so the samples cannot drift from the text.
   *  Drawn `fixed` and kept inside the panel, like the chapter picker. */
  import { onDestroy } from "svelte";
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";

  let open = false;
  let root: HTMLElement;
  let trigger: HTMLButtonElement;
  let place = "";

  const UNDERLINES: ReadonlyArray<{ mark: string; label: string }> = [
    { mark: "m-gr", label: "Greek Room: spelling, names, repetition, consistency" },
    { mark: "m-tn", label: "translationNotes check" },
    { mark: "m-tw", label: "translationWords check" },
    { mark: "m-term", label: "Term" },
    { mark: "m-lqa-typo-high", label: "Likely typo" },
    { mark: "m-lqa-typo", label: "Possible typo" },
    { mark: "m-lqa-learned", label: "A fix you made before" },
    { mark: "m-lqa-sandhi", label: "Sandhi (word joining)" },
    { mark: "m-lqa-spacing", label: "Spacing" },
    { mark: "m-lqa-unicode", label: "Unicode: an invisible or unusual character" },
  ];

  function show(): void {
    const rect = trigger.getBoundingClientRect();
    const panel = (trigger.closest("[data-editor-pane]") ?? document.body).getBoundingClientRect();
    const width = Math.min(340, Math.max(220, panel.width - 12));
    const left = Math.max(panel.left + 6, Math.min(rect.right - width, panel.right - 6 - width));
    place = `left:${left}px;top:${rect.bottom + 4}px;width:${width}px;max-height:${Math.max(160, window.innerHeight - rect.bottom - 16)}px`;
    open = true;
  }
  function close(refocus: boolean): void {
    if (!open) return;
    open = false;
    if (refocus) trigger?.focus();
  }
  function onDocumentPointer(event: Event): void {
    if (open && root && !root.contains(event.target as Node)) close(false);
  }
  function onKey(event: KeyboardEvent): void {
    if (open && event.key === "Escape") { event.preventDefault(); close(true); }
  }
  const onResize = () => close(false);
  document.addEventListener("mousedown", onDocumentPointer);
  document.addEventListener("pointerdown", onDocumentPointer, true);
  document.addEventListener("keydown", onKey);
  window.addEventListener("resize", onResize);
  onDestroy(() => {
    document.removeEventListener("mousedown", onDocumentPointer);
    document.removeEventListener("pointerdown", onDocumentPointer, true);
    document.removeEventListener("keydown", onKey);
    window.removeEventListener("resize", onResize);
  });
</script>

<span class="legend" bind:this={root}>
  <button type="button" class="ui-icon-btn legend-btn" class:open bind:this={trigger} aria-label="What the marks mean"
    aria-haspopup="dialog" aria-expanded={open} use:tooltip={open ? "" : "What the marks in the verses mean"}
    on:click={() => (open ? close(false) : show())}><UiIcon name="info" /></button>
  {#if open}
    <div class="legend-panel" style={place} role="dialog" aria-label="What the marks mean">
      <p class="heading">On each verse</p>
      <ul>
        <li><span class="sample"><span class="num">3<span class="count">12</span></span></span>The small raised number is the verse's open issues: red for a high one, amber medium, grey low. Click it to review them.</li>
        <li><span class="sample"><span class="num ok">3 ✓</span></span>Clear: checked, nothing open, alignment complete.</li>
        <li><span class="sample"><span class="num bad">3 ⚠</span></span>The check failed or was cancelled.</li>
        <li><span class="sample icons"><UiIcon name="rename" /></span>Edit the verse.</li>
        <li><span class="sample icons"><span class="al none"><UiIcon name="align" /></span><span class="al partial"><UiIcon name="align" /></span><span class="al done"><UiIcon name="align" /></span><span class="al bad"><UiIcon name="align" /></span></span>Word alignment: not started, partial, complete, invalid. Click to align.</li>
      </ul>
      <p class="heading">In the text</p>
      <ul>
        {#each UNDERLINES as item}
          <li><span class="sample"><mark class={item.mark}>word</mark></span>{item.label}</li>
        {/each}
        <li><span class="sample"><span class="sup">1</span></span>The finding's number, the same as on its card in Review.</li>
        <li><span class="sample"><span class="flag">⚑</span></span>Flagged for review.</li>
        <li><span class="sample"><span class="small">↺2</span></span>Edited twice: click for the change history.</li>
        <li><span class="sample"><span class="pt">PT 1</span></span>Open Paratext notes on the verse.</li>
      </ul>
      <p class="tip">Right-click a verse or a marked word for more. Double-click a word to select it.</p>
    </div>
  {/if}
</span>

<style>
  .legend { display: inline-flex; }
  .legend-btn { width: 28px; height: 28px; min-height: 28px; border-radius: 7px; }
  .legend-btn :global(svg) { width: 16px; height: 16px; }
  .legend-btn.open { background: var(--accent-bg); color: var(--accent); }
  .legend-panel { position: fixed; z-index: var(--z-dropdown); box-sizing: border-box; padding: 10px 12px; overflow-y: auto;
    border: 1px solid var(--border-strong); border-radius: 10px; background: var(--surface); box-shadow: 0 12px 32px rgba(0,0,0,.16);
    color: var(--text); font-size: var(--fs-2xs); line-height: 1.4; }
  .heading { margin: 0 0 6px; font-size: var(--fs-3xs); font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: var(--text-3); }
  ul + .heading { margin-top: 10px; }
  ul { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 5px; }
  li { display: flex; align-items: baseline; gap: 10px; }
  .sample { flex: none; width: 64px; display: inline-flex; align-items: center; justify-content: flex-start; gap: 3px; font-weight: 600; }
  .sample.icons { align-self: center; }
  .sample :global(svg) { width: 15px; height: 15px; color: var(--text-2); }
  .count { position: relative; top: -.5em; margin-left: 1px; font-size: var(--fs-3xs); color: var(--danger); }
  .num { font-weight: 700; color: var(--text-3); }
  .num.ok { color: var(--success); }
  .num.bad { color: var(--danger); }
  .al { display: grid; place-items: center; width: 18px; height: 18px; border-radius: 5px; }
  .al.partial { background: var(--warning-bg); }
  .al.partial :global(svg) { color: var(--warning); }
  .al.done { background: var(--success-bg); }
  .al.done :global(svg) { color: var(--success); }
  .al.bad { background: var(--danger-bg); }
  .al.bad :global(svg) { color: var(--danger); }
  .sup { font-size: var(--fs-3xs); font-weight: 700; color: var(--accent); vertical-align: super; }
  .flag { color: var(--flag, var(--warning)); }
  .small { color: var(--text-2); }
  .pt { padding: 0 5px; border: 1px solid var(--border); border-radius: 999px; background: var(--surface-2); font-size: var(--fs-3xs); color: var(--text-2); }
  .tip { margin: 10px 0 0; padding-top: 8px; border-top: 1px solid var(--border); color: var(--text-2); }
</style>
