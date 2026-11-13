<script lang="ts">
  /** The editor's left rail (2026-11-13), in place of the top bar's menus: a
   *  fixed column of icon buttons, each with an instant hint to its right.
   *  The first five are the work area's panes (2026-11-14, EditorTabs): the
   *  verse list, on by default, and the four side panels. A click opens a
   *  pane as a tab (in the group last used) and shows it; on a tab that is
   *  open but behind another it shows it; on one that is showing it closes it. An open pane's icon is blue,
   *  the one showing also has the tint and the bar. Language QA has no
   *  button: it is a tab of the Review panel (#487). Check, Bookmarks and
   *  Alignment are App's, in the slot below. */
  import UiIcon from "./UiIcon.svelte";
  import { tooltip } from "../tooltip";
  import { setSidePanel, sidePanels, toggleSidePanel } from "../editorPrefs";
  import { EDITOR_TABS, closeTab, openTabs, selectTab, showTab, visibleTabs, type EditorTabId } from "../editorTabs";

  const ORDER: readonly EditorTabId[] = ["editor", "source", "reference", "paratext", "review"];

  // Open at all: a tab, or (a side panel) in its own window.
  $: isOpen = (id: EditorTabId): boolean => $openTabs.includes(id) || (id !== "editor" && $sidePanels[id].open);

  function choose(id: EditorTabId): void {
    if ($visibleTabs.has(id)) closeTab(id);
    else if ($openTabs.includes(id)) selectTab(id);
    else if (id === "editor") showTab(id);
    // In its own window: close it, and it is a tab the next time it opens.
    else if ($sidePanels[id].open && $sidePanels[id].detached) setSidePanel(id, { open: false, detached: false });
    // Closed: open it, as a tab.
    else toggleSidePanel(id);
  }

  $: hint = (id: EditorTabId): string => {
    const meta = EDITOR_TABS[id];
    if ($visibleTabs.has(id)) return `${meta.title}. Click to close it`;
    if ($openTabs.includes(id)) return `${meta.title}. Click to show it`;
    return meta.title;
  };
</script>

<nav class="activity-bar no-print" aria-label="Editor tools">
  <div class="group" role="group" aria-label="Panels">
    {#each ORDER as id (id)}
      <button type="button" class="rail-btn" class:open={isOpen(id)} class:active={$visibleTabs.has(id)}
        aria-label={EDITOR_TABS[id].label} aria-pressed={isOpen(id)}
        use:tooltip={{ text: hint(id), side: "right" }}
        on:click={() => choose(id)}>
        <UiIcon name={EDITOR_TABS[id].icon} />
      </button>
    {/each}
  </div>
  <span class="rule" aria-hidden="true" />
  <div class="group"><slot /></div>
</nav>

<style>
  .activity-bar { flex: none; width: 44px; display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 6px 0; box-sizing: border-box; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; overflow: visible; }
  .group { display: flex; flex-direction: column; align-items: center; gap: 4px; }
  .rule { width: 22px; height: 1px; background: var(--border); }
</style>
