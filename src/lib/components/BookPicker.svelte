<script lang="ts">
  /** The top bar's book switcher (2026-11-13; a <select> in the editor
   *  panel's header before): the open book's name as the breadcrumb's last
   *  crumb, opening a list of the collection's books with a search box that
   *  filters as you type, by name or by book code. Arrow keys move, Enter
   *  opens the marked book, Escape closes. The list is drawn `fixed`, since
   *  the breadcrumb clips what leaves it. */
  import { onDestroy, tick } from "svelte";
  import UiIcon from "./UiIcon.svelte";
  import type { ImportedProject } from "../types/finding";

  export let books: ImportedProject[] = [];
  export let currentPath = "";
  export let currentName = "";
  /** A book is being opened: choosing another would start a second wait. */
  export let disabled = false;
  /** The name is in a non-Latin script: set a step smaller, like the crumbs. */
  export let script = false;
  export let onChange: (path: string) => void = () => {};

  let open = false;
  let query = "";
  let active = 0;
  let root: HTMLElement;
  let trigger: HTMLButtonElement;
  let search: HTMLInputElement;
  let list: HTMLElement;
  let place = "";

  const fold = (text: string): string => text.normalize("NFKC").toLocaleLowerCase();
  $: needle = fold(query.trim());
  $: matches = needle
    ? books.filter((book) => fold(book.bookName).includes(needle) || fold(book.bookId ?? "").includes(needle))
    : books;
  $: if (active >= matches.length) active = Math.max(0, matches.length - 1);

  async function show(): Promise<void> {
    if (disabled) return;
    const rect = trigger.getBoundingClientRect();
    const width = 260;
    place = `left:${Math.max(8, Math.min(rect.left, window.innerWidth - width - 8))}px;top:${rect.bottom + 4}px;width:${width}px;max-height:${Math.max(160, window.innerHeight - rect.bottom - 16)}px`;
    query = "";
    active = Math.max(0, books.findIndex((book) => book.path === currentPath));
    open = true;
    await tick();
    search?.focus();
    reveal();
  }
  function close(refocus: boolean): void {
    if (!open) return;
    open = false;
    if (refocus) trigger?.focus();
  }
  function choose(book: ImportedProject | undefined): void {
    if (!book) return;
    close(true);
    if (book.path !== currentPath) onChange(book.path);
  }
  async function reveal(): Promise<void> {
    await tick();
    list?.querySelector<HTMLElement>(".option.active")?.scrollIntoView?.({ block: "nearest" });
  }
  function onSearchKey(event: KeyboardEvent): void {
    if (event.key === "ArrowDown") { event.preventDefault(); if (matches.length) active = (active + 1) % matches.length; void reveal(); }
    else if (event.key === "ArrowUp") { event.preventDefault(); if (matches.length) active = (active - 1 + matches.length) % matches.length; void reveal(); }
    else if (event.key === "Home") { event.preventDefault(); active = 0; void reveal(); }
    else if (event.key === "End") { event.preventDefault(); active = Math.max(0, matches.length - 1); void reveal(); }
    else if (event.key === "Enter") { event.preventDefault(); choose(matches[active]); }
    else if (event.key === "Tab") close(false);
  }

  function onDocumentPointer(event: MouseEvent): void {
    if (open && root && !root.contains(event.target as Node)) close(false);
  }
  function onKey(event: KeyboardEvent): void {
    if (open && event.key === "Escape") { event.preventDefault(); close(true); }
  }
  const onResize = () => close(false);
  document.addEventListener("mousedown", onDocumentPointer);
  // The top bar is a window-drag region: the shell takes a mousedown there
  // before the page sees it, so a click on the bar is caught as a pointerdown.
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

