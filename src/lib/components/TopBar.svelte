<script lang="ts">
  import { onMount } from "svelte";
  import { bridge, type EngineInfo } from "../api/bridgeClient";
  import { project, currentChapter, navigationStatus, bookAssignments, localUserId, assignedToMe } from "../stores";
  import { projectRoles, ROLE_NAMES } from "../projectRole";

  export let screen: "home" | "dashboard" | "validation" | "review" | "editor" | "report";
  export let projectName = "";
  export let onGoHome: () => void;
  export let onGoToDashboard: () => void;
  export let onOpenSettings: () => void;
  export let onOpenConnections: () => void;
  export let onOpenExport: () => void;
  // Project (dashboard) screen only: opens the whole-collection QA report.
  export let onGenerateReport: () => void = () => {};
  export let onGotoVerse: (verse: string) => void;
  export let onChapterChange: (chapter: string) => void;
  export let onBookChange: (path: string) => void;
  export let exportEnabled: boolean;
  export let bookSwitching = false;

  let gotoValue = "";
  // Best-effort: same call SettingsModal already makes; a slow or failed
  // lookup should never hold up the top bar, so failure just leaves the
  // version off rather than showing an error here.
  let engineInfo: EngineInfo | null = null;
  onMount(async () => {
    try {
      engineInfo = await bridge.engineInfo();
    } catch (e) {
      console.error("failed to load engine info", e);
    }
  });

  function handleBookSelect(e: Event) {
    const value = (e.target as HTMLSelectElement).value;
    onBookChange(value);
  }

  function jump() {
    const parts = gotoValue.trim().split(":");
    const chapterPart = parts.length > 1 ? parts[0] : null;
    const versePart = parts[parts.length - 1];
    if (chapterPart && chapterPart !== $currentChapter) {
      onChapterChange(chapterPart);
    }
    if (versePart) onGotoVerse(versePart);
  }

  function handleChapterSelect(e: Event) {
    const value = (e.target as HTMLSelectElement).value;
    onChapterChange(value);
  }

  /* Previous/next chapter (issue #53). "Previous" and "next" are defined by
     position in the same list the dropdown renders, not by numeric value, so
     stepping always agrees with what the reader can see -- and a book whose
     chapters are not a clean 1..n run still steps sensibly. Both routes call
     onChapterChange, so unsaved-edit handling, project, book and view mode
     follow whatever the dropdown already does, by construction. */
  $: chapters = $project?.chapters ?? [];
  $: chapterIndex = chapters.indexOf($currentChapter);
  $: hasPreviousChapter = chapterIndex > 0;
  $: hasNextChapter = chapterIndex >= 0 && chapterIndex < chapters.length - 1;

  function stepChapter(delta: -1 | 1): void {
    const target = chapters[chapterIndex + delta];
    if (target !== undefined) onChapterChange(target);
  }
</script>

