<script lang="ts">
  // The strip at the far right of the editor (Benz, 2026-10-09): one button
  // per side panel, each toggling its column, and Settings, which opens the
  // Settings dialog. Labels are text, not an icon font (CLAUDE.md gotcha 9).
  import { sidePanels, toggleSidePanel } from "../editorPrefs";
  import type { SidePanelId } from "../editorPrefs";
  import { languageQaChannel } from "../languageQaInline";
  import { selectedFindings } from "../stores";

  export let onOpenSettings: () => void = () => {};

  $: reviewBadge = $selectedFindings.filter((f) => f.status === "open").length;
  $: lqaBadge = $languageQaChannel.error ? "!" : ($languageQaChannel.status?.totalFindings ?? 0);

  const PANELS: { id: SidePanelId; label: string; title: string }[] = [
    { id: "review", label: "Review", title: "Review the selected verse" },
    { id: "languageQa", label: "Language QA", title: "Language QA for the book" },
    { id: "reference", label: "Reference", title: "A reference Bible beside the text" },
    { id: "source", label: "Source", title: "The Hebrew, Aramaic or Greek source beside the text" },
  ];
</script>

<nav class="rail" aria-label="Side panels">
  {#each PANELS as panel (panel.id)}
    {@const badge = panel.id === "review" ? reviewBadge : panel.id === "languageQa" ? lqaBadge : 0}
    <button type="button" class="rail-btn" aria-pressed={$sidePanels[panel.id].open}
      aria-controls={`side-panel-${panel.id}`} title={panel.title}
      on:click={() => toggleSidePanel(panel.id)}>
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
  .rail-label { writing-mode: vertical-rl; white-space: nowrap; }
  .rail-badge { min-width: 16px; padding: 0 3px; border-radius: 999px; background: var(--accent-bg); color: var(--accent);
    font-size: var(--fs-3xs); line-height: 16px; text-align: center; }
  .rail-btn[aria-pressed="true"] .rail-badge { background: var(--accent); color: white; }
  .rail-badge.alert { background: var(--danger); color: white; }
</style>