<span class="book-picker" bind:this={root}>
  <button type="button" class="trigger" class:script class:open bind:this={trigger} {disabled}
    aria-label={`Book: ${currentName}`} aria-haspopup="listbox" aria-expanded={open} title="Switch to another book of this project"
    on:click={() => (open ? close(false) : void show())}
    on:keydown={(event) => { if (event.key === "ArrowDown" && !open) { event.preventDefault(); void show(); } }}>
    <span class="name">{currentName}</span><UiIcon name="chevronDown" />
  </button>
  {#if open}
    <div class="panel" style={place}>
      <input class="search" bind:this={search} bind:value={query} type="text" role="combobox" aria-label="Search books"
        aria-expanded="true" aria-controls="book-picker-list" aria-autocomplete="list"
        aria-activedescendant={matches.length ? `book-picker-option-${active}` : undefined}
        placeholder="Search books" autocomplete="off" spellcheck="false"
        on:input={() => (active = 0)} on:keydown={onSearchKey} />
      <div class="options" id="book-picker-list" role="listbox" aria-label="Books" bind:this={list}>
        {#each matches as book, index (book.path)}
          <!-- svelte-ignore a11y-click-events-have-key-events -->
          <div class="option" id={`book-picker-option-${index}`} role="option" tabindex="-1"
            class:active={index === active} class:current={book.path === currentPath}
            aria-selected={book.path === currentPath}
            on:mousemove={() => (active = index)} on:click={() => choose(book)}>
            <span class="tick" aria-hidden="true">{#if book.path === currentPath}<UiIcon name="check" />{/if}</span>
            <span class="label">{book.bookName}</span>
            {#if book.bookId}<span class="code">{book.bookId.toUpperCase()}</span>{/if}
          </div>
        {:else}
          <p class="none">No book matches “{query.trim()}”.</p>
        {/each}
      </div>
    </div>
  {/if}
</span>

<style>
  .book-picker { display: inline-flex; min-width: 0; }
  .trigger { display: inline-flex; align-items: center; gap: 3px; min-width: 0; max-width: 220px; padding: 2px 4px 2px 6px; border: 0; border-radius: 6px;
    background: transparent; color: var(--text); font: inherit; font-size: var(--fs-xs); font-weight: 600; cursor: pointer; transition: color .15s, background .15s; }
  .trigger.script { font-size: var(--fs-3xs); }
  .trigger .name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .trigger :global(svg) { width: 13px; height: 13px; flex: none; color: var(--text-3); transition: transform .15s; }
  .trigger:hover:not(:disabled), .trigger.open { background: var(--accent-bg); color: var(--accent); }
  .trigger:hover:not(:disabled) :global(svg), .trigger.open :global(svg) { color: var(--accent); }
  .trigger.open :global(svg) { transform: rotate(180deg); }
  .trigger:disabled { opacity: .6; cursor: not-allowed; }
  .panel { position: fixed; z-index: var(--z-dropdown); box-sizing: border-box; display: flex; flex-direction: column; gap: 6px; padding: 8px;
    border: 1px solid var(--border-strong); border-radius: 10px; background: var(--surface); box-shadow: 0 12px 32px rgba(0,0,0,.16); }
  .search { flex: none; height: 30px; box-sizing: border-box; padding: 0 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-2);
    color: var(--text); font: inherit; font-size: var(--fs-2xs); }
  .search:focus-visible { outline: none; border-color: var(--accent); background: var(--surface); box-shadow: 0 0 0 3px var(--accent-bg); }
  .options { min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 1px; max-height: 320px; }
  .option { display: flex; align-items: center; gap: 6px; padding: 5px 8px; border-radius: 6px; color: var(--text); font-size: var(--fs-2xs); cursor: pointer; }
  .option.active { background: var(--accent-bg); color: var(--accent); }
  .option.current { font-weight: 700; }
  .tick { display: grid; place-items: center; width: 14px; flex: none; color: var(--accent); }
  .tick :global(svg) { width: 14px; height: 14px; }
  .label { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .code { flex: none; font-size: var(--fs-3xs); font-weight: 600; color: var(--text-3); letter-spacing: .03em; }
  .none { margin: 0; padding: 8px; color: var(--text-2); font-size: var(--fs-2xs); }
  @media (prefers-reduced-motion: reduce) { .trigger, .trigger :global(svg) { transition: none; } }
</style>