<div class="topbar no-print">
  <div class="brand">
    <div class="mark" /> Bridge
    {#if engineInfo}<span class="version" title="Schema v{engineInfo.companionSchemaVersion}">{engineInfo.bridgeVersion}</span>{/if}
  </div>
  <div class="divider" />

  <nav class="breadcrumb" aria-label="Navigation">
    <button class="crumb" class:current={screen === "home"} on:click={onGoHome}>Projects</button>
    {#if screen === "dashboard" || screen === "validation" || screen === "review" || screen === "report"}
      <span class="crumb-sep">›</span>
      {#if screen === "validation"}
        <button class="crumb" on:click={onGoToDashboard}>{projectName}</button>
        <span class="crumb-sep">›</span>
        <span class="crumb current">Mapping validation</span>
      {:else if screen === "review"}
        <button class="crumb" on:click={onGoToDashboard}>{projectName}</button>
        <span class="crumb-sep">›</span>
        <span class="crumb current">Alignment Review</span>
      {:else if screen === "report"}
        <button class="crumb" on:click={onGoToDashboard}>{projectName}</button>
        <span class="crumb-sep">›</span>
        <span class="crumb current">QA report</span>
      {:else}
        <span class="crumb current">{projectName}</span>
      {/if}
    {:else if screen === "editor"}
      <span class="crumb-sep">›</span>
      <button class="crumb" on:click={onGoToDashboard} disabled={bookSwitching}>{projectName}</button>
      <span class="crumb-sep">›</span>
      {#if $project && $project.importedProjects && $project.importedProjects.length > 1}
        <select class="crumb-select" value={$project.path} on:change={handleBookSelect} disabled={bookSwitching}>
          {#each $project.importedProjects as book}
            <option value={book.path}>{book.bookName}</option>
          {/each}
        </select>
      {:else}
        <span class="crumb current">{$project?.bookName ?? ""}</span>
      {/if}
      {#if $projectRoles?.projectRole}
        <!-- #279: a role given on this project, which overrides the installation role here. -->
        <span class="project-role" title="Your role on this project; it decides what you can do here">
          {ROLE_NAMES[$projectRoles.projectRole] ?? $projectRoles.projectRole} on this project</span>
      {/if}
    {/if}
  </nav>

  {#if screen === "editor"}
    <div class="chapter-nav" role="group" aria-label="Chapter navigation">
      <button
        type="button"
        class="chapter-step"
        disabled={!hasPreviousChapter}
        title={hasPreviousChapter ? "Previous chapter" : "Already at the first chapter"}
        aria-label="Previous chapter"
        on:click={() => stepChapter(-1)}
      >‹</button>
      <!-- Sized by its widest option, not a fixed 72px: "Ch 119 ●" was cut to
           "Ch 11" at that width, and the in-app text size makes it wider still (#209). -->
      <select class="select chapter-select" value={$currentChapter} on:change={handleChapterSelect}>
        {#each chapters as ch}
          <option value={ch}>Ch {ch}{assignedToMe($bookAssignments, ch, $localUserId) ? " ●" : ""}</option>
        {/each}
      </select>
      <button
        type="button"
        class="chapter-step"
        disabled={!hasNextChapter}
        title={hasNextChapter ? "Next chapter" : "Already at the last chapter"}
        aria-label="Next chapter"
        on:click={() => stepChapter(1)}
      >›</button>
    </div>
    <div class="goto">
      <input
        bind:value={gotoValue}
        placeholder="Go to 1:4"
        on:keydown={(e) => e.key === "Enter" && jump()}
      />
    </div>
  {/if}

  <div class="grow" />
  <button
    class="sync-status"
    class:enabled={$navigationStatus.enabled}
    on:click={onOpenConnections}
    title={$navigationStatus.ownerConflict ? "Another Bridge window owns desktop navigation" : "Paratext and Logos navigation"}
  >
    {#if $navigationStatus.enabled}
      <span class:connected={$navigationStatus.paratext.connected} class:error={Boolean($navigationStatus.paratext.error)}>P</span>
      <span class:connected={$navigationStatus.logos.connected} class:error={Boolean($navigationStatus.logos.error)}>L</span>
      Sync
    {:else}
      Sync off
    {/if}
  </button>
  {#if screen === "dashboard"}
    <button class="btn primary" on:click={onGenerateReport}>Generate report</button>
  {/if}
  {#if screen === "editor"}
    <button class="btn primary" disabled={!exportEnabled} on:click={onOpenExport}>Export</button>
  {/if}
  <button class="btn ghost" on:click={onOpenSettings}>Settings</button>
</div>

<style>
  .topbar { height: 52px; background: var(--surface); border-bottom: 1px solid var(--border); display: flex; align-items: center; padding: 0 16px; gap: 14px; flex-shrink: 0; }
  .brand { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: var(--fs-md); color: var(--text); white-space: nowrap; }
  .mark { width: 22px; height: 22px; border-radius: 6px; background: linear-gradient(135deg, var(--accent), var(--pass)); flex-shrink: 0; }
  .version { font-size: var(--fs-3xs); font-weight: 600; color: var(--text-3); }
  .divider { width: 1px; height: 24px; background: var(--border); flex-shrink: 0; }
  .breadcrumb { display: flex; align-items: center; gap: 4px; min-width: 0; flex-shrink: 1; overflow: hidden; }
  .crumb { border: 0; background: transparent; color: var(--text-2); font-size: var(--fs-sm); font-weight: 600; padding: 4px 6px; border-radius: 6px; cursor: pointer; max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .crumb:hover:not(:disabled) { background: var(--surface-2); color: var(--text); }
  .crumb:disabled { cursor: not-allowed; opacity: 0.6; }
  .crumb.current { color: var(--text); cursor: default; }
  .crumb.current:hover { background: transparent; }
  .crumb-sep { color: var(--text-3); font-size: var(--fs-sm); flex-shrink: 0; }
  .project-role { margin-left: 6px; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--border-strong); background: var(--surface-2); color: var(--text-2); font-size: var(--fs-2xs); font-weight: 650; white-space: nowrap; flex-shrink: 0; }
  .crumb-select { height: 28px; border: 1px solid transparent; border-radius: 6px; font-size: var(--fs-sm); font-weight: 600; padding: 0 4px; background: transparent; color: var(--text); max-width: 200px; }
  .crumb-select:hover { background: var(--surface-2); }
  /* Chapter stepper (issue #53): the two arrows read as one control with the
     dropdown between them, so the reader's eye finds prev/next where the
     chapter already is rather than somewhere else in the bar. */
  .chapter-nav { display: flex; align-items: center; gap: 3px; flex-shrink: 0; }
  .chapter-step {
    height: var(--control-h); width: 24px; flex-shrink: 0; box-sizing: border-box;
    display: inline-flex; align-items: center; justify-content: center;
    font: inherit; font-size: var(--fs-md); line-height: 1;
    border: 1px solid var(--border); border-radius: 6px;
    background: var(--surface); color: var(--text); cursor: pointer;
  }
  .chapter-step:hover:not(:disabled), .chapter-step:focus-visible {
    border-color: var(--border-strong); background: var(--surface-2);
  }
  .chapter-step:disabled { opacity: .4; cursor: not-allowed; }
  .select { height: var(--control-h); box-sizing: border-box; border: 1px solid var(--border); border-radius: 6px; font: inherit; font-size: var(--fs-sm); line-height: 1; padding: 0 6px; background: var(--surface); color: var(--text); flex-shrink: 0; }
  .chapter-select { min-width: 72px; width: auto; }
  .goto { display: inline-flex; align-items: center; gap: 6px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 6px; padding: 0 8px; height: var(--control-h); box-sizing: border-box; font: inherit; line-height: 1; width: 150px; flex-shrink: 0; }
  .goto input { border: none; background: transparent; font: inherit; font-size: var(--fs-sm); line-height: 1; color: var(--text); outline: none; width: 100%; }
  .grow { flex: 1; }
  .sync-status { display: inline-flex; align-items: center; gap: 4px; height: var(--control-h); box-sizing: border-box; padding: 0 8px; border: 1px solid var(--border); border-radius: 6px; background: transparent; color: var(--text-2); font: inherit; font-size: var(--fs-xs); font-weight: 600; line-height: 1; cursor: pointer; flex-shrink: 0; }
  .sync-status:hover { background: var(--surface-2); }
  .sync-status span { display: inline-grid; place-items: center; width: 16px; height: 16px; border-radius: 50%; background: var(--border-strong); color: var(--surface); font-size: var(--fs-3xs); }
  .sync-status span.connected { background: var(--success); }
  .sync-status span.error { background: var(--danger); }
  /* #377: one control height. The height is the token, not the padding, so
     the three buttons measure the same as Sync, the selects and ‹ › beside
     them; `font: inherit` stops the browser's default button font setting a
     different line box. */
  .btn { height: var(--control-h); box-sizing: border-box; display: inline-flex; align-items: center; font: inherit; font-size: var(--fs-sm); font-weight: 600; line-height: 1; padding: 0 12px; border-radius: 6px; border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); cursor: pointer; flex-shrink: 0; }
  .btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  .btn.primary:disabled { background: #B9C6E0; border-color: #B9C6E0; color: #fff; cursor: not-allowed; }
  .btn.ghost { background: transparent; border-color: var(--border); }
  @media (max-width: 900px) {
    .goto { width: 110px; }
    .crumb { max-width: 130px; }
  }
</style>
