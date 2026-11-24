<script lang="ts">
  /** The left rail's Reference button (#519), and the list it opens.
   *
   *  With no reference open and none added, a click opens the project's
   *  reference tab, as the rail's other panes open (its empty state asks for a
   *  folder). Once a reference is open, or one was added, a click opens a list
   *  instead, as the Alignment button does (AlignmentMenu): the project's
   *  reference Bible first, then each reference a reviewer added, each saying
   *  "open" while its tab or window is open, and "Add new reference" below
   *  them. Choosing a reference shows its tab (opening it if it was closed) or
   *  brings its window forward; it never closes one, the tab's own close does
   *  that. An added reference stays in the list after its tab is closed, until
   *  it is removed here. Four references in all. */
  import { onDestroy, tick } from "svelte";
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";
  import { bridge } from "../api/bridgeClient";
  import { REFERENCE_PANEL_IDS, sidePanels, toggleSidePanel } from "../editorPrefs";
  import { EDITOR_TABS, visibleTabs } from "../editorTabs";
  import {
    addReference, canAddReference, projectReferenceName, referenceEntries, referenceHeading, referenceListNeeded,
    removeReference, showReference, type ReferenceEntry,
  } from "../referenceTabs";
  import { currentChapter, project } from "../stores";

  let open = false;
  let root: HTMLElement;
  let trigger: HTMLButtonElement;
  let list: HTMLElement;

  $: anyOpen = REFERENCE_PANEL_IDS.some((id) => $sidePanels[id].open);
  $: showing = REFERENCE_PANEL_IDS.some((id) => $visibleTabs.has(id));
  // Nothing left to list (the last reference was closed or removed): the list goes.
  $: if (open && !$referenceListNeeded) open = false;

  const items = (): HTMLButtonElement[] =>
    Array.from(list?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? []);

  /** The project's reference Bible's name, for its row: it may be closed, or
   *  changed in Settings since its tab last read it. Never waits on the folder. */
  async function readProjectName(): Promise<void> {
    const path = $project?.path, chapter = $currentChapter;
    if (!path || !chapter) return;
    try {
      const result = await bridge.languageQaReference(path, chapter);
      if ($project?.path === path) projectReferenceName.set(result.configured ? referenceHeading(result.source) : "");
    } catch { /* the row keeps the name it has */ }
  }

  async function show(): Promise<void> {
    open = true;
    void readProjectName();
    await tick();
    items()[0]?.focus();
  }
  function close(refocus: boolean): void {
    if (!open) return;
    open = false;
    if (refocus) trigger?.focus();
  }
  function press(): void {
    if (open) { close(false); return; }
    // Nothing open and nothing added: the tab itself, as the other panes open.
    if (!$referenceListNeeded) { toggleSidePanel("reference"); return; }
    void show();
  }
  function choose(action: () => void): void {
    close(false);
    action();
  }

  const nameOf = (entry: ReferenceEntry): string => entry.name || (entry.added ? "New reference" : "Reference Bible");
  function hintOf(entry: ReferenceEntry): string {
    const what = entry.added ? "Added for reading" : "This project's reference Bible, the one Language QA uses";
    if (entry.detached) return `${what}. Open in its own window: click to bring it forward`;
    if (entry.open) return `${what}. Already open: click to show it`;
    return `${what}. Click to open it`;
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
  // The top bar is a window-drag region: the shell takes a mousedown there
  // before the page sees it, so a click on the bar is caught as a pointerdown.
  document.addEventListener("pointerdown", onDocumentPointer, true);
  document.addEventListener("keydown", onKey);
  onDestroy(() => {
    document.removeEventListener("mousedown", onDocumentPointer);
    document.removeEventListener("pointerdown", onDocumentPointer, true);
    document.removeEventListener("keydown", onKey);
  });
</script>

<span class="reference-menu" bind:this={root}>
  <button type="button" class="rail-btn" class:open={anyOpen} class:active={showing} bind:this={trigger}
    aria-label={EDITOR_TABS.reference.label} aria-pressed={anyOpen}
    aria-haspopup={$referenceListNeeded ? "menu" : undefined} aria-expanded={$referenceListNeeded ? open : undefined}
    use:tooltip={{ text: open ? "" : $referenceListNeeded ? "Reference: the reference Bibles of this project, and Add new reference" : EDITOR_TABS.reference.title, side: "right" }}
    on:click={press}
    on:keydown={(event) => { if (event.key === "ArrowDown" && !open && $referenceListNeeded) { event.preventDefault(); void show(); } }}>
    <UiIcon name={EDITOR_TABS.reference.icon} />
  </button>
  {#if open}
    <!-- svelte-ignore a11y-no-static-element-interactions -->
    <div class="panel" role="menu" aria-label="Reference Bibles" tabindex="-1" bind:this={list} on:keydown={onMenuKey}>
      {#each $referenceEntries as entry (entry.id)}
        <div class="row">
          <button type="button" class="pick" role="menuitem" data-reference={entry.id}
            use:tooltip={{ side: "right", text: hintOf(entry) }}
            on:click={() => choose(() => showReference(entry.id))}>
            <UiIcon name="open" /><span class="entry">{nameOf(entry)}</span>{#if entry.open}<span class="is-open">open</span>{/if}
          </button>
          {#if entry.added}
            <button type="button" class="remove" role="menuitem" aria-label={`Remove ${nameOf(entry)} from this list`}
              use:tooltip={{ side: "right", text: entry.open ? "Remove from this list: its tab closes too. The folder is not touched" : "Remove from this list. The folder is not touched" }}
              on:click={() => { const id = entry.id; if (id !== "reference") removeReference(id); }}><UiIcon name="close" /></button>
          {/if}
        </div>
      {/each}
      <span class="rule" aria-hidden="true" />
      <div class="row">
        <button type="button" class="pick" role="menuitem" disabled={!$canAddReference}
          use:tooltip={{ side: "right", text: $canAddReference ? "Open a new reference tab and choose its folder. For reading: Language QA keeps the project's own"
            : "Four references at most. Remove one from this list first" }}
          on:click={() => { if ($canAddReference) choose(() => { addReference(); }); }}>
          <UiIcon name="plus" /><span class="entry">Add new reference</span>
        </button>
      </div>
    </div>
  {/if}
</span>

<style>
  /* AlignmentMenu's panel, to the right of the rail. */
  .reference-menu { position: relative; display: inline-flex; }
  .panel { position: absolute; top: 0; left: calc(100% + 10px); z-index: var(--z-dropdown); min-width: 220px; max-width: 320px; padding: 4px; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface); box-shadow: 0 8px 24px rgba(0,0,0,.14); display: flex; flex-direction: column; }
  .row { display: flex; align-items: center; gap: 2px; min-width: 0; }
  .pick { flex: 1; min-width: 0; display: flex; align-items: center; gap: 8px; padding: 6px 10px; border: 0; border-radius: 5px; background: transparent; color: var(--text); font: inherit; font-size: var(--fs-xs); text-align: left; cursor: pointer; white-space: nowrap; }
  .pick:hover:not(:disabled), .pick:focus-visible { background: var(--surface-2); outline: none; }
  .pick:disabled { opacity: 0.6; cursor: not-allowed; }
  .pick :global(svg) { width: 15px; height: 15px; flex: none; color: var(--text-3); }
  .entry { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  /* A tab that is open already: said on the entry, quietly. */
  .is-open { flex: none; padding: 0 6px; border-radius: 999px; background: var(--accent-bg); color: var(--accent); font-size: var(--fs-3xs); font-weight: 700; }
  /* The tab strip's close: grey, red on a red tint when pointed at. */
  .remove { flex: none; display: grid; place-items: center; width: 24px; height: 24px; padding: 0; border: 0; border-radius: 6px; background: transparent; color: var(--text-3); cursor: pointer; }
  .remove :global(svg) { width: 13px; height: 13px; }
  .remove:hover, .remove:focus-visible { background: var(--danger-bg); color: var(--danger); outline: none; }
  .rule { height: 1px; margin: 4px 6px; background: var(--border); }
</style>
