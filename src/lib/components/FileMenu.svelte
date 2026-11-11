<script lang="ts">
  /** The top bar's File menu (2026-11-11), first of the editor's menus: Close
   *  editor (the project page), Close project (the project list), Export
   *  project and Settings (both were buttons at the right of the bar), and
   *  Exit. The caller owns the actions. Choosing an entry closes the menu. */
  import { onDestroy, tick } from "svelte";

  export let onCloseEditor: () => void = () => {};
  export let onCloseProject: () => void = () => {};
  export let onExport: () => void = () => {};
  /** No project is open. */
  export let exportDisabled = false;
  export let onSettings: () => void = () => {};
  export let onExit: () => void = () => {};
  /** A book is being opened: leaving for the project page would start another wait. */
  export let busy = false;

  let open = false;
  let root: HTMLElement;
  let trigger: HTMLButtonElement;
  let list: HTMLElement;

  const items = (): HTMLButtonElement[] =>
    Array.from(list?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? []);

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
  function choose(action: () => void): void {
    close(false);
    action();
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

<span class="file-menu" bind:this={root}>
  <button type="button" class="menu-btn" bind:this={trigger} aria-haspopup="menu" aria-expanded={open}
    title="Close the editor or the project, export, Settings and Exit"
    on:click={() => (open ? close(false) : void show())}
    on:keydown={(event) => { if (event.key === "ArrowDown" && !open) { event.preventDefault(); void show(); } }}>File ▾</button>
  {#if open}
    <!-- svelte-ignore a11y-no-static-element-interactions -->
    <div class="panel" role="menu" aria-label="File" tabindex="-1" bind:this={list} on:keydown={onMenuKey}>
      <button type="button" role="menuitem" disabled={busy} title="Leave the editor for this project's page"
        on:click={() => { if (!busy) choose(onCloseEditor); }}>Close editor</button>
      <button type="button" role="menuitem" title="Close this project and return to the project list"
        on:click={() => choose(onCloseProject)}>Close project</button>
      <hr />
      <button type="button" role="menuitem" disabled={exportDisabled}
        on:click={() => { if (!exportDisabled) choose(onExport); }}>Export project…</button>
      <button type="button" role="menuitem" on:click={() => choose(onSettings)}>Settings…</button>
      <hr />
      <button type="button" role="menuitem" title="Close Bridge" on:click={() => choose(onExit)}>Exit</button>
    </div>
  {/if}
</span>

<style>
  .file-menu { position: relative; display: inline-flex; }
  .menu-btn { height: var(--control-h); box-sizing: border-box; display: inline-flex; align-items: center; font: inherit; font-size: var(--fs-sm); font-weight: 600; line-height: 1; padding: 0 8px; border-radius: 6px; border: 1px solid transparent; background: transparent; color: var(--text-2); cursor: pointer; white-space: nowrap; }
  .menu-btn:hover, .menu-btn[aria-expanded="true"] { background: var(--surface-2); color: var(--text); border-color: var(--border); }
  .panel { position: absolute; top: calc(100% + 4px); left: 0; z-index: var(--z-dropdown); min-width: 180px; padding: 4px; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface); box-shadow: 0 8px 24px rgba(0,0,0,.14); display: flex; flex-direction: column; }
  .panel button { display: flex; align-items: center; padding: 6px 10px; border: 0; border-radius: 5px; background: transparent; color: var(--text); font: inherit; font-size: var(--fs-xs); text-align: left; cursor: pointer; white-space: nowrap; }
  .panel button:hover:not(:disabled), .panel button:focus-visible { background: var(--surface-2); outline: none; }
  .panel button:disabled { opacity: 0.6; cursor: not-allowed; }
  hr { width: 100%; margin: 4px 0; border: 0; border-top: 1px solid var(--border); }
</style>
