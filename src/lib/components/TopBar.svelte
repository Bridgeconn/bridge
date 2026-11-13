<script lang="ts">
  import { onMount } from "svelte";
  import UiIcon from "./UiIcon.svelte";
  import BridgeMark from "./BridgeMark.svelte";
  import BookPicker from "./BookPicker.svelte";
  import { tooltip } from "../tooltip";
  import { isTauri } from "@tauri-apps/api/core";
  import { getCurrentWindow } from "@tauri-apps/api/window";

  let desktop = false;
  let maximized = false;
  onMount(() => {
    desktop = isTauri();
    if (!desktop) return;
    const appWindow = getCurrentWindow();
    let disposed = false;
    let unlisten: (() => void) | undefined;
    const updateMaximized = async () => {
      const value = await appWindow.isMaximized();
      if (!disposed) maximized = value;
    };
    void updateMaximized().catch(console.error);
    void appWindow.onResized(() => { void updateMaximized().catch(console.error); })
      .then((stop) => { if (disposed) stop(); else unlisten = stop; })
      .catch(console.error);
    return () => { disposed = true; unlisten?.(); };
  });

  async function windowAction(action: "minimize" | "toggleMaximize" | "close") {
    // Drop focus first: a window coming back from the taskbar gives focus
    // back to the button, and its hint would show with no pointer on it.
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    try {
      const appWindow = getCurrentWindow();
      await appWindow[action]();
      if (action === "toggleMaximize") maximized = await appWindow.isMaximized();
    } catch (error) {
      console.error(`Window ${action} failed`, error);
    }
  }
  import { bridge, type EngineInfo } from "../api/bridgeClient";
  import { navigationStatus, project } from "../stores";
  import { projectRoles, ROLE_NAMES } from "../projectRole";

  export let screen: "home" | "dashboard" | "validation" | "review" | "editor" | "report";
  export let projectName = "";
  export let onGoHome: () => void;
  export let onGoToDashboard: () => void;
  export let onOpenSettings: () => void;
  export let onOpenConnections: () => void;
  /** The editor's Export project (it was in the File menu). */
  export let onExport: (() => void) | undefined = undefined;
  export let exportDisabled = false;
  export let bookSwitching = false;
  /** Switch to another book of the collection (the editor's book picker). */
  export let onBookChange: (path: string) => void = () => {};
  $: books = $project?.importedProjects ?? [];

  // A name in an Indic or other non-Latin script draws taller and wider than
  // Latin text at the same font size (the fallback font's glyphs fill more of
  // the em box), so beside "Projects" it looks a size bigger. Such a crumb is
  // set two steps smaller, which evens the three out by eye.
  const nonLatin = (text: string): boolean => /[^\u0000-\u024F\u2000-\u206F]/.test(text);

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

</script>

