<script lang="ts">
  /** Assign a book, or its chapters, to users (#240, requirement 5). A
   *  project_admin's dialog, opened from a book row on the dashboard. Pure
   *  UI: the parent owns the engine calls. The book row ("whole book") and
   *  one row per chapter; an empty choice clears the assignment. */
  import type { Assignment, WorkspaceUser } from "../types/finding";

  export let bookName: string;
  export let chapters: string[];
  export let users: WorkspaceUser[];
  export let assignments: Assignment[];
  export let busy = false;
  export let error = "";
  export let onSet: (chapter: string, userId: string) => void;
  export let onClear: (chapter: string) => void;
  export let onClose: () => void;

  $: active = users.filter((user) => user.active);
  $: byChapter = Object.fromEntries(assignments.map((item) => [item.chapter, item])) as Record<string, Assignment>;

  function change(chapter: string, value: string) {
    if (value) onSet(chapter, value);
    else onClear(chapter);
  }

  function label(chapter: string): string {
    return chapter ? `Chapter ${chapter}` : "Whole book";
  }
</script>

<div class="overlay" role="dialog" aria-labelledby="assign-title">
  <div class="dialog">
    <button class="close-btn" on:click={onClose} aria-label="Close assignments">✕</button>
    <h2 id="assign-title">Assign {bookName}</h2>
    <p class="desc">Who works on what. A book assignment covers every chapter unless a chapter names someone else; "My work" on the dashboard and the chapter list follow these.</p>
    {#if active.length === 0}
      <p class="muted">No active users. Add one in Settings › Users.</p>
    {:else}
      <table class="rows" aria-label="Assignments for {bookName}">
        <thead><tr><th>Scope</th><th>Assigned to</th><th>Since</th></tr></thead>
        <tbody>
          {#each ["", ...chapters] as chapter (chapter)}
            <tr class:book={!chapter}>
              <td>{label(chapter)}</td>
              <td>
                <select aria-label="Assignee for {label(chapter)}" value={byChapter[chapter]?.assigneeId ?? ""} disabled={busy}
                  on:change={(event) => change(chapter, event.currentTarget.value)}>
                  <option value="">— nobody —</option>
                  {#each active as user (user.userId)}
                    <option value={user.userId}>{user.displayName}</option>
                  {/each}
                </select>
              </td>
              <td class="since">{byChapter[chapter]?.assignedAt ? new Date(byChapter[chapter].assignedAt).toLocaleDateString() : ""}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
    {#if error}<p class="error">{error}</p>{/if}
  </div>
</div>

<style>
  .overlay { position: absolute; inset: 0; background: rgba(15, 20, 26, 0.45); display: flex; align-items: center; justify-content: center; z-index: 30; }
  .dialog { width: min(560px, calc(100% - 32px)); max-height: 80vh; overflow: auto; background: var(--surface); border-radius: 14px; padding: 20px 24px; position: relative; }
  .close-btn { position: absolute; top: 10px; right: 10px; width: 28px; height: 28px; border-radius: 6px; border: none; background: transparent; color: var(--text-2); font-size: var(--fs-lg); cursor: pointer; }
  h2 { font-size: var(--fs-lg); margin: 0 0 6px; color: var(--text); }
  .desc, .muted { font-size: var(--fs-xs); color: var(--text-2); line-height: 1.5; margin: 0 0 12px; }
  .rows { width: 100%; border-collapse: collapse; font-size: var(--fs-xs); }
  .rows th, .rows td { text-align: left; padding: 5px 8px; border-bottom: 1px solid var(--border); color: var(--text); }
  .rows th { color: var(--text-2); font-weight: 650; }
  tr.book td { font-weight: 700; }
  select { font: inherit; padding: 3px 6px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface); color: var(--text); min-width: 160px; }
  .since { color: var(--text-3); font-size: var(--fs-2xs); }
  .error { color: var(--danger); font-size: var(--fs-xs); margin: 10px 0 0; }
</style>
