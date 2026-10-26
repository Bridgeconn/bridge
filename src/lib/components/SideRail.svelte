<script lang="ts">
  // The strip at the far right of the editor (Benz, 2026-10-09): one button
  // per side panel, each toggling its column, and Settings, which opens the
  // Settings dialog. Labels are text, not an icon font (CLAUDE.md gotcha 9).
  import { SIDE_PANEL_ORDER, revealSidePanel, sidePanels, toggleSidePanel } from "../editorPrefs";
  import { foldedPanels } from "../panelFit";
  import type { SidePanelId } from "../editorPrefs";
  import { languageQaChannel } from "../languageQaInline";
  import { currentChapter, paratextNoteCountsByVerse, selectedFindings, selectedVerse } from "../stores";
  import { noteCountFor } from "../paratextNotes";

  export let onOpenSettings: () => void = () => {};

  // An open panel folded for width (#324) is shown as not pressed, and a click
  // brings it back (folding another) rather than closing it.
  const isFolded = (id: SidePanelId): boolean => $sidePanels[id].open && $foldedPanels.has(id);
  function press(id: SidePanelId): void {
    if (isFolded(id)) revealSidePanel(id);
    else toggleSidePanel(id);
  }

  $: reviewBadge = $selectedFindings.filter((f) => f.status === "open").length;
  $: lqaBadge = $languageQaChannel.error ? "!" : ($languageQaChannel.status?.totalFindings ?? 0);
  // #357: open Paratext note threads on the selected verse.
  $: ptBadge = $selectedVerse ? noteCountFor($paratextNoteCountsByVerse, $currentChapter, $selectedVerse).open : 0;

  // #379 item 6: the rail runs top to bottom in the order the columns run
  // left to right (SIDE_PANEL_ORDER), so a button and its panel line up.
  const LABELS: Record<SidePanelId, { label: string; title: string }> = {
    source: { label: "Source", title: "The Hebrew, Aramaic or Greek source beside the text" },
    reference: { label: "Reference", title: "A reference Bible beside the text" },
    languageQa: { label: "Language QA", title: "Language QA for the book" },
    paratext: { label: "Paratext", title: "Paratext Project Notes on the selected verse" },
    review: { label: "Review", title: "Review the selected verse" },
  };
  const PANELS: { id: SidePanelId; label: string; title: string }[] =
    SIDE_PANEL_ORDER.map((id) => ({ id, ...LABELS[id] }));
</script>

<nav class="rail" aria-label="Side panels">
  {#each PANELS as panel (panel.id)}
    {@const badge = panel.id === "review" ? reviewBadge : panel.id === "languageQa" ? lqaBadge : panel.id === "paratext" ? ptBadge : 0}
    {@const folded = $sidePanels[panel.id].open && $foldedPanels.has(panel.id)}
    <button type="button" class="rail-btn" aria-pressed={$sidePanels[panel.id].open && !folded}
      class:folded aria-controls={`side-panel-${panel.id}`}
      title={folded ? `${panel.title} (folded: the window is too narrow; click to show it)` : panel.title}
      on:click={() => press(panel.id)}>
      <span class="rail-label">{panel.label}</span>
      {#if badge}<span class="rail-badge" class:alert={badge === "!"}>{badge}</span>{/if}
    </button>
  {/each}
  <span class="grow" />
  <button type="button" class="rail-btn" title="Settings" on:click={onOpenSettings}>
    <span class="rail-label">Settings</span>
  </button>
</nav>

<style>
  .rail { width: 34px; flex-shrink: 0; display: flex; flex-direction: column; align-items: stretch; gap: 2px;
    padding: 6px 0; border-left: 1px solid var(--border); background: var(--surface-2); }
  .grow { flex: 1; }
  .rail-btn { position: relative; display: flex; flex-direction: column; align-items: center; gap: 4px;
    padding: 10px 0; border: 0; border-left: 3px solid transparent; background: none; color: var(--text-2);
    cursor: pointer; font: inherit; font-size: var(--fs-3xs); font-weight: 700; }
  .rail-btn:hover { color: var(--text); background: var(--surface); }
  .rail-btn[aria-pressed="true"] { color: var(--accent); border-left-color: var(--accent); background: var(--surface); }
  .rail-btn.folded { border-left: 3px dashed var(--accent); }
  .rail-label { writing-mode: vertical-rl; white-space: nowrap; }
  .rail-badge { min-width: 16px; padding: 0 3px; border-radius: 999px; background: var(--accent-bg); color: var(--accent);
    font-size: var(--fs-3xs); line-height: 16px; text-align: center; }
  .rail-btn[aria-pressed="true"] .rail-badge { background: var(--accent); color: white; }
  .rail-badge.alert { background: var(--danger); color: white; }
</style>