<div class="topbar no-print" class:home-bar={screen === "home"} class:editor-bar={screen === "editor"} class:desktop-bar={desktop} data-tauri-drag-region>
  <div class="brand" data-tauri-drag-region>
    <span class="mark" data-tauri-drag-region><BridgeMark size={18} /></span> <span class="brand-name" data-tauri-drag-region>Bridge</span>
    {#if engineInfo && screen !== "editor"}<span class="version" data-tauri-drag-region title="Schema v{engineInfo.companionSchemaVersion}">{engineInfo.bridgeVersion}</span>{/if}
  </div>
  {#if screen === "editor"}
    <!-- 2026-11-13: the editor has the breadcrumb again (its menus moved to
         the left rail, ActivityBar.svelte):
         Projects, the project (opens the project page), then the open book
         with a close button that closes the editor. No version number here;
         the chapter picker and Go to stay in the editor panel's header. -->
    <div class="divider" />
    <nav class="breadcrumb editor-crumbs" aria-label="Navigation">
      <button class="crumb crumb-root" on:click={onGoHome} disabled={bookSwitching}>Projects</button>
      <span class="crumb-sep crumb-root">›</span>
      <button class="crumb" class:script={nonLatin(projectName)} title={`${projectName}: open the project page`} on:click={onGoToDashboard} disabled={bookSwitching}>{projectName}</button>
      {#if $project?.bookName}
        <span class="crumb-sep">›</span>
        {#if books.length > 1}
          <BookPicker {books} currentPath={$project.path} currentName={$project.bookName} script={nonLatin($project.bookName)}
            disabled={bookSwitching} onChange={onBookChange} />
        {:else}
          <span class="crumb current" class:script={nonLatin($project.bookName)}>{$project.bookName}</span>
        {/if}
      {/if}
      <button class="crumb-close" aria-label="Close editor" use:tooltip={"Close the book and return to the project page"} on:click={onGoToDashboard} disabled={bookSwitching}><UiIcon name="close" /></button>
    </nav>
    {#if $projectRoles?.projectRole}
      <!-- #279: a role given on this project, which overrides the installation role here. -->
      <span class="project-role" title="Your role on this project; it decides what you can do here">
        {ROLE_NAMES[$projectRoles.projectRole] ?? $projectRoles.projectRole} on this project</span>
    {/if}
  {:else if screen !== "home"}
  <div class="divider" />

  <nav class="breadcrumb" aria-label="Navigation">
    <button class="crumb" on:click={onGoHome}>Projects</button>
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
        <button class="crumb-close" aria-label="Close project" use:tooltip={"Close project and return to Projects"} on:click={onGoHome} disabled={bookSwitching}><UiIcon name="close" /></button>
      {/if}
    {/if}
  </nav>
  {/if}

  <div class="grow" data-tauri-drag-region />
  <!-- Navigation sync (Paratext / Logos following the current verse) only
       means something where there is a current verse: the editor, Alignment
       Review and validation. Home and the dashboard have none, so the
       indicator is not shown there; Settings > Connections stays reachable
       from every screen. -->
  {#if screen === "editor" || screen === "review" || screen === "validation"}
  <button
    class="sync-status"
    class:enabled={$navigationStatus.enabled}
    on:click={onOpenConnections}
    aria-label={`${$navigationStatus.enabled ? "Sync on" : "Sync off"}${$navigationStatus.paratext.projectMismatch ? " · Paratext project mismatch" : ""}`}
    use:tooltip={$navigationStatus.ownerConflict ? "Sync: another Bridge window owns navigation" : $navigationStatus.paratext.mismatchMessage || `Sync ${$navigationStatus.enabled ? "on" : "off"} · Paratext ${$navigationStatus.paratext.error ? "error" : $navigationStatus.paratext.connected ? "connected" : "disconnected"} · Logos ${$navigationStatus.logos.error ? "error" : $navigationStatus.logos.connected ? "connected" : "disconnected"}`}
    class:sync-error={Boolean($navigationStatus.paratext.error || $navigationStatus.paratext.projectMismatch || $navigationStatus.logos.error || $navigationStatus.ownerConflict)}
  >
    <UiIcon name="sync" />
    <span class="sync-dot" class:connected={$navigationStatus.enabled} aria-hidden="true"></span>
  </button>
  {/if}
  {#if screen === "editor" && onExport}
  <button class="btn ghost settings-icon" aria-label="Export project" use:tooltip={"Export project"} disabled={exportDisabled} on:click={onExport}><UiIcon name="export" /></button>
  {/if}
  <!-- On every screen, the editor included (2026-11-13). -->
  <button class="btn ghost settings-icon" aria-label="Settings" use:tooltip={"Settings"} on:click={onOpenSettings}><UiIcon name="settings" /></button>
  {#if desktop}
    <div class="window-controls" role="group" aria-label="Window controls">
      <button aria-label="Minimize window" use:tooltip={"Minimize"} on:click={() => windowAction("minimize")}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10"/></svg></button>
      <button aria-label={maximized ? "Restore window" : "Maximize window"} use:tooltip={maximized ? "Restore" : "Maximize"} on:click={() => windowAction("toggleMaximize")}><svg viewBox="0 0 16 16" aria-hidden="true">{#if maximized}<path d="M5 5V3h8v8h-2M3 5h8v8H3z"/>{:else}<path d="M3 3h10v10H3z"/>{/if}</svg></button>
      <button class="window-close" aria-label="Close window" use:tooltip={"Close"} on:click={() => windowAction("close")}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3 3 10 10M3 13 13 3"/></svg></button>
    </div>
  {/if}
</div>

<style>
  /* 32 px on every screen (was 52, 48 on the home page): the editor needs the
     height more than the bar does. The controls in it are 24-26 px. */
  .topbar { height: 32px; background: var(--surface); border-bottom: 1px solid var(--border); display: flex; align-items: center; padding: 0 12px; gap: 10px; flex-shrink: 0; }
  .brand { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: var(--fs-md); color: var(--text); white-space: nowrap; }
  .mark { display: flex; flex-shrink: 0; filter: drop-shadow(0 1px 2px rgba(47, 111, 237, 0.25)); }
  .version { font-size: var(--fs-3xs); font-weight: 600; color: var(--text-3); }
  .divider { width: 1px; height: 16px; background: var(--border); flex-shrink: 0; }
  .breadcrumb { display: flex; align-items: center; gap: 4px; min-width: 0; flex-shrink: 1; overflow: hidden; }
  .crumb { border: 0; background: transparent; color: var(--text-2); font-size: var(--fs-xs); font-weight: 600; padding: 4px 6px; border-radius: 6px; cursor: pointer; max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .crumb:hover:not(:disabled) { background: var(--surface-2); color: var(--text); }
  .crumb:disabled { cursor: not-allowed; opacity: 0.6; }
  .crumb.current { color: var(--text); cursor: default; }
  .crumb.current:hover { background: transparent; }
  .crumb.script { font-size: var(--fs-3xs); }
  .crumb-sep { color: var(--text-3); font-size: var(--fs-xs); flex-shrink: 0; }
  .crumb-close { display: grid; place-items: center; width: 26px; height: 26px; margin-left: 2px; padding: 0; flex-shrink: 0; border: 0; border-radius: 6px; background: transparent; color: var(--text-3); cursor: pointer; transition: color .15s, background .15s; }
  .crumb-close :global(svg) { width: 15px; height: 15px; }
  .crumb-close:hover:not(:disabled), .crumb-close:focus-visible { background: var(--danger-bg); color: var(--danger); }
  .crumb-close:disabled { opacity: .5; cursor: not-allowed; }
  .project-role { padding: 2px 8px; border-radius: 999px; border: 1px solid var(--border-strong); background: var(--surface-2); color: var(--text-2); font-size: var(--fs-2xs); font-weight: 650; white-space: nowrap; flex-shrink: 0; }
  .grow { flex: 1; }
  .sync-status { display: inline-flex; align-items: center; gap: 4px; height: var(--control-h); box-sizing: border-box; padding: 0 8px; border: 1px solid var(--border); border-radius: 6px; background: transparent; color: var(--text-2); font: inherit; font-size: var(--fs-xs); font-weight: 600; line-height: 1; cursor: pointer; flex-shrink: 0; }
  .sync-status:hover { background: var(--surface-2); }
  .sync-status span { display: inline-grid; place-items: center; width: 16px; height: 16px; border-radius: 50%; background: var(--border-strong); color: var(--surface); font-size: var(--fs-3xs); }
  .sync-status span.connected { background: var(--success); }
  /* #377: one control height. The height is the token, not the padding, so
     the three buttons measure the same as Sync, the selects and ‹ › beside
     them; `font: inherit` stops the browser's default button font setting a
     different line box. */
  .btn { height: var(--control-h); box-sizing: border-box; display: inline-flex; align-items: center; font: inherit; font-size: var(--fs-sm); font-weight: 600; line-height: 1; padding: 0 12px; border-radius: 6px; border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); cursor: pointer; flex-shrink: 0; }
  .btn.ghost { background: transparent; border-color: var(--border); }
  .sync-status, .btn.settings-icon { position: relative; display: grid; place-items: center; width: 26px; height: 26px; padding: 0; border: 0; border-radius: 6px; background: transparent; transition: color .15s, background .15s; }
  .sync-status:hover, .btn.settings-icon:hover, .sync-status:focus-visible, .btn.settings-icon:focus-visible { color: var(--accent); background: var(--accent-bg); }
  .btn.settings-icon:disabled { opacity: .5; cursor: not-allowed; }
  .sync-status.sync-error:hover { color: var(--danger); background: var(--danger-bg); }
  @media (prefers-reduced-motion: reduce) {
    .sync-status, .btn.settings-icon { transition: none; }
  }
  .sync-status :global(svg), .btn.settings-icon :global(svg) { width: 16px; height: 16px; }
  .crumb { padding-top: 2px; padding-bottom: 2px; }
  .crumb-close { width: 22px; height: 22px; }
  .sync-status .sync-dot { position: absolute; right: 2px; bottom: 2px; width: 5px; height: 5px; border: 2px solid var(--surface); }
  .sync-status.enabled { color: var(--accent); }
  .sync-status.sync-error { color: var(--danger); }
  .sync-status.sync-error .sync-dot { background: var(--danger); }
  @media (max-width: 900px) {
    .crumb { max-width: 130px; }
  }
  .topbar { min-width: 0; }
  /* The editor's frame (2026-11-13): the bar has the window's background and
     no line under it; the rail and the work area below are the boxes. */
  .editor-bar { background: var(--bg); border-bottom-color: transparent; }
  .desktop-bar { padding-right: 0; user-select: none; }
  .grow { align-self: stretch; min-width: 16px; }
  .home-bar .btn, .home-bar .sync-status { font-size: var(--fs-2xs); }
  .window-controls { display: flex; align-self: stretch; margin-left: 2px; flex-shrink: 0; }
  .window-controls button { display: grid; place-items: center; width: 34px; border: 0; padding: 0; background: transparent; color: var(--text); cursor: pointer; }
  /* The hover is the Settings icon's: a 26 px rounded square in the accent
     colours (danger for Close), drawn on the glyph. The button itself keeps
     the bar's full height, so the window's top-right corner still closes. */
  .window-controls svg { box-sizing: content-box; width: 13px; height: 13px; padding: 6.5px; border-radius: 6px; fill: none; stroke: currentColor; stroke-width: 1.2; transition: color .15s, background .15s; }
  .window-controls button:hover svg, .window-controls button:focus-visible svg { color: var(--accent); background: var(--accent-bg); }
  .window-controls .window-close:hover svg, .window-controls .window-close:focus-visible svg { color: var(--danger); background: var(--danger-bg); }
  @media (prefers-reduced-motion: reduce) {
    .window-controls svg { transition: none; }
  }
  .topbar button:focus-visible { outline: 2px solid var(--accent); outline-offset: -3px; }
  /* A narrow or split-screen window: the bar stays one 40 px row. The version
     goes first, then the word "Bridge" (the mark stays), and the menus and
     window buttons tighten, so the project's name keeps some room. */
  @media (max-width: 900px) {
    .version { display: none; }
  }
  @media (max-width: 760px) {
    .topbar { padding-left: 8px; gap: 6px; }
    .brand-name { display: none; }
    .grow { min-width: 4px; }
    .editor-crumbs .crumb { padding-left: 4px; padding-right: 4px; }
    .project-role { display: none; }
    .window-controls { margin-left: 0; }
    .window-controls button { width: 32px; }
  }
</style>
