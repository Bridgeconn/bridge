<script lang="ts">
  /** Assign a book, or its chapters, to users (#240, requirement 5). A
   *  project_admin's dialog, opened from a book row on the dashboard. Pure
   *  UI: the parent owns the engine calls.
   *
   *  #378: pick the person once, tick the chapters (or a range, or the whole
   *  book), apply once. Nothing is written until Apply; Apply sends one
   *  existing engine call per changed chapter, in order, and shows how far
   *  it is. The team_assignments contract (#240) is unchanged: there is no
   *  batch RPC, and an empty choice ("Nobody") clears the assignment. */
  import { onMount, tick } from "svelte";
  import type { Assignment, WorkspaceUser } from "../types/finding";

  export let bookName: string;
  export let chapters: string[];
  export let users: WorkspaceUser[];
  export let assignments: Assignment[];
  export let busy = false;
  export let error = "";
  /** One chapter ("" = whole book). Resolves false when the parent could not save it. */
  export let onSet: (chapter: string, userId: string) => Promise<boolean | void> | boolean | void;
  export let onClear: (chapter: string) => Promise<boolean | void> | boolean | void;
  /** After an Apply has sent its last change: the parent refreshes once. */
  export let onApplied: () => void = () => {};
  export let onClose: () => void;

  /** The picker's "clear" choice: what the engine receives as no assignee. */
  const NOBODY = "";

  // Step 1: who. null until a choice is made.
  let picked: string | null = null;
  let query = "";
  let listOpen = false;
  let highlighted = 0;
  let searchBox: HTMLInputElement | null = null;

  // Step 2: what. "" is the whole book; `anchor` serves Shift-click.
  let selected = new Set<string>();
  let anchor: string | null = null;
  let rangeFrom = "";
  let rangeTo = "";

  // Apply.
  let applying = false;
  let applied = 0;
  let planned = 0;
  let lastApplied = 0;
  let applyError = "";

  $: active = users.filter((user) => user.active);
  $: byChapter = Object.fromEntries(assignments.map((item) => [item.chapter, item])) as Record<string, Assignment>;
  $: pickedLabel = picked === null ? "" : picked === NOBODY ? "Nobody (clear)"
    : active.find((user) => user.userId === picked)?.displayName ?? picked;
  $: matches = [{ userId: NOBODY, displayName: "Nobody (clear)" }, ...active.map((u) => ({ userId: u.userId, displayName: u.displayName }))]
    .filter((option) => !query.trim() || option.displayName.toLowerCase().includes(query.trim().toLowerCase()));
  $: if (highlighted >= matches.length) highlighted = Math.max(0, matches.length - 1);

  /** The chapters a change would touch: ticked, and not already held by the pick. */
  $: changes = picked === null ? []
    : ["", ...chapters].filter((chapter) => selected.has(chapter) && (byChapter[chapter]?.assigneeId ?? "") !== picked);
  $: wouldChange = new Set(changes);

  function label(chapter: string): string {
    return chapter ? `Chapter ${chapter}` : "Whole book";
  }

  /** "RI" for Rina Issac; the full name is the cell's tooltip. */
  function initials(name: string | undefined): string {
    if (!name) return "";
    const parts = name.trim().split(/\s+/).filter(Boolean);
    return parts.slice(0, 2).map((part) => Array.from(part)[0]?.toUpperCase() ?? "").join("");
  }

  function pick(userId: string): void {
    picked = userId;
    query = "";
    listOpen = false;
  }

  function onSearchKeydown(event: KeyboardEvent): void {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      listOpen = true;
      highlighted = Math.min(highlighted + 1, matches.length - 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      highlighted = Math.max(highlighted - 1, 0);
    } else if (event.key === "Enter" && listOpen && matches[highlighted]) {
      event.preventDefault();
      pick(matches[highlighted].userId);
    } else if (event.key === "Escape" && listOpen) {
      // The list closes first; a second Escape closes the dialog.
      event.preventDefault();
      listOpen = false;
    }
  }

  function toggleChapter(chapter: string, shift: boolean): void {
    const next = new Set(selected);
    if (shift && anchor !== null && chapter !== "" && anchor !== "") {
      const from = chapters.indexOf(anchor);
      const to = chapters.indexOf(chapter);
      for (const at of chapters.slice(Math.min(from, to), Math.max(from, to) + 1)) next.add(at);
    } else if (next.has(chapter)) {
      next.delete(chapter);
    } else {
      next.add(chapter);
    }
    selected = next;
    anchor = chapter;
  }

  function selectAll(): void {
    selected = new Set(chapters);
    anchor = null;
  }

  function clearSelection(): void {
    selected = new Set();
    anchor = null;
  }

  /** "3–7" adds every chapter between the two, inclusive; one box alone adds that chapter. */
  function addRange(): void {
    const from = chapters.indexOf(rangeFrom.trim() || rangeTo.trim());
    const to = chapters.indexOf(rangeTo.trim() || rangeFrom.trim());
    if (from < 0 || to < 0) return;
    const next = new Set(selected);
    for (const chapter of chapters.slice(Math.min(from, to), Math.max(from, to) + 1)) next.add(chapter);
    selected = next;
    rangeFrom = "";
    rangeTo = "";
  }

  async function apply(): Promise<void> {
    if (applying || picked === null || !changes.length) return;
    applying = true;
    applyError = "";
    applied = 0;
    planned = changes.length;
    const todo = [...changes];
    try {
      for (const chapter of todo) {
        const ok = picked === NOBODY ? await onClear(chapter) : await onSet(chapter, picked);
        if (ok === false) {
          applyError = `Stopped after ${applied} of ${planned}: ${label(chapter)} was not saved.`;
          break;
        }
        applied += 1;
      }
    } catch (cause) {
      applyError = cause instanceof Error ? cause.message : String(cause);
    } finally {
      applying = false;
      lastApplied = applied;
      if (applied > 0) {
        selected = new Set();
        anchor = null;
        onApplied();
      }
    }
  }

  // #321: Escape does what the × does, and focus goes back to the button that
  // opened the dialog (the CheckerSettingsDialog pattern). While an Apply is
  // sending, the dialog stays open until it is done.
  let openedFrom: Element | null = null;
  onMount(() => {
    openedFrom = document.activeElement;
    void tick().then(() => searchBox?.focus());
    return () => { if (openedFrom instanceof HTMLElement && openedFrom.isConnected) openedFrom.focus(); };
  });

  function onWindowKeydown(event: KeyboardEvent): void {
    if (event.key === "Escape" && !event.defaultPrevented && !applying) onClose();
  }
