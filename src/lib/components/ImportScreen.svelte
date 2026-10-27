<script context="module" lang="ts">
  // #301: App.svelte keeps the last drop's path and sequence after it has been
  // handled, and closing a book mounts a fresh ImportScreen with those same
  // props. A per-instance counter started at 0 treated that old drop as new:
  // every return to Projects reopened the last dropped file's review, and a
  // drop made while a book was open showed the previous file (the new one
  // arrived while the stale inspect was loading and was refused). The handled
  // sequence lives here, once per app, so each drop is inspected exactly once.
  let lastHandledDropSequence = 0;

  /** Tests mount the screen afresh with dropSequence 1 each time. */
  export function forgetHandledDrops(): void {
    lastHandledDropSequence = 0;
  }
</script>

<script lang="ts">
  import { onDestroy, onMount, tick } from "svelte";
  import UiIcon from "./UiIcon.svelte";
  import DuplicateImportDialog, { type RelatedImportProject } from "./DuplicateImportDialog.svelte";
  import { tooltip } from "../tooltip";
  import { iso6393 } from "iso-639-3";
  import { bridge } from "../api/bridgeClient";
  import { perfAbort, perfBegin, perfResponded } from "../perf";
  import { clearPrepare, trackPrepare } from "../openProgress";
  import { project } from "../stores";
  import type {
    DuplicateAssessment, DuplicateMatch, ImportJobSnapshot, ImportMetadata, ImportPreview, RegisteredProject,
  } from "../types/finding";

  const IMPORT_TERMINAL = new Set<ImportJobSnapshot["state"]>(["succeeded", "failed", "cancelled"]);
  const IMPORT_POLL_MS = 250;

  export let onOpened: () => void;
  export let droppedPath = "";
  export let dropSequence = 0;

  let projects: RegisteredProject[] = [];
  let error: string | null = null;
  let loading = false;
  // True until the first project.list response comes back. Distinct from
  // `loading` (which gates the import/open action buttons) because an
  // empty `projects` array is ambiguous on its own -- it means either
  // "genuinely no projects yet" or "still waiting on the very first
  // engine round trip", and those need different copy. The round trip
  // includes the sidecar's own cold start, which for the frozen
  // PyInstaller build can itself take tens of seconds (onefile
  // re-extracts its whole bundle to a fresh temp dir on every launch --
  // see the "slowEngineStart" escalation below), not just the registry
  // scan.
  let projectsLoading = true;
  // The background import (#231). The screen stays usable while it runs:
  // the banner at the top shows the phase, the book and Cancel, and when
  // the job succeeds the primary book is opened from here.
  let importJob: ImportJobSnapshot | null = null;
  let importNotice = "";
  let importGeneration = 0;
  let importPollTimer: ReturnType<typeof setTimeout> | undefined;
  let slowEngineStart = false;
  let slowEngineStartTimer: ReturnType<typeof setTimeout> | undefined;
  let preview: ImportPreview | null = null;
  let selectedBookIds: string[] = [];
  let duplicateDialogOpen = false;
  let approvedDuplicateKey = "";
  let languageInput: HTMLInputElement | undefined;
  let projectNameInput: HTMLInputElement | undefined;
  let languageQuery = "";
  let showLanguages = false;
  let metadata: ImportMetadata = {
    languageId: "", languageName: "", languageDirection: "ltr",
    projectName: "", bibleName: "",
  };

  onMount(() => { void loadProjects(); });
  onDestroy(() => { importGeneration += 1; clearTimeout(importPollTimer); });

  $: importing = importJob !== null && !IMPORT_TERMINAL.has(importJob.state);

  $: if (dropSequence > lastHandledDropSequence && droppedPath) {
    lastHandledDropSequence = dropSequence;
    void inspect(droppedPath);
  }

  const languages = iso6393
    .filter((language) => language.type !== "special")
    .sort((a, b) => a.name.localeCompare(b.name));

  $: normalizedLanguageQuery = languageQuery.trim().toLocaleLowerCase();
  $: languageMatches = normalizedLanguageQuery
    ? languages.filter((language) =>
        language.name.toLocaleLowerCase().includes(normalizedLanguageQuery) ||
        language.iso6393.toLocaleLowerCase().startsWith(normalizedLanguageQuery) ||
        (language.iso6391 ?? "").toLocaleLowerCase().startsWith(normalizedLanguageQuery),
      ).slice(0, 40)
    : languages.slice(0, 40);
  $: allBooksSelected = Boolean(preview?.books.length && selectedBookIds.length === preview.books.length);
  $: canImport = Boolean(preview && selectedBookIds.length > 0 && metadata.languageId && metadata.languageName && metadata.projectName.trim() && metadata.bibleName.trim());
  $: matchedGroups = groupDuplicateMatches(preview?.duplicates.matches ?? [], projects);
  $: importFieldsMissing = [
    !metadata.languageId || !metadata.languageName ? "language" : "",
    !metadata.projectName.trim() ? "project name" : "",
    !metadata.bibleName.trim() ? "Bible / translation name" : "",
  ].filter(Boolean);
  let confirmingId = "";
  // #238: the list's management. Archived rows stay behind a filter; a
  // rename is a display name in the registry, never the folder.
  let showArchived = false;
  let projectSearch = "";
  let renamingId = "";
  let renameDraft = "";
  $: activeProjects = projects.filter((item) => !item.archivedAt);
  $: archivedProjects = projects.filter((item) => Boolean(item.archivedAt));
  $: visibleProjects = showArchived ? [...activeProjects, ...archivedProjects] : activeProjects;
  $: projectSearchTerms = projectSearch.trim().normalize("NFKC").toLocaleLowerCase().split(/\s+/).filter(Boolean);
  $: filteredProjects = visibleProjects.filter((item) => {
    const searchable = [displayName(item), item.projectName, item.bookName, item.bookId,
      item.bibleName, item.targetLanguage, item.targetLanguageId].filter(Boolean).join(" ").normalize("NFKC").toLocaleLowerCase();
    return projectSearchTerms.every((term) => searchable.includes(term));
  });

  function displayName(item: RegisteredProject): string {
    return item.displayName || item.projectName || item.bookName || "Unnamed project";
  }

  function startRename(item: RegisteredProject) {
    renamingId = item.projectId;
    renameDraft = displayName(item);
  }

  async function commitRename(item: RegisteredProject) {
    const name = renameDraft.trim();
    renamingId = "";
    if (!name || name === displayName(item)) return;
    loading = true;
    error = null;
    try {
      await bridge.renameProject(item.projectId, name);
      await loadProjects();
    } catch (value) {
      error = message(value);
    } finally {
      loading = false;
    }
  }

  async function setArchived(item: RegisteredProject, archived: boolean) {
    loading = true;
    error = null;
    try {
      if (archived) await bridge.archiveProject(item.projectId);
      else await bridge.unarchiveProject(item.projectId);
      await loadProjects();
    } catch (value) {
      error = message(value);
    } finally {
      loading = false;
    }
  }

  function lastOpened(item: RegisteredProject): string {
    if (!item.lastOpenedAt) return "never opened";
    const when = new Date(item.lastOpenedAt);
    const stamp = Number.isNaN(when.getTime()) ? item.lastOpenedAt : when.toLocaleString();
    return item.lastOpenedByName ? `opened ${stamp} by ${item.lastOpenedByName}` : `opened ${stamp}`;
  }

  function progressLine(item: RegisteredProject): string {
    const p = item.progress;
    if (!p) return "no progress recorded yet";
    const parts = [`checked ${p.checkedChapterCount}/${p.chapterCount} ch`, `reviewed ${p.reviewedVerseCount}/${p.verseCount}`];
    if ((p.alignedKnownVerseCount ?? 0) > 0) parts.push(`aligned ${p.alignedVerseCount ?? 0}/${p.alignedKnownVerseCount}`);
    if ((p.languageQaCheckedVerseCount ?? 0) > 0) parts.push(`LQA clean ${p.languageQaCleanVerseCount ?? 0}/${p.languageQaCheckedVerseCount}`);
    return parts.join(" · ");
  }

  function message(value: unknown): string {
    return value instanceof Error ? value.message : String(value);
  }

  function groupDuplicateMatches(matches: DuplicateMatch[], registered: RegisteredProject[]): RelatedImportProject[] {
    const groups = new Map<string, {
      id: string; label: string; path: string; projectId: string; missing: boolean;
      exactBooks: Set<string>; possibleBooks: Set<string>;
    }>();
    for (const match of matches) {
      let group = groups.get(match.groupId);
      if (!group) {
        const entry = registered.find((item) => !item.conflict && (item.projectId === match.projectId || (match.collectionId && item.collectionId === match.collectionId)));
        group = {
          id: match.groupId,
          label: entry ? displayName(entry) : match.projectName || match.bibleName || match.bookName || "Existing project",
          path: match.path, projectId: match.projectId, missing: match.missing,
          exactBooks: new Set<string>(), possibleBooks: new Set<string>(),
        };
        groups.set(match.groupId, group);
      }
      // A collection may have both missing and available members. Open an
      // available matching member, never the missing representative.
      if (group.missing && !match.missing) {
        group.path = match.path;
        group.projectId = match.projectId;
      }
      group.missing = group.missing && match.missing;
      (match.match === "exact" ? group.exactBooks : group.possibleBooks).add(match.bookId.toUpperCase());
    }
    return [...groups.values()].map((group) => ({ ...group, exactBooks: [...group.exactBooks], possibleBooks: [...group.possibleBooks] }));
  }

  function duplicateReviewKey(assessment: DuplicateAssessment, selection: string[]) {
    // Consent applies only to these books and this set of related projects.
    return JSON.stringify([
      preview?.sourcePath, [...selection].sort(), assessment.classification,
      Object.entries(assessment.sourceFingerprints).sort(),
      assessment.matches.map((match) => [match.groupId, match.projectId, match.path, match.bookId, match.match, match.missing].join("|")).sort(),
    ]);
  }

  async function chooseNewProject() {
    if (!preview) return;
    approvedDuplicateKey = duplicateReviewKey(preview.duplicates, selectedBookIds);
    duplicateDialogOpen = false;
    error = null;
    await tick();
    (metadata.languageId && metadata.languageName ? projectNameInput : languageInput)?.focus();
  }

  async function openRelatedProject(item: RelatedImportProject) {
    if (item.missing || loading) return;
    if (await openPath(item.path, item.projectId)) duplicateDialogOpen = false;
  }

  async function loadProjects() {
    projectsLoading = true;
    slowEngineStart = false;
    slowEngineStartTimer = setTimeout(() => { slowEngineStart = true; }, 5000);
    try {
      projects = (await bridge.listProjects()).projects;
    } catch (value) {
      error = message(value);
    } finally {
      clearTimeout(slowEngineStartTimer);
      projectsLoading = false;
    }
  }

  async function openPath(path: string, projectId?: string) {
    // #232 (Tier B): begins at the click; App.svelte ends it when the
    // dashboard has painted. The disabled buttons are the first response.
    const name = path.split(/[\\/]/).pop() ?? "";
    perfBegin("project.open", name);
    const listed = projects.find((item) => item.path === path);
    loading = true;
    error = null;
    perfResponded("project.open");
    try {
      // #400: a lazy book's prepare shows in App's "Opening …" strip.
      const info = await bridge.openProject(path, projectId, trackPrepare(listed ? displayName(listed) : name));
      project.set(info);
      onOpened();
      return true;
    } catch (value) {
      perfAbort("project.open");
      error = message(value);
      await loadProjects();
      return false;
    } finally {
      loading = false;
      clearPrepare();
    }
  }

  async function openExisting() {
    const path = await bridge.pickProjectFolder();
    if (path) await openPath(path);
  }

  async function locate(item: RegisteredProject) {
    const path = await bridge.pickProjectFolder();
    if (path) await openPath(path, item.projectId);
  }

  async function forget(item: RegisteredProject) {
    loading = true;
    error = null;
    try {
      await bridge.forgetProject(item.projectId);
      await loadProjects();
    } catch (value) {
      error = message(value);
    } finally {
      loading = false;
    }
  }

  async function deleteProject(item: RegisteredProject) {
    loading = true;
    error = null;
    try {
      await bridge.deleteProject(item.projectId);
      confirmingId = "";
      await loadProjects();
    } catch (value) {
      error = message(value);
    } finally {
      loading = false;
    }
  }

  async function chooseFile() {
    const path = await bridge.pickImportFile();
    if (path) await inspect(path);
  }

  async function chooseFolder() {
    const path = await bridge.pickProjectFolder();
    if (path) await inspect(path);
  }

  async function inspect(path: string) {
    if (duplicateDialogOpen) {
      error = "Choose an existing project or create a new project before importing another source.";
      return;
    }
    if (loading || importing) {
      error = "Please wait for the current operation to finish, then drop the source again.";
      return;
    }
    loading = true;
    error = null;
    preview = null;
    approvedDuplicateKey = "";
    duplicateDialogOpen = false;
    showLanguages = false;
    try {
      preview = await bridge.inspectImport(path);
      selectedBookIds = preview.books.map((book) => book.bookId);
      metadata = {
        languageId: preview.metadata.languageId ?? "",
        languageName: preview.metadata.languageName ?? "",
        languageDirection: preview.metadata.languageDirection || "ltr",
        projectName: preview.metadata.projectName ?? "",
        bibleName: preview.metadata.bibleName ?? "",
      };
      // A detected code with no name (a Paratext LanguageIsoCode, #308) is
      // named from the same table the search uses. Paratext's own <Language>
      // is the name only when the code is not in that table (#355).
      const detected = !metadata.languageName && metadata.languageId
        ? languages.find((language) => language.iso6393 === metadata.languageId)
        : undefined;
      if (detected) metadata = { ...metadata, languageName: detected.name };
      else if (!metadata.languageName && preview.paratextLanguageName) {
        metadata = { ...metadata, languageName: preview.paratextLanguageName };
      }
      languageQuery = metadata.languageName || metadata.languageId;
      duplicateDialogOpen = preview.duplicates.classification !== "new";
    } catch (value) {
      error = message(value);
    } finally {
      loading = false;
    }
  }

  function closeLanguageMenu(event: FocusEvent) {
    const container = event.currentTarget as HTMLElement;
    if (!(event.relatedTarget instanceof Node) || !container.contains(event.relatedTarget)) showLanguages = false;
  }

  async function handleLanguageKey(event: KeyboardEvent) {
    if (event.key === "Escape") showLanguages = false;
    if (event.key === "ArrowDown") {
      const field = languageInput?.parentElement;
      event.preventDefault();
      showLanguages = true;
      await tick();
      field?.querySelector<HTMLButtonElement>(".language-menu button")?.focus();
    }
  }

  function selectLanguage(language: (typeof iso6393)[number]) {
    metadata = { ...metadata, languageId: language.iso6393, languageName: language.name };
    languageQuery = language.name;
    showLanguages = false;
  }

  async function runImport() {
    if (!preview || !canImport || loading || importing || duplicateDialogOpen) return;
    loading = true;
    error = null;
    try {
      const selection = [...selectedBookIds];
      const importMetadata = { ...metadata };
      const partialSelection = selection.length !== preview.books.length;
      const refreshed = partialSelection
        ? await bridge.inspectImport(preview.sourcePath, importMetadata, selection)
        : await bridge.inspectImport(preview.sourcePath, importMetadata);
      if (partialSelection && refreshed.books.map((book) => book.bookId).sort().join(",") !== selection.slice().sort().join(",")) {
        throw new Error("Book selection requires the updated engine. Rebuild the engine and restart Bridge, then try again.");
      }
      preview = { ...preview, duplicates: refreshed.duplicates };
      const reviewKey = duplicateReviewKey(refreshed.duplicates, selection);
      if (refreshed.duplicates.classification !== "new" && approvedDuplicateKey !== reviewKey) {
        duplicateDialogOpen = true;
        showLanguages = false;
        return;
      }
      const allowDuplicate = refreshed.duplicates.classification !== "new" && approvedDuplicateKey === reviewKey;
      importNotice = "";
      let snapshot: ImportJobSnapshot;
      try {
        snapshot = partialSelection
          ? await bridge.importStart(preview.sourcePath, importMetadata, allowDuplicate, selection)
          : await bridge.importStart(preview.sourcePath, importMetadata, allowDuplicate);
      } catch (value) {
        // An import is already running (a double click): follow it instead.
        if (!/already running/i.test(message(value))) throw value;
        snapshot = await bridge.importStatus("");
      }
      importJob = snapshot;
      void pollImport(snapshot.jobId, ++importGeneration);
    } catch (value) {
      error = message(value);
    } finally {
      loading = false;
    }
  }

  async function pollImport(jobId: string, generation: number) {
    try {
      while (generation === importGeneration) {
        const snapshot = await bridge.importStatus(jobId);
        if (generation !== importGeneration) return;
        importJob = snapshot;
        if (IMPORT_TERMINAL.has(snapshot.state)) {
          if (snapshot.state === "succeeded" && snapshot.result) {
            const primary = snapshot.result.projects[0];
            // #400: the banner follows the open's prepare, not the import's last snapshot.
            const info = await bridge.openProject(snapshot.result.primaryProjectPath, primary?.projectId,
              (prepare) => { if (generation === importGeneration) importJob = prepare; });
            if (generation !== importGeneration) return;
            // project.open does not echo the collection's siblings; only the
            // import knows them, and the book switcher reads them from here.
            info.importedProjects = snapshot.result.projects;
            importJob = null;
            project.set(info);
            onOpened();
          } else if (snapshot.state === "cancelled") {
            importJob = null;
            importNotice = "Import cancelled. Nothing was written.";
          } else {
            importJob = null;
            error = snapshot.error || "The import failed.";
          }
          return;
        }
        await new Promise<void>((resolve) => { importPollTimer = setTimeout(resolve, IMPORT_POLL_MS); });
      }
    } catch (value) {
      if (generation !== importGeneration) return;
      importJob = null;
      error = message(value);
    }
  }

  async function cancelImport() {
    if (!importJob) return;
    try {
      importJob = await bridge.importCancel(importJob.jobId);
    } catch (value) {
      error = message(value);
    }
  }

  function importLabel(job: ImportJobSnapshot): string {
    const lead = job.state === "cancelling" ? "Cancelling" : job.phaseLabel;
    const book = job.totalBooks > 1 && job.currentBook
      ? ` (book ${Math.min(job.completedBooks + 1, job.totalBooks)} of ${job.totalBooks})`
      : "";
    const chapter = job.chapter && job.chapterCount ? `, chapter ${job.chapter} of ${job.chapterCount}` : "";
    return `${lead}${book}${chapter}`;
  }

  function reset() {
    preview = null;
    duplicateDialogOpen = false;
    approvedDuplicateKey = "";
    error = null;
    languageQuery = "";
    selectedBookIds = [];
    showLanguages = false;
    void loadProjects();
  }
