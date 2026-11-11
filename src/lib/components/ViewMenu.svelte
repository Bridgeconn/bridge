<script lang="ts">
  /** The top bar's View menu (#488): one entry per side panel, each a toggle
   *  with a tick when its panel is showing. The state is the side rail's
   *  (sidePanels, saved per installation), so the two always agree. Language
   *  QA goes through viewMenu.ts, the name #487's Review tab reads. */
  import { onDestroy, tick } from "svelte";
  import { revealSidePanel, sidePanels, toggleSidePanel, type SidePanelId } from "../editorPrefs";
  import { foldedPanels } from "../panelFit";
  import { languageQaShown, toggleLanguageQaShown } from "../viewMenu";

  const ENTRIES: ReadonlyArray<{ id: SidePanelId; label: string; title: string }> = [
    { id: "source", label: "Source", title: "The Hebrew, Aramaic or Greek source beside the text" },
    { id: "reference", label: "Reference", title: "A reference Bible beside the text" },
    { id: "paratext", label: "Paratext", title: "Paratext Project Notes on the selected verse" },
    { id: "languageQa", label: "Language QA", title: "Language QA for the book" },
    { id: "review", label: "Review", title: "Review the selected verse" },
  ];

  let open = false;
  let root: HTMLElement;
  let trigger: HTMLButtonElement;
  let list: HTMLElement;

  // An open panel folded for width (#324) is not showing: no tick, and
  // choosing it brings it back instead of closing it, as on the rail.
  $: folded = (id: SidePanelId): boolean => $sidePanels[id].open && $foldedPanels.has(id);
  $: shown = (id: SidePanelId): boolean =>
    (id === "languageQa" ? $languageQaShown : $sidePanels[id].open) && !folded(id);

  function choose(id: SidePanelId): void {
    if (folded(id)) revealSidePanel(id);
    else if (id === "languageQa") toggleLanguageQaShown();
    else toggleSidePanel(id);
  }

  const items = (): HTMLButtonElement[] => Array.from(list?.querySelectorAll<HTMLButtonElement>("button") ?? []);

  async function show(): Promise<void> {
    open = true;
    await tick();
    items()[0]?.focus();
  }
  function close(refocus: boolean): void {
    if (!open) return;
    open = false;
    if (refocus) trigger?.focus();
  }

  function onMenuKey(event: KeyboardEvent): void {
    const all = items();
    const at = all.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "ArrowDown") { event.preventDefault(); all[(at + 1) % all.length]?.focus(); }
    else if (event.key === "ArrowUp") { event.preventDefault(); all[(at - 1 + all.length) % all.length]?.focus(); }
    else if (event.key === "Home") { event.preventDefault(); all[0]?.focus(); }
    else if (event.key === "End") { event.preventDefault(); all[all.length - 1]?.focus(); }
    else if (event.key === "Tab") close(false);
  }

  function onDocumentPointer(event: MouseEvent): void {
    if (open && root && !root.contains(event.target as Node)) close(false);
  }
  function onKey(event: KeyboardEvent): void {
    if (open && event.key === "Escape") { event.preventDefault(); close(true); }
  }
  document.addEventListener("mousedown", onDocumentPointer);
  document.addEventListener("keydown", onKey);
  onDestroy(() => {
    document.removeEventListener("mousedown", onDocumentPointer);
    document.removeEventListener("keydown", onKey);
  });
</script>

<span class="view-menu" bind:this={root}>
  <button type="button" class="menu-btn" bind:this={trigger} aria-haspopup="menu" aria-expanded={open}
    title="Show or hide the panels beside the text"
    on:click={() => (open ? close(false) : void show())}
    on:keydown={(event) => { if (event.key === "ArrowDown" && !open) { event.preventDefault(); void show(); } }}>View ▾</button>
  {#if open}
    <!-- svelte-ignore a11y-no-static-element-interactions -->
    <div class="panel" role="menu" aria-label="View" tabindex="-1" bind:this={list} on:keydown={onMenuKey}>
      {#each ENTRIES as entry (entry.id)}
        <button type="button" role="menuitemcheckbox" aria-checked={shown(entry.id)}
          title={folded(entry.id) ? `${entry.title} (folded: the window is too narrow; choose to show it)` : entry.title}
          on:click={() => choose(entry.id)}>
          <span class="tick" aria-hidden="true">{shown(entry.id) ? "✓" : ""}</span>{entry.label}
        </button>
      {/each}
    </div>
  {/if}
</span>

<style>
  .view-menu { position: relative; display: inline-flex; }
  .menu-btn { height: var(--control-h); box-sizing: border-box; display: inline-flex; align-items: center; font: inherit; font-size: var(--fs-sm); font-weight: 600; line-height: 1; padding: 0 8px; border-radius: 6px; border: 1px solid transparent; background: transparent; color: var(--text-2); cursor: pointer; white-space: nowrap; }
  .menu-btn:hover, .menu-btn[aria-expanded="true"] { background: var(--surface-2); color: var(--text); border-color: var(--border); }
  .panel { position: absolute; top: calc(100% + 4px); left: 0; z-index: var(--z-dropdown); min-width: 170px; padding: 4px; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface); box-shadow: 0 8px 24px rgba(0,0,0,.14); display: flex; flex-direction: column; }
  .panel button { display: flex; align-items: center; gap: 6px; padding: 6px 10px; border: 0; border-radius: 5px; background: transparent; color: var(--text); font: inherit; font-size: var(--fs-xs); text-align: left; cursor: pointer; white-space: nowrap; }
  .panel button:hover, .panel button:focus-visible { background: var(--surface-2); outline: none; }
  .tick { width: 14px; flex: none; color: var(--accent); font-weight: 700; }
</style>