</script>

<svelte:window on:keydown={onWindowKeydown} />

<div class="overlay" role="dialog" aria-labelledby="assign-title">
  <div class="dialog">
    <button class="close-btn" on:click={onClose} aria-label="Close assignments" disabled={applying}>✕</button>
    <h2 id="assign-title">Assign {bookName}</h2>
    <p class="desc">Pick a person, tick the chapters, apply once. A book assignment covers every chapter unless a chapter names someone else; "My work" on the dashboard and the chapter list follow these.</p>
    {#if active.length === 0}
      <p class="muted">No active users. Add one in Settings › Users.</p>
    {:else}
      <section class="step" aria-labelledby="assign-who">
        <h3 id="assign-who">1. Who</h3>
        <div class="picker">
          <input bind:this={searchBox} role="combobox" aria-label="Person" aria-expanded={listOpen} aria-controls="assign-people"
            aria-autocomplete="list" autocomplete="off" placeholder={pickedLabel || "Search people…"} value={query}
            disabled={applying}
            on:input={(event) => { query = event.currentTarget.value; listOpen = true; highlighted = 0; }}
            on:focus={() => (listOpen = true)}
            on:blur={() => (listOpen = false)}
            on:keydown={onSearchKeydown} />
          {#if listOpen}
            <ul id="assign-people" class="people" role="listbox" aria-label="People">
              {#each matches as option, at (option.userId)}
                <li role="option" aria-selected={option.userId === picked} class:highlighted={at === highlighted}
                  class:nobody={option.userId === NOBODY}
                  on:mousedown|preventDefault={() => pick(option.userId)}>{option.displayName}</li>
              {:else}
                <li class="no-match">Nobody matches</li>
              {/each}
            </ul>
          {/if}
          {#if picked !== null}
            <span class="picked" data-testid="picked-person">{pickedLabel}</span>
          {/if}
        </div>
      </section>

      <section class="step" aria-labelledby="assign-what">
        <h3 id="assign-what">2. What</h3>
        <div class="tools">
          <label class="cell book" class:changing={wouldChange.has("")}>
            <input type="checkbox" aria-label="Whole book" checked={selected.has("")} disabled={applying}
              on:click={() => toggleChapter("", false)} />
            <span class="num">Whole book</span>
            <span class="who" title={byChapter[""]?.assigneeName ?? ""}>{byChapter[""]?.assigneeName ?? "nobody"}</span>
          </label>
          <button type="button" on:click={selectAll} disabled={applying}>Select all</button>
          <button type="button" on:click={clearSelection} disabled={applying || !selected.size}>Clear selection</button>
          <span class="range">
            <input aria-label="From chapter" bind:value={rangeFrom} placeholder="from" inputmode="numeric" disabled={applying}
              on:keydown={(event) => { if (event.key === "Enter") { event.preventDefault(); addRange(); } }} />
            –
            <input aria-label="To chapter" bind:value={rangeTo} placeholder="to" inputmode="numeric" disabled={applying}
              on:keydown={(event) => { if (event.key === "Enter") { event.preventDefault(); addRange(); } }} />
            <button type="button" on:click={addRange} disabled={applying || !(rangeFrom.trim() || rangeTo.trim())}>Add range</button>
          </span>
        </div>
        <!-- Each cell: the chapter, who holds it now (initials, name in the
             tooltip), and a mark where Apply would change it. Shift-click
             ticks every chapter from the last one clicked to this one. -->
        <div class="grid" role="group" aria-label="Chapters of {bookName}">
          {#each chapters as chapter (chapter)}
            <label class="cell" class:changing={wouldChange.has(chapter)} class:ticked={selected.has(chapter)}
              title={byChapter[chapter]?.assigneeName ? `${label(chapter)}: ${byChapter[chapter].assigneeName}` : `${label(chapter)}: nobody`}>
              <input type="checkbox" aria-label={label(chapter)} checked={selected.has(chapter)} disabled={applying}
                on:click={(event) => toggleChapter(chapter, event.shiftKey)} />
              <span class="num">{chapter}</span>
              <span class="who">{initials(byChapter[chapter]?.assigneeName)}</span>
            </label>
          {/each}
        </div>
      </section>

      <div class="apply-row">
        <span class="summary" aria-live="polite">
          {#if applying}
            Applying {Math.min(applied + 1, planned)} of {planned}…
          {:else if picked === null}
            Pick a person first.
          {:else if !selected.size}
            Tick the chapters to give to {pickedLabel}.
          {:else if !changes.length}
            {pickedLabel} already holds the ticked {selected.size === 1 ? "chapter" : "chapters"}.
          {:else}
            {pickedLabel} → {changes.length} {changes.length === 1 ? "change" : "changes"}
          {/if}
        </span>
        <button type="button" class="apply" on:click={apply} disabled={applying || busy || picked === null || !changes.length}>
          {changes.length ? `Apply (${changes.length})` : "Apply"}
        </button>
      </div>
      {#if lastApplied && !applying && !applyError}<p class="muted" role="status">Applied {lastApplied} {lastApplied === 1 ? "change" : "changes"}.</p>{/if}
    {/if}
    {#if applyError}<p class="error" role="alert">{applyError}</p>{/if}
    {#if error}<p class="error">{error}</p>{/if}
  </div>
</div>

<style>
  .overlay { position: absolute; inset: 0; background: rgba(15, 20, 26, 0.45); display: flex; align-items: center; justify-content: center; z-index: var(--z-dialog); }
  .dialog { width: min(640px, calc(100% - 32px)); max-height: 85vh; overflow: auto; background: var(--surface); border-radius: 14px; padding: 20px 24px; position: relative; }
  .close-btn { position: absolute; top: 10px; right: 10px; width: 28px; height: 28px; border-radius: 6px; border: none; background: transparent; color: var(--text-2); font-size: var(--fs-lg); cursor: pointer; }
  h2 { font-size: var(--fs-lg); margin: 0 0 6px; color: var(--text); }
  h3 { font-size: var(--fs-xs); margin: 0 0 6px; color: var(--text-2); font-weight: 700; }
  .desc, .muted { font-size: var(--fs-xs); color: var(--text-2); line-height: 1.5; margin: 0 0 12px; }
  .step { margin: 0 0 14px; }
  .picker { position: relative; display: flex; align-items: center; gap: 10px; }
  .picker input { flex: 0 1 280px; font: inherit; padding: 5px 8px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface); color: var(--text); }
  .people { position: absolute; z-index: var(--z-dropdown); left: 0; top: calc(100% + 4px); width: 280px; max-height: 215px; overflow: auto; margin: 0; padding: 4px; list-style: none; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface); box-shadow: 0 10px 25px rgba(25, 35, 55, .16); }
  .people li { padding: 6px 10px; border-radius: 5px; font-size: var(--fs-xs); color: var(--text); cursor: pointer; }
  .people li.highlighted, .people li:hover { background: var(--accent-bg); }
  .people li[aria-selected="true"] { font-weight: 700; }
  .people li.nobody { color: var(--text-2); font-style: italic; }
  .people .no-match { color: var(--text-3); cursor: default; }
  .picked { font-size: var(--fs-xs); font-weight: 700; color: var(--accent); }
  .tools { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 10px; margin: 0 0 8px; font-size: var(--fs-2xs); }
  .tools button, .range button { font: inherit; font-size: var(--fs-2xs); padding: 3px 8px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface); color: var(--text); cursor: pointer; }
  .tools button:disabled, .range button:disabled, .apply:disabled { opacity: .55; cursor: not-allowed; }
  .range { display: inline-flex; align-items: center; gap: 4px; color: var(--text-3); }
  .range input { width: 48px; font: inherit; font-size: var(--fs-2xs); padding: 3px 6px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface); color: var(--text); }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(58px, 1fr)); gap: 4px; }
  .cell { display: flex; align-items: center; gap: 4px; padding: 3px 5px; border: 1px solid var(--border); border-radius: 6px; font-size: var(--fs-2xs); color: var(--text); cursor: pointer; min-width: 0; }
  .cell input { margin: 0; flex-shrink: 0; }
  .cell.ticked { border-color: var(--accent); background: var(--accent-bg); }
  .cell.changing { box-shadow: inset 0 -2px 0 var(--warning); }
  .cell.book { border-color: var(--border-strong); font-weight: 700; }
  .num { font-weight: 700; flex-shrink: 0; }
  .who { color: var(--text-3); font-size: var(--fs-3xs); font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cell.book .who { font-weight: 500; }
  .apply-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border); }
  .summary { font-size: var(--fs-xs); color: var(--text-2); min-width: 0; }
  .apply { font: inherit; font-size: var(--fs-xs); font-weight: 700; padding: 6px 14px; border: 1px solid var(--accent); border-radius: 7px; background: var(--accent); color: #fff; cursor: pointer; flex-shrink: 0; }
  .error { color: var(--danger); font-size: var(--fs-xs); margin: 10px 0 0; }
</style>