</script>

<div class="screen" class:project-home={preview === null} class:import-review={preview !== null}>
  {#if importJob}
    <div class="import-banner" role="status" aria-label="Import progress" aria-live="polite">
      <span class="import-label" title={importJob.sourcePath}>
        Importing: {importLabel(importJob)} — {importJob.percent}%
      </span>
      <div class="track"><div class="fill" style="width:{importJob.percent}%"></div></div>
      <button class="small-button" on:click={cancelImport} disabled={importJob.state === "cancelling"}>
        {importJob.state === "cancelling" ? "Cancelling…" : "Cancel"}
      </button>
    </div>
  {/if}
  {#if preview === null}
    <div class="header">
      <div class="page-title"><h1>Projects</h1><span class="project-count">{activeProjects.length}</span></div>
    </div>

    <div class="footer">
      <div class="section-heading"><h2>Add a project</h2></div>
      <div class="choice-grid">
        <button class="choice" use:tooltip={"Import a file: USFM, SFM, TXT, TCORE, TSTUDIO or ZIP"} on:click={chooseFile} disabled={loading}>
          <span class="choice-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5M12 17v-6m-3 3 3-3 3 3"/></svg></span>
          <span class="choice-copy"><span class="choice-title">Import a file</span><span>USFM, SFM, TXT, TCORE, TSTUDIO or ZIP</span></span>
          <span class="choice-arrow" aria-hidden="true">→</span>
        </button>
        <button class="choice" use:tooltip={"Import a folder: multi-book USFM, Paratext or translationCore"} on:click={chooseFolder} disabled={loading}>
          <span class="choice-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3 7V5a1 1 0 0 1 1-1h5l2 3h9a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7Z"/><path d="M3 10h18"/></svg></span>
          <span class="choice-copy"><span class="choice-title">Import a folder</span><span>Multi-book USFM, Paratext or translationCore</span></span>
          <span class="choice-arrow" aria-hidden="true">→</span>
        </button>
      </div>

      <p class="drop-hint">Or drop a file or folder anywhere in this window.</p>
      <button class="link-button" on:click={openExisting} disabled={loading} title="Open a Bridge or translationCore project in its current location, without copying it">Open an existing project</button>
      {#if loading}<p class="working">Reading, validating, or opening the selected project…</p>{/if}
      {#if importNotice}<p class="working">{importNotice}</p>{/if}
      {#if error && !duplicateDialogOpen}<p class="error" role="alert">{error}</p>{/if}
    </div>

    <div class="list-area">
      {#if projects.length > 0}
      <div class="project-toolbar">
        <div class="project-search">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg>
          <input type="search" aria-label="Search projects" placeholder="Search projects by name, book or language" bind:value={projectSearch} />
          {#if projectSearch}
            <button class="clear-search" aria-label="Clear project search" on:click={() => (projectSearch = "")}>Clear</button>
          {/if}
        </div>
        {#if archivedProjects.length > 0}
          <label class="archived-filter">
            <input type="checkbox" bind:checked={showArchived} />
            Show archived ({archivedProjects.length})
          </label>
        {/if}
        {#if projectSearchTerms.length > 0 && !projectsLoading}
          <span class="search-count" role="status">{filteredProjects.length} of {visibleProjects.length} projects</span>
        {/if}
      </div>
      {/if}
      <!-- Keep the scroll region focusable for keyboard scrolling. -->
      <!-- svelte-ignore a11y-no-noninteractive-tabindex -->
      <div class="project-results" role="region" aria-label="Project list" tabindex="0">
      {#if projectsLoading}
        <p class="empty">
          {slowEngineStart
            ? "Still starting the translation engine — first launch can take up to a minute…"
            : "Scanning for projects…"}
        </p>
      {:else if projects.length > 0}
        <section class="projects" aria-label="Known projects">
          {#each filteredProjects as item (item.conflict ? `conflict:${item.path}` : item.projectId)}
            {#if item.conflict}
              <!-- #309: a managed folder whose identity the registry refused. It
                   has no projectId of its own, so it offers no actions. -->
              <article class="project-row conflict">
                <div class="book-badge">{item.bookId?.toUpperCase() || "?"}</div>
                <div class="project-copy">
                  <strong>{displayName(item)}</strong>
                  <span>{(item.bookCount ?? 1) > 1 ? `${item.bookCount} books` : item.bookName}{item.bibleName ? ` · ${item.bibleName}` : ""}</span>
                  <span class="conflict-message" role="alert">{item.conflict.message}</span>
                  {#if item.conflict.registeredPath}<small title={item.conflict.registeredPath}>Registered copy: {item.conflict.registeredPath}</small>{/if}
                  <small title={item.path}>This copy: {item.path}</small>
                </div>
              </article>
            {:else}
            <article class:missing={item.missing} class:archived={Boolean(item.archivedAt)} class="project-row">
              <div class="book-badge">{item.bookId?.toUpperCase() || "?"}</div>
              <div class="project-copy">
                {#if renamingId === item.projectId}
                  <input class="rename-input" aria-label="Project name" bind:value={renameDraft}
                    on:keydown={(event) => { if (event.key === "Enter") void commitRename(item); if (event.key === "Escape") renamingId = ""; }}
                    on:blur={() => void commitRename(item)} />
                {:else}
                  <strong>{displayName(item)}{item.archivedAt ? " (archived)" : ""}</strong>
                {/if}
                <span>{item.collectionId ? `${item.bookCount ?? 1}-book collection` : item.bookName}{item.bibleName ? ` · ${item.bibleName}` : ""}{item.targetLanguage ? ` · ${item.targetLanguage}` : ""}</span>
                {#if item.missing}<small class="missing-label">Project folder is missing</small>{/if}
              </div>
              <div class="project-actions" role="group" aria-label={`Actions for ${displayName(item)}`}>
              {#if item.missing}
                <button class="small-button icon-action" on:click={() => locate(item)} disabled={loading}
                  title={`Locate ${displayName(item)}`} aria-label={`Locate ${displayName(item)}`}>📂︎</button>
                <button class="small-button icon-action danger" on:click={() => forget(item)} disabled={loading}
                  title={`Forget ${displayName(item)}`} aria-label={`Forget ${displayName(item)}`}>✕</button>
              {:else if confirmingId === item.projectId}
                <span class="confirm-copy">Delete permanently?</span>
                <button class="small-button danger" on:click={() => deleteProject(item)} disabled={loading}>Confirm</button>
                <button class="small-button" on:click={() => (confirmingId = "")} disabled={loading}>Cancel</button>
              {:else}
                <button class="small-button action-icon primary" aria-label={`Open ${displayName(item)}`} use:tooltip={`Open ${displayName(item)}`} on:click={() => openPath(item.path, item.projectId)} disabled={loading}><UiIcon name="open" /></button>
                <button class="small-button action-icon" aria-label={`Rename ${displayName(item)}`} use:tooltip={`Rename ${displayName(item)}`} on:click={() => startRename(item)} disabled={loading}><UiIcon name="rename" /></button>
                {#if item.archivedAt}
                  <button class="small-button action-icon" aria-label={`Unarchive ${displayName(item)}`} use:tooltip={`Unarchive ${displayName(item)}`} on:click={() => setArchived(item, false)} disabled={loading}><UiIcon name="unarchive" /></button>
                {:else}
                  <button class="small-button action-icon" aria-label={`Archive ${displayName(item)}`} use:tooltip={`Archive ${displayName(item)}`} on:click={() => setArchived(item, true)} disabled={loading}><UiIcon name="archive" /></button>
                {/if}
                {#if item.managed}
                  <button class="small-button action-icon danger" aria-label={`Delete ${displayName(item)}`} use:tooltip={`Delete ${displayName(item)}`} on:click={() => (confirmingId = item.projectId)} disabled={loading}><UiIcon name="delete" /></button>
                {/if}
              {/if}
              </div>
              <details class="project-details">
                <summary>Project details</summary>
                <div class="details-body">
                  <div><span class="detail-label">Progress</span><span class="progress-line">{progressLine(item)}</span></div>
                  <div><span class="detail-label">Last activity</span><span>{lastOpened(item)}</span></div>
                  <div><span class="detail-label">Location</span><span>{item.path}</span></div>
                </div>
              </details>
            </article>
            {/if}
          {/each}
        </section>
        {#if filteredProjects.length === 0}
          <p class="empty">{projectSearchTerms.length > 0 ? "No projects match your search. Try another name, book or language." : "All projects are archived. Turn on Show archived to see them."}</p>
        {/if}
      {:else}
        <p class="empty">No projects are registered yet. Existing app-managed projects will appear here automatically.</p>
      {/if}
      </div>
    </div>

  {:else}
    <div class="header">
      <div class="header-row">
        <div class="review-heading">
          <h1>Confirm project details</h1>
          <p class="source" title={preview.sourcePath}>{preview.sourcePath}</p>
          {#if preview.paratext}
            <p class="paratext-link" data-testid="paratext-link">
              Paratext project <strong>{preview.paratext.name}</strong>{preview.paratext.fullName ? ` (${preview.paratext.fullName})` : ""}
              · Guid <code>{preview.paratext.guid}</code>
            </p>
          {/if}
        </div>
        <button class="back action-icon" aria-label="Back to projects" use:tooltip={"Back to projects"} on:click={reset} disabled={loading}><UiIcon name="back" /></button>
        <button class="action-icon review-close" aria-label="Close import review" use:tooltip={"Close and return to projects"} on:click={reset} disabled={loading}><UiIcon name="close" /></button>
      </div>
    </div>

    <div class="list-area">
      <div class="content-grid">
        <section class="summary">
          <div class="books-card-content">
          <div class="books-heading">
            <h2>Books</h2>
            <div class="books-controls">
              <label class="bulk-selection">
                <input type="checkbox" checked={allBooksSelected} disabled={loading || importing || preview.books.length === 0}
                  on:change={(event) => (selectedBookIds = event.currentTarget.checked && preview ? preview.books.map((book) => book.bookId) : [])} />
                <span>{allBooksSelected ? "Unselect all" : "Select all"}</span>
              </label>
              <span class="selection-count" aria-live="polite">{selectedBookIds.length} / {preview.books.length} selected</span>
            </div>
          </div>
          <div class="book-list">
            {#each preview.books as book}
              <label class="book-row" class:book-unselected={!selectedBookIds.includes(book.bookId)}>
                <input type="checkbox" value={book.bookId} bind:group={selectedBookIds} aria-label={`Import ${book.bookName || book.bookId}`} disabled={loading || importing} />
                <span class="book-id">{book.bookId.toUpperCase()}</span>
                <span class="book-name" use:tooltip={book.bookName}>{book.bookName}</span>
                <span class="book-meta"><span class="book-separator" aria-hidden="true">·</span>{book.verseCount === null ? "Existing project" : `${book.verseCount} verses`}{book.hasAlignments ? " · aligned" : ""}</span>
              </label>
            {/each}
          </div>
          {#if preview.warnings.some((warning) => !/^\d+ books will be imported/.test(warning))}
            <details class="import-notes"><summary>Source notes</summary>
              {#each preview.warnings.filter((warning) => !/^\d+ books will be imported/.test(warning)) as warning}<p class="warning">{warning}</p>{/each}
            </details>
          {/if}
          <p class="note">Selected books are copied. Source files stay unchanged.</p>
          </div>
        </section>

        <section class="form">
          <div class="form-heading"><h2>Project details</h2><span>New project</span></div>
          <div class="language-control" on:focusout={closeLanguageMenu}>
            <div class="field-heading"><label for="import-language">Language</label>{#if metadata.languageId}<output class="language-code" aria-label="Language code">{metadata.languageId}</output>{/if}</div>
            <div class="language-field">
              <input id="import-language" bind:this={languageInput} disabled={loading || importing} value={languageQuery} placeholder="Search language or code" autocomplete="off" aria-describedby="import-language-help"
                on:keydown={handleLanguageKey}
                on:input={(event) => { languageQuery = event.currentTarget.value; metadata = { ...metadata, languageId: "", languageName: "" }; showLanguages = true; }}
                on:click={() => (showLanguages = true)} />
              {#if showLanguages}
                <div class="language-menu" role="group" aria-label="Language suggestions">
                  {#each languageMatches as language}
                    <button type="button" on:mousedown|preventDefault on:click={() => selectLanguage(language)}><span>{language.name}</span><code>{language.iso6393}</code></button>
                  {:else}<div class="no-match">No ISO 639-3 language found</div>{/each}
                </div>
              {/if}
            </div>
          </div>

          <p class="field-help" id="import-language-help">{metadata.languageId && metadata.languageName ? "Language for the imported text." : "Search, then select a language from the list."}</p>
          <fieldset class="direction-field">
            <legend>Text direction</legend>
            <div class="direction-options">
              <button type="button" disabled={loading || importing} aria-pressed={metadata.languageDirection === "ltr"} on:click={() => (metadata = { ...metadata, languageDirection: "ltr" })}><span aria-hidden="true">→</span> Left to right {#if metadata.languageDirection === "ltr"}<span aria-hidden="true">✓</span>{/if}</button>
              <button type="button" disabled={loading || importing} aria-pressed={metadata.languageDirection === "rtl"} on:click={() => (metadata = { ...metadata, languageDirection: "rtl" })}><span aria-hidden="true">←</span> Right to left {#if metadata.languageDirection === "rtl"}<span aria-hidden="true">✓</span>{/if}</button>
            </div>
          </fieldset>
          <label><span>Project name</span><input disabled={loading || importing} bind:this={projectNameInput} bind:value={metadata.projectName} placeholder="e.g. Community review" /></label>
          <label><span>Bible / translation name</span><input disabled={loading || importing} bind:value={metadata.bibleName} placeholder="e.g. IRV Malayalam" /></label>

          <div class="import-submit">
            {#if selectedBookIds.length === 0}<p class="required">Select at least one book to import.</p>{:else if importFieldsMissing.length > 0}<p class="required">To import, complete: {importFieldsMissing.join(", ")}.</p>{/if}
            <button class="import-button" on:click={runImport} disabled={loading || importing || !canImport}>
              {importing ? `Importing ${selectedBookIds.length === 1 ? "book" : `${selectedBookIds.length} books`}…` : `Import ${selectedBookIds.length === 1 ? "book" : `${selectedBookIds.length} books`}`}
            </button>
          </div>
        </section>
      </div>

      {#if loading}<p class="working">Checking the source…</p>{/if}
      {#if importNotice}<p class="working">{importNotice}</p>{/if}
      {#if error && !duplicateDialogOpen}<p class="error" role="alert">{error}</p>{/if}
    </div>
  {/if}
</div>

{#if duplicateDialogOpen && preview}
  <DuplicateImportDialog projects={matchedGroups} exact={preview.duplicates.classification === "exactDuplicate"} busy={loading || importing} {error} onOpen={openRelatedProject} onCreate={chooseNewProject} />
{/if}

<style>
  .screen { flex: 1; min-height: 0; min-width: 0; display: flex; flex-direction: column; overflow: auto; background: var(--surface); }
  .import-banner { flex-shrink: 0; display: flex; align-items: center; gap: 12px; padding: 10px 40px; border-bottom: 1px solid var(--border); background: var(--surface-2, var(--surface)); max-width: 900px; width: 100%; margin: 0 auto; box-sizing: border-box; }
  .import-label { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--fs-sm); color: var(--text); }
  .import-banner .track { flex: 1 1 120px; height: 6px; border-radius: 3px; background: var(--border); overflow: hidden; }
  .import-banner .fill { height: 100%; background: var(--accent); transition: width .2s linear; }
  .header { flex-shrink: 0; padding: 28px 40px 18px; border-bottom: 1px solid var(--border); }
  .list-area { flex: 1 0 auto; padding: 20px 40px; }
  .footer { flex-shrink: 0; padding: 16px 40px 24px; border-top: 1px solid var(--border); background: var(--surface); }
  .header, .list-area, .footer { max-width: 900px; width: 100%; margin: 0 auto; box-sizing: border-box; }
  h1 { font-size: var(--fs-4xl); line-height: 1.2; margin: 0; color: var(--text); }
  h2 { font-size: var(--fs-md); margin: 0 0 12px; color: var(--text); }
  .projects { border: 1px solid var(--border); border-radius: 10px; }
  .project-row { flex-wrap: wrap; min-height: 66px; display: flex; align-items: center; gap: 11px; padding: 9px 11px; border-bottom: 1px solid var(--border); }
  .project-row:last-child { border-bottom: 0; }
  .project-row.missing { background: #fff9ed; }
  .project-row.conflict { background: #fff9ed; }
  .conflict-message { color: var(--danger); }
  .book-badge { width: 38px; height: 38px; display: grid; place-items: center; border-radius: 8px; background: var(--accent-bg); color: var(--accent); font-size: var(--fs-2xs); font-weight: 800; flex-shrink: 0; }
  .project-copy { display: flex; flex-direction: column; min-width: 0; flex: 1; gap: 2px; }
  .project-copy strong { font-size: var(--fs-sm); color: var(--text); }
  .project-copy span, .project-copy small { color: var(--text-2); font-size: var(--fs-2xs); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .archived-filter { display: flex; flex-direction: row; align-items: center; gap: 6px; font-size: var(--fs-2xs); color: var(--text-2); margin: 0 0 8px; }
  .project-row.archived { opacity: .7; }
  .progress-line { font-size: var(--fs-2xs); color: var(--text-2); }
  .rename-input { font: inherit; font-weight: 700; padding: 2px 6px; border: 1px solid var(--accent); border-radius: 4px; background: var(--surface); color: var(--text); width: 100%; box-sizing: border-box; }
  .small-button { height: var(--control-h); box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface); color: var(--text); padding: 0 10px; cursor: pointer; font-size: var(--fs-2xs); flex-shrink: 0; }
  .small-button.primary { border-color: var(--accent); color: var(--accent); }
  .small-button.danger { color: var(--danger); }
  /* #375: a 28x28 glyph button; the glyph is drawn upright and monochrome
     from the UI font, never from an icon font (CLAUDE.md gotcha 9). */
  .small-button.icon-action { width: var(--control-h); padding: 0; font-family: var(--font-ui); font-size: var(--fs-sm); line-height: 1; }
  .small-button.icon-action:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
  .small-button.icon-action.danger:hover:not(:disabled) { border-color: var(--danger); color: var(--danger); }
  .confirm-copy { color: var(--danger); font-size: var(--fs-2xs); font-weight: 650; flex-shrink: 0; }
  .empty { background: var(--surface-2); color: var(--text-2); border-radius: 8px; padding: 14px; font-size: var(--fs-xs); margin: 0 0 18px; }
  .choice-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  button { font: inherit; }
  .choice { min-height: 82px; text-align: left; border: 1px solid var(--border-strong); background: var(--surface); color: var(--text-2); border-radius: 10px; padding: 14px; cursor: pointer; font-size: var(--fs-xs); line-height: 1.45; }
  .choice:hover { border-color: var(--accent); background: var(--accent-bg); }
  .choice-title { display: block; color: var(--text); font-size: var(--fs-md); font-weight: 700; margin-bottom: 5px; }
  .link-button, .back { display: block; border: 0; background: none; color: var(--accent); cursor: pointer; font-size: var(--fs-xs); margin: 15px auto 0; }
  .header-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding-bottom: 18px; border-bottom: 1px solid var(--border); }
  .source { color: var(--text-2); font-size: var(--fs-2xs); margin: 7px 0 0; max-width: 650px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .paratext-link { color: var(--text-2); font-size: var(--fs-2xs); margin: 4px 0 0; max-width: 650px; overflow-wrap: anywhere; }
  .paratext-link code { font-size: var(--fs-2xs); }
  .back { margin: 4px 0 0; white-space: nowrap; }
  .content-grid { display: grid; grid-template-columns: minmax(0, .9fr) minmax(320px, 1.1fr); gap: 30px; padding-top: 20px; }
  .summary { min-width: 0; }
  .book-list { border: 1px solid var(--border); border-radius: 8px; max-height: 225px; overflow: auto; }
  .book-row { display: grid; grid-template-columns: 42px 1fr auto; align-items: center; gap: 8px; min-height: 38px; padding: 0 10px; border-bottom: 1px solid var(--border); font-size: var(--fs-xs); }
  .book-row:last-child { border-bottom: 0; }
  .book-id { color: var(--accent); font-weight: 800; }
  .book-name { color: var(--text); font-weight: 600; }
  .book-meta { color: var(--text-2); font-size: var(--fs-2xs); text-align: right; }
  .warning, .note { border-radius: 7px; padding: 9px 10px; font-size: var(--fs-2xs); line-height: 1.45; margin: 10px 0 0; }
  .warning { background: #fff7e6; color: #8a5a00; }
  .note { background: var(--surface-2); color: var(--text-2); }
  .form { display: flex; flex-direction: column; gap: 13px; }
  label { display: flex; flex-direction: column; gap: 5px; color: var(--text); font-size: var(--fs-xs); font-weight: 650; }
  input { width: 100%; box-sizing: border-box; height: 36px; border: 1px solid var(--border-strong); border-radius: 7px; background: var(--surface); color: var(--text); padding: 0 10px; font-size: var(--fs-sm); outline: none; }
  input:focus { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-bg); }
  .language-field { position: relative; }
  .language-menu { position: absolute; z-index: var(--z-dropdown); left: 0; right: 0; top: 40px; max-height: 215px; overflow: auto; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface); box-shadow: 0 10px 25px rgba(25, 35, 55, .16); }
  .language-menu button { width: 100%; display: flex; justify-content: space-between; align-items: center; border: 0; border-bottom: 1px solid var(--border); background: var(--surface); color: var(--text); padding: 8px 10px; cursor: pointer; font-size: var(--fs-xs); text-align: left; }
  .language-menu button:hover { background: var(--accent-bg); }
  .language-menu code { color: var(--text-2); font-size: var(--fs-2xs); }
  .no-match { color: var(--text-2); font-size: var(--fs-xs); padding: 12px; }
  .import-button { height: 38px; border-radius: 7px; font-size: var(--fs-sm); font-weight: 700; cursor: pointer; }
  .import-button { border: 1px solid var(--accent); background: var(--accent); color: white; }
  button:disabled { opacity: .55; cursor: not-allowed; }
  .required, .working, .error { font-size: var(--fs-2xs); margin: 0; }
  .required, .working { color: var(--text-2); }
  .working { margin-top: 15px; }
  .error { color: var(--danger); margin-top: 13px; line-height: 1.45; }
  .project-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
  .section-heading { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 8px; margin-bottom: 14px; }
  .section-heading h2 { margin: 0; font-size: var(--fs-lg); }
  .choice-icon { display: grid; place-items: center; flex: 0 0 40px; height: 40px; border-radius: 10px; background: var(--accent-bg); color: var(--accent); }
  .choice-icon svg { width: 22px; height: 22px; }
  .choice-copy { flex: 1; min-width: 0; }
  .choice-arrow { color: var(--text-2); font-size: 20px; }
  .page-title { display: flex; align-items: center; gap: 10px; }
  .project-count { display: grid; place-items: center; min-width: 26px; height: 24px; padding: 0 6px; box-sizing: border-box; border: 1px solid var(--border); border-radius: 7px; color: var(--text-2); background: var(--surface); font-size: var(--fs-2xs); }
  .project-details { grid-column: 2 / -1; min-width: 0; color: var(--text-2); font-size: var(--fs-2xs); }
  .project-details summary { width: fit-content; cursor: pointer; padding: 4px 0; border-radius: 4px; user-select: none; }
  .project-details summary:hover { color: var(--accent); }
  .project-details summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
  .details-body { display: grid; gap: 4px; padding-top: 8px; margin-top: 4px; border-top: 1px solid var(--border); }
  .details-body > div { display: grid; grid-template-columns: 100px minmax(0, 1fr); gap: 12px; line-height: 1.4; overflow-wrap: anywhere; }
  .detail-label { font-weight: 600; color: var(--text); }
  .project-copy .missing-label { color: var(--danger); }
  .drop-hint { color: var(--text-2); font-size: var(--fs-2xs); text-align: center; line-height: 1.5; margin: 16px 0 0; }
  button:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
  .small-button:hover:not(:disabled) { background: var(--accent-bg); border-color: var(--accent); }
  .archived-filter input { width: 18px; height: 18px; accent-color: var(--accent); }
  .project-home { background: var(--bg); overflow: hidden; padding-bottom: 0; }
  .project-home .header, .project-home .list-area, .project-home .footer { max-width: 1200px; padding-left: 32px; padding-right: 32px; }
  .project-home .header { padding-top: 28px; padding-bottom: 20px; border: 0; }
  .project-home .list-area { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; padding-top: 0; padding-bottom: 0; }
  .project-results { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior-y: contain; scrollbar-gutter: stable; padding: 3px 4px 20px 3px; }
  .project-results:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; border-radius: 10px; }
  .project-home .footer { border: 0; background: transparent; padding-top: 0; padding-bottom: 24px; }
  .project-toolbar { flex-shrink: 0; display: flex; flex-wrap: wrap; align-items: center; gap: 12px 16px; margin-bottom: 16px; }
  .project-search { display: flex; align-items: center; gap: 8px; flex: 1 1 320px; min-width: 0; padding: 0 12px; border: 1px solid var(--border-strong); border-radius: 9px; background: var(--surface); }
  .project-search:focus-within { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-bg); }
  .project-search svg { width: 18px; height: 18px; flex-shrink: 0; color: var(--text-2); }
  .project-search input { min-width: 0; height: 40px; border: 0; background: transparent; padding: 0; font-size: var(--fs-xs); box-shadow: none; }
  .project-search input::placeholder { color: var(--text-2); opacity: 1; }
  .clear-search { border: 0; border-radius: 4px; background: transparent; color: var(--accent); font-size: var(--fs-2xs); padding: 6px; cursor: pointer; }
  .project-toolbar .archived-filter { margin: 0; flex-shrink: 0; }
  .search-count { font-size: var(--fs-2xs); color: var(--text-2); }
  @media (max-width: 480px) {
    .project-search { flex-basis: 100%; }
    .project-search input { font-size: var(--fs-2xs); }
  }
  .project-home .projects { display: grid; gap: 12px; border: 0; }
  .project-home .project-row { display: grid; grid-template-columns: 40px minmax(0, 1fr) auto; column-gap: 14px; row-gap: 6px; padding: 16px 18px; border: 1px solid var(--border); border-radius: 14px; background: var(--surface); box-shadow: 0 2px 4px rgb(0 0 0 / 2%); }
  .project-home .project-row.missing { background: #fff9ed; }
  .project-home .book-badge { width: 40px; height: 40px; border-radius: 10px; }
  .project-home .project-copy { gap: 6px; }
  .project-home .project-copy strong { font-size: var(--fs-md); overflow-wrap: anywhere; }
  .project-home .project-copy span { white-space: normal; overflow-wrap: anywhere; line-height: 1.6; }
  .project-home .project-copy small { white-space: normal; overflow-wrap: anywhere; line-height: 1.5; }
  .project-home .project-actions { max-width: 300px; }
  .project-home .small-button { min-height: 32px; padding: 5px 10px; font-weight: 600; }
  .project-home .small-button.primary { background: var(--accent); color: white; }
  .project-home .small-button.primary:hover:not(:disabled) { filter: brightness(.92); }
  .project-home .choice-grid { gap: 16px; }
  .project-home .choice { display: flex; align-items: center; gap: 14px; min-width: 0; min-height: 92px; padding: 16px; border-radius: 12px; border-color: var(--border); transition: background .15s, border-color .15s; }
  .project-home .choice-title { font-size: var(--fs-sm); margin-bottom: 3px; }
  .project-home .choice-copy > span:last-child { font-size: var(--fs-2xs); }
  .project-home .choice:hover:not(:disabled) { border-color: var(--accent); }
  .project-home .choice:hover:not(:disabled) .choice-arrow { color: var(--accent); }
  .project-home .link-button { min-height: 32px; padding: 6px 10px; margin-top: 6px; line-height: 1.5; text-decoration: underline; text-underline-offset: 3px; }
  .action-icon { display: grid; place-items: center; width: 34px; height: 34px; min-height: 34px; padding: 0; flex-shrink: 0; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface); color: var(--text-2); cursor: pointer; }
  .project-home .action-icon.danger { color: var(--danger); }
  .import-review { background: var(--bg); }
  .import-review .header, .import-review .list-area { max-width: 1200px; padding-left: 32px; padding-right: 32px; }
  .import-review .header { border: 0; padding-bottom: 0; }
  .import-review .header-row { display: grid; grid-template-columns: 34px minmax(0, 1fr) 34px; align-items: center; gap: 2px 14px; border: 0; padding-bottom: 0; }
  .review-heading { display: contents; }
  .review-heading h1 { grid-column: 2; grid-row: 1; min-width: 0; line-height: 1.15; }
  .review-heading .paratext-link { grid-column: 2; grid-row: 3; margin-top: 2px; line-height: 1.35; }
  .import-review .header-row .action-icon { border: 0; background: transparent; transition: color .15s, background .15s; }
  .import-review .header-row .back { grid-column: 1; grid-row: 1; }
  .import-review .header-row .review-close { grid-column: 3; grid-row: 1; }
  .import-review .header-row .back:hover:not(:disabled), .import-review .header-row .back:focus-visible { color: var(--accent); background: var(--accent-bg); }
  .import-review .header-row .review-close:hover:not(:disabled), .import-review .header-row .review-close:focus-visible { color: var(--danger); background: var(--danger-bg); }
  .import-review .header-row > div { min-width: 0; }
  .import-review .source { grid-column: 2; grid-row: 2; min-width: 0; max-width: none; white-space: normal; overflow-wrap: anywhere; margin: 0; line-height: 1.35; }
  .import-review .back { order: -1; margin: 0; }
  .import-review .header-row > div { flex: 1; }
  .import-review .content-grid { gap: 20px; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); padding-top: 0; align-items: stretch; }
  .import-review .summary, .import-review .form { min-width: 0; padding: 20px; border: 1px solid var(--border); border-radius: 14px; background: var(--surface); }
  .import-review .summary { position: relative; }
  .books-card-content { position: absolute; inset: 20px; display: flex; flex-direction: column; min-height: 0; }
  .books-card-content .books-heading, .books-card-content .note { flex-shrink: 0; }
  .books-card-content .import-notes { max-height: 120px; overflow: auto; flex-shrink: 0; }
  .import-review .form { gap: 16px; }
  .form-heading { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 10px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
  .form-heading > span { color: var(--text-2); background: var(--surface-2); border-radius: 6px; padding: 4px 8px; font-size: var(--fs-3xs); }
  .form label, .direction-field legend { font-size: var(--fs-xs); font-weight: 550; }
  .form label { gap: 8px; }
  .language-control { display: flex; flex-direction: column; gap: 8px; }
  .field-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
  .language-code { color: var(--accent); background: var(--accent-bg); border-radius: 5px; font-size: var(--fs-3xs); font-weight: 600; padding: 2px 6px; }
  .field-help { margin: -9px 0 0; color: var(--text-2); font-size: var(--fs-3xs); line-height: 1.5; }
  .direction-field { min-width: 0; padding: 0; border: 0; margin: 0; }
  .direction-field legend { color: var(--text); padding: 0 0 8px; }
  .direction-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px; padding: 4px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 10px; }
  .direction-options button { min-width: 0; display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 6px; border: 1px solid transparent; border-radius: 7px; padding: 8px; color: var(--text-2); background: transparent; font-size: var(--fs-2xs); cursor: pointer; }
  .direction-options button[aria-pressed="true"] { background: var(--accent); color: white; border-color: var(--accent); font-weight: 650; box-shadow: 0 1px 3px rgb(0 0 0 / 8%); }
  .direction-options button:hover:not([aria-pressed="true"]) { color: var(--accent); }
  .import-submit { display: flex; flex-direction: column; gap: 10px; padding-top: 16px; margin-top: 2px; border-top: 1px solid var(--border); }
  .import-review .form input { border-radius: 9px; font-weight: 400; }
  .import-review .form input::placeholder { color: var(--text-2); opacity: .75; }
  .import-review .form h2 { margin: 0 0 2px; }
  .import-review input:not([type="checkbox"]) { height: 40px; }
  .books-heading { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 16px; margin-bottom: 14px; }
  .books-heading h2 { margin: 0; }
  .books-controls { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 8px 14px; margin-left: auto; }
  .bulk-selection { flex-direction: row; align-items: center; gap: 7px; font-size: var(--fs-2xs); font-weight: 500; cursor: pointer; white-space: nowrap; }
  .bulk-selection input { width: 17px; height: 17px; margin: 0; padding: 0; accent-color: var(--accent); cursor: pointer; }
  .selection-count { font-size: var(--fs-2xs); color: var(--text-2); white-space: nowrap; }
  .import-review .book-list { flex: 1; min-height: 0; max-height: none; }
  .import-review .book-row { grid-template-columns: 18px 38px minmax(0, 1fr) auto; gap: 10px; min-height: 44px; padding: 8px 10px; cursor: pointer; font-weight: 400; }
  .book-row input[type="checkbox"] { width: 17px; height: 17px; margin: 0; padding: 0; accent-color: var(--accent); }
  .import-review .book-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; line-height: 1.6; }
  .import-review .book-meta { display: flex; align-items: center; gap: 7px; grid-column: auto; white-space: nowrap; text-align: right; padding: 0; font-variant-numeric: tabular-nums; }
  .book-separator { color: var(--text-3); font-size: var(--fs-lg); font-weight: 400; }
  .book-unselected { background: var(--surface-2); }
  .import-notes { font-size: var(--fs-2xs); margin-top: 12px; color: var(--text-2); }
  .import-notes summary { cursor: pointer; padding: 4px 0; }
  .import-review .import-button { height: auto; min-height: 40px; padding: 8px 12px; }
  @media (max-width: 760px) {
    .import-review .content-grid { grid-template-columns: minmax(0, 1fr); }
    .import-review .header, .import-review .list-area { padding-left: 16px; padding-right: 16px; }
    .import-review .summary, .import-review .form { padding: 16px; }
    .books-card-content { position: static; }
    .import-review .book-list { flex: none; max-height: 260px; }
  }
  .project-home .project-actions .action-icon { display: grid; place-items: center; width: 34px; height: 34px; min-height: 34px; padding: 0; border: 0; background: transparent; color: var(--text-2); border-radius: 8px; transition: color .15s, background .15s; }
  .project-home .project-actions .action-icon.primary { color: var(--accent); }
  .project-home .project-actions .action-icon.danger { color: var(--danger); }
  .project-home .project-actions .action-icon:hover:not(:disabled), .project-home .project-actions .action-icon:focus-visible { background: var(--accent-bg); color: var(--accent); filter: none; }
  .project-home .project-actions .action-icon.danger:hover:not(:disabled), .project-home .project-actions .action-icon.danger:focus-visible { background: var(--danger-bg); color: var(--danger); }
  @media (max-width: 1024px) {
    .project-home .project-row { grid-template-columns: 40px minmax(0, 1fr); }
    .project-home .project-actions { grid-column: 2; max-width: none; }
  }
  @media (max-width: 640px) {
    .project-home .header, .project-home .list-area, .project-home .footer { padding-left: 20px; padding-right: 20px; }
    .project-home .header { padding-top: 24px; }
    .project-home .project-row { padding: 16px; gap: 12px; }
    .project-home .project-actions, .project-details { grid-column: 1 / -1; }
    .details-body > div { grid-template-columns: 1fr; gap: 2px; }
    .project-home .project-actions button { min-height: 36px; }
    .header-row { flex-wrap: wrap; gap: 12px; }
    .header-row > div { min-width: 0; }
    .source { white-space: normal; overflow-wrap: anywhere; }
    .import-banner { flex-wrap: wrap; padding: 12px 20px; }
    .import-label { flex-basis: 100%; }
  }
  @media (max-width: 380px) {
    .project-home .header, .project-home .list-area, .project-home .footer { padding-left: 12px; padding-right: 12px; }
    h1 { font-size: var(--fs-3xl); }
  }
  @media (max-width: 760px) {
    .content-grid { grid-template-columns: 1fr; }
    .choice-grid { grid-template-columns: 1fr; }
    .header, .list-area, .footer { padding-left: 20px; padding-right: 20px; }
    .book-row { grid-template-columns: 42px 1fr; }
    .book-meta { grid-column: 2; text-align: left; padding-bottom: 8px; }
  }
  @media (max-height: 700px) {
    .project-home .header { padding-top: 12px; padding-bottom: 12px; }
    .project-home .footer { padding-bottom: 12px; }
    .project-home .section-heading { margin-bottom: 8px; }
    .project-home .choice { min-height: 66px; padding: 10px 12px; }
    .project-home .drop-hint { margin-top: 8px; }
    .project-toolbar { margin-bottom: 10px; }
  }
  @media (max-width: 640px) and (max-height: 640px) {
    .project-home .choice-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
    .project-home .choice { gap: 8px; }
    .project-home .choice-copy > span:last-child, .project-home .choice-arrow { display: none; }
    .project-home .choice-title { margin: 0; font-size: var(--fs-2xs); }
    .project-home .choice-icon { flex-basis: 30px; height: 30px; }
  }
  @media (prefers-reduced-motion: reduce) {
    .project-home .project-actions .action-icon, .import-review .header-row .action-icon { transition: none; }
  }
</style>
