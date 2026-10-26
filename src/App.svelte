<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { bridge } from "./lib/api/bridgeClient";
  import { bridgeReference } from "./lib/navigationReference";
  import {
    formatPerfLine, perfAbort, perfBegin, perfEnd, perfInFlight, perfResponded, registerPerfRunner, setPerfSink,
  } from "./lib/perf";
  import { BUSY_LABEL, MAX_BUSY_TIMEOUTS, checkFailureMessage, isBusyTimeout } from "./lib/checkMonitor";
  import ImportScreen from "./lib/components/ImportScreen.svelte";
  import TopBar from "./lib/components/TopBar.svelte";
  import VerseList from "./lib/components/VerseList.svelte";
  import ReviewPanel from "./lib/components/ReviewPanel.svelte";
  import LanguageQaPanel from "./lib/components/LanguageQaPanel.svelte";
  import ScopeConfirmDialog from "./lib/components/ScopeConfirmDialog.svelte";
  import ConfirmDialog from "./lib/components/ConfirmDialog.svelte";
  import { confirmRequest } from "./lib/confirmAction";
  import ScopeNotice from "./lib/components/ScopeNotice.svelte";
  import { resetScopedApply, scopeDialog } from "./lib/scopedApply";
  import { startFlagLoader } from "./lib/flags";
  import ReferencePanel from "./lib/components/ReferencePanel.svelte";
  import SourceTextPanel from "./lib/components/SourceTextPanel.svelte";
  import ParatextNotesPanel from "./lib/components/ParatextNotesPanel.svelte";
  import FindingContextMenu from "./lib/components/FindingContextMenu.svelte";
  import { TEXT_SCALES, bumpTextScale, rawView, sidePanelOrder, sidePanels, textScale, toggleSidePanel } from "./lib/editorPrefs";
  import { verseMin } from "./lib/panelFit";
  import SidePanel from "./lib/components/SidePanel.svelte";
  import SideRail from "./lib/components/SideRail.svelte";
  import {
    bookmarks, buildPlacesMenu, collectionOf, recentChapters, recordRecentChapter, setPlaces, toggleBookmark,
  } from "./lib/bookmarks";
  import AlignmentReview from "./lib/components/AlignmentReview.svelte";
  import CrossVerseAlignmentModal from "./lib/components/CrossVerseAlignmentModal.svelte";
  import AutoAlignChapterButton from "./lib/components/AutoAlignChapterButton.svelte";
  import {
    closeCrossVerse, crossVerseAnchor, crossVerseInitialVerses, crossVerseOpen, crossVerseRequest, openCrossVerse,
  } from "./lib/alignmentUi";
  import { resetReviewState } from "./lib/reviewStores";
  import SettingsModal from "./lib/components/SettingsModal.svelte";
  import ExportModal from "./lib/components/ExportModal.svelte";
  import ProjectDashboard from "./lib/components/ProjectDashboard.svelte";
  import DiagnosticsPanel from "./lib/components/DiagnosticsPanel.svelte";
  import StartupScreen from "./lib/components/StartupScreen.svelte";
  import UserPicker from "./lib/components/UserPicker.svelte";
  import AssignmentsDialog from "./lib/components/AssignmentsDialog.svelte";
  import { STARTUP_TIMEOUT_MS, mergeStage } from "./lib/startup";
  import type { EngineStartupStage, EngineStartupState } from "./lib/api/bridgeClient";
  import ProjectReportScreen from "./lib/components/ProjectReportScreen.svelte";
  import type { AiCheckReview, AlignmentWorkStatus, BookProgressEntry, CheckJobSnapshot, ProjectReport, QaFinding, StoredChapterFindings, UserRole, VerseDisplay, VerseHeading, WorkspaceUser } from "./lib/types/finding";
  import type {
    QaReport, ReportJobSnapshot, TriageJobSnapshot, TriageRecord,
  } from "./lib/types/report";
  import { isTriageUnavailable } from "./lib/types/report";
  import type { TriageOverrideVerdict } from "./lib/types/finding";
  import {
    project, currentChapter, chapterVerseNums, verseTexts, verseDisplay, headingsByVerse, findingsByVerse, historyCountByVerse,
    checkStatusByVerse, alignmentStatusByVerse, loadedChapters, selectedVerse, selectedVerseSet, checkingProgress, approvedCount, verseNums,
    verseKey, settingsOpen, exportOpen, bookApprovedSummary, resetBookState, reviewerMode,
    aiCheckReviewsByVerse, diagnosticsOpen, engineLog, appendEngineLog, navigationStatus,
    bookAssignments, localUserId, checkGroupsByVerse, type CheckStatus,
  } from "./lib/stores";
  import { get } from "svelte/store";
  import {
    boxesRan, checkListLabel, coversSelection, editorCheckList, groupsOf, mergeFindings, selectedEditorChecks,
  } from "./lib/checkSelection";
  import { planChapterEntry, shouldReadStored } from "./lib/chapterEntry";
  import { greekRoomChapterSummary, runVerseGreekRoom } from "./lib/verseChecks";
  import { projectRoles, refreshProjectRoles } from "./lib/projectRole";
  import CheckMenu from "./lib/components/CheckMenu.svelte";
  import { editingChapter, editingVerse, editSaving } from "./lib/verseEditor";
  import { languageQaChannel, nudgeLanguageQa, startLanguageQaInline } from "./lib/languageQaInline";
  import { toggleLanguageQaPanel } from "./lib/languageQaPanelUi";
  import { collectionQaRunning, stopCollectionQa } from "./lib/collectionQa";
  import CollectionQaPanel from "./lib/components/CollectionQaPanel.svelte";

  let opened = false;
  let engineStatus: "checking" | "ready" | "error" = "checking";
  let activeJobId = "";
  let monitorGeneration = 0;
  let openingBook = "";
  // #210: while a lazy sibling is prepared on the worker, which chapter it is on.
  let openingDetail = "";
  let bookOpenError = "";
  let droppedPath = "";
  let dropSequence = 0;
  let draggingOver = false;
  let dropError = "";
  let chapterLoadSequence = 0;
  let showingDashboard = false;
  // Alignment Review is a top-level surface alongside the editor, not a
  // replacement for ReviewPanel's per-verse alignment modal.
  let showingAlignmentReview = false;
  let bookProgress: BookProgressEntry[] = [];
  let dashboardLoading = false;
  let dashboardError = "";
  let report: ProjectReport | null = null;
  let reportLoading = false;
  let reportError = "";
  // Whole-collection QA report (TopBar "Generate report" on the project
  // screen). Built by a background sidecar job (report.generate) that is
  // polled here; the finished payload is fetched once and kept for the
  // rest of the session so returning to the screen is instant.
  let showingReport = false;
  let qaReport: QaReport | null = null;
  let qaReportJob: ReportJobSnapshot | null = null;
  let qaReportError = "";
  let qaReportPollTimer: ReturnType<typeof setTimeout> | undefined;
  let qaReportPollGeneration = 0;
  // AI triage overlay on that report. Optional and online-only: with no
  // verdicts and no API key the report screen renders exactly as it did
  // before triage existed.
  let triageEntries: Record<string, TriageRecord> = {};
  let triageJob: TriageJobSnapshot | null = null;
  let triageAvailable = false;
  let triageUnavailableReason = "";
  let triageError = "";
  let triageThreshold: number | null = 90;
  let triagePollTimer: ReturnType<typeof setTimeout> | undefined;
  let triagePollGeneration = 0;
  let engineNotice = "";
  let engineNoticeTimer: ReturnType<typeof setTimeout> | undefined;
  let settingsInitialPane: "ai" | "quality" | "connections" | "resources" | "terminology" | "languageQa" | "security" = "ai";
  let navigationPollInFlight = false;
  let handlingNavigationRequest = "";
  let lastNavigationReference = "";
  let navigationReference = "";
  let navigationRetryTimer: ReturnType<typeof setTimeout> | undefined;
  let navigationRetryReference = "";
  let navigationRetries = 0;

  function openSettings(pane: "ai" | "quality" | "connections" | "resources" | "terminology" | "languageQa" | "security" = "ai"): void {
    settingsInitialPane = pane;
    settingsOpen.set(true);
  }

  function currentBridgeReference(): string {
    return bridgeReference($project, $currentChapter, $selectedVerse);
  }

  function navigationContext(): string {
    return [
      $project?.path ?? "no-project",
      currentBridgeReference(),
      $editingChapter ? `editing:${$editingChapter}:${$editingVerse}` : "not-editing",
      $editSaving ? "saving" : "idle",
      screen,
    ].join("|");
  }

  // The ★ Bookmarks menu, anchored under its button.
  let placesMenu: { x: number; y: number } | null = null;
  $: currentPlace = $project && $selectedVerse
    ? { collection: collectionOf($project), book: $project.bookId.toLowerCase(), chapter: $currentChapter, verse: $selectedVerse }
    : null;
  $: placesActions = placesMenu ? buildPlacesMenu($bookmarks, $recentChapters, collectionOf($project), currentPlace) : [];

  // #232: every finished responsiveness sample goes to the diagnostics log
  // through the shell, where scripts/perf_table.py reads it; a logging
  // failure is nobody's problem but the log's.
  setPerfSink((sample) => { void bridge.logFrontend("info", formatPerfLine(sample)).catch(() => {}); });
  // A side-panel toggle (#232, Tier A) is timed at the store: the rail and the
  // toolbar both go through toggleSidePanel, whose update notifies here
  // synchronously inside the click, and the paint after it is the response.
  let sidePanelsSeen = false;
  const unsubscribeSidePanels = sidePanels.subscribe(() => {
    if (!sidePanelsSeen) { sidePanelsSeen = true; return; }
    perfBegin("panel.toggle");
    void perfEnd("panel.toggle");
  });
  onDestroy(() => { unsubscribeSidePanels(); registerPerfRunner(null); setPerfSink(null); });
  // The in-app runner for the measurement day (#232): the actions App.svelte
  // can drive without a mouse, each already instrumented. Registered while a
  // book is open in the editor, cleared otherwise.
  $: registerPerfRunner(opened && $project && !showingDashboard ? {
    navigateVerse: async () => {
      const verses = $chapterVerseNums[$currentChapter] ?? [];
      if (verses.length < 2) return;
      const index = verses.indexOf($selectedVerse ?? "");
      selectedVerse.set(verses[(index + 1) % verses.length]);
      await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    },
    openChapter: async () => {
      const chapters = $project?.chapters ?? [];
      if (chapters.length < 2) return;
      const index = chapters.indexOf($currentChapter);
      await activateChapter(chapters[(index + 1) % chapters.length]);
    },
    togglePanel: async () => {
      toggleSidePanel("reference");
      await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    },
    switchBook: ($project?.importedProjects?.length ?? 0) > 1 ? async () => {
      const siblings = $project?.importedProjects ?? [];
      const index = siblings.findIndex((book) => book.path === $project?.path);
      await switchBook(siblings[(index + 1) % siblings.length].path);
    } : null,
    openReport: async () => { await loadReport(); },
  } : null);

  function openPlacesMenu(event: MouseEvent): void {
    perfBegin("menu.open", "places");
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    placesMenu = { x: rect.left, y: rect.bottom + 4 };
    void perfEnd("menu.open");
  }

  async function onPlacesAction(event: CustomEvent<{ id: string }>): Promise<void> {
    placesMenu = null;
    const [kind, index] = event.detail.id.split(":");
    if (kind === "toggle") {
      if (!currentPlace) return;
      const error = await toggleBookmark(currentPlace);
      if (error) showNavigationNotice(error);
      return;
    }
    const place = kind === "bm" ? $bookmarks[Number(index)] : kind === "recent" ? $recentChapters[Number(index)] : undefined;
    if (place) await navigateToReportRow(place.book, place.chapter, place.verse ?? "");
  }

  function showNavigationNotice(message: string): void {
    if (engineNoticeTimer) clearTimeout(engineNoticeTimer);
    engineNotice = message;
    engineNoticeTimer = setTimeout(() => { engineNotice = ""; }, 10000);
  }

  async function rejectNavigation(requestId: string, message: string): Promise<void> {
    navigationStatus.set(await bridge.navigationResolve(
      requestId, false, currentBridgeReference(), navigationContext(),
    ));
    showNavigationNotice(message);
  }

  async function handleNavigationCandidate(
    candidate: { reference: string; origin: "paratext" | "logos"; requestId: string },
  ): Promise<void> {
    if (handlingNavigationRequest === candidate.requestId) return;
    handlingNavigationRequest = candidate.requestId;
    const source = candidate.origin === "paratext" ? "Paratext" : "Logos";
    try {
      if (!opened || !$project) {
        await rejectNavigation(candidate.requestId, `${source} moved to ${candidate.reference}; open a Bridge project to follow it.`);
        return;
      }
      if ($editingChapter || $editSaving) {
        await rejectNavigation(candidate.requestId, `${source} moved to ${candidate.reference}. Save or cancel the verse edit before following external navigation.`);
        return;
      }
      const match = /^([1-4]?[A-Z]{2,4})\s+(\d+):(\d+[a-z]?)$/i.exec(candidate.reference);
      if (!match) {
        await rejectNavigation(candidate.requestId, `${source} reported an unsupported Scripture reference.`);
        return;
      }
      const [, bookId, chapter, verse] = match;
      const original = {
        path: $project.path, chapter: $currentChapter, verse: $selectedVerse,
        dashboard: showingDashboard, review: showingAlignmentReview,
      };
      const destination = $project.bookId.toUpperCase() === bookId.toUpperCase()
        ? { path: $project.path }
        : $project.importedProjects?.find((book) => book.bookId.toUpperCase() === bookId.toUpperCase());
      if (!destination) {
        await rejectNavigation(candidate.requestId, `${source} moved to ${candidate.reference}, but that book is not in the open Bridge collection.`);
        return;
      }
      if (destination.path !== $project.path && !(await switchBook(destination.path, false))) {
        await rejectNavigation(candidate.requestId, `Bridge could not open the book requested by ${source}: ${bookOpenError || candidate.reference}.`);
        return;
      }
      let valid = $project?.chapters.includes(chapter) ?? false;
      if (valid) {
        await ensureChapterData(chapter);
        valid = ($chapterVerseNums[chapter] ?? []).includes(verse);
      }
      if (!valid) {
        if ($project?.path !== original.path) {
          await switchBook(original.path, false);
          if ($project?.chapters.includes(original.chapter) && original.verse) {
            await activateChapter(original.chapter, original.verse);
          }
          showingDashboard = original.dashboard;
          showingAlignmentReview = original.review;
        }
        await rejectNavigation(candidate.requestId, `${source} moved to ${candidate.reference}, which is not present in this Bridge project.`);
        return;
      }
      showingDashboard = false;
      showingAlignmentReview = false;
      await activateChapter(chapter, verse);
      navigationStatus.set(await bridge.navigationResolve(
        candidate.requestId, true, currentBridgeReference(), navigationContext(),
      ));
    } catch (error) {
      try {
        await rejectNavigation(
          candidate.requestId,
          `Could not follow ${source} navigation: ${error instanceof Error ? error.message : String(error)}`,
        );
      } catch (resolveError) {
        console.error("Could not reject external navigation", resolveError);
      }
    } finally {
      handlingNavigationRequest = "";
    }
  }

  // Refresh the navigation store from the engine without polling the
  // connectors. Used once at engine-ready and after a respawn so the poll
  // gate below has a real `enabled` value; SettingsModal does the same after
  // a save, so turning sync on later starts the round-trips on the next tick.
  async function refreshNavigationStatus(): Promise<void> {
    try {
      navigationStatus.set(await bridge.navigationStatus());
    } catch (error) {
      console.error("Could not read desktop navigation status", error);
    }
  }

  async function pollNavigation(): Promise<void> {
    if (navigationPollInFlight || engineStatus !== "ready") return;
    // No connector enabled means the engine's coordinator returns at once
    // (navigation.py's poll guard), so the only thing this tick would do is
    // occupy the single-threaded dispatcher line ~75 times a minute (#110).
    // The timer keeps ticking; it just does no RPC until sync is enabled.
    if (!$navigationStatus.enabled) return;
    navigationPollInFlight = true;
    try {
      const state = await bridge.navigationPoll(navigationContext());
      navigationStatus.set(state);
      if (state.candidate) await handleNavigationCandidate(state.candidate);
    } catch (error) {
      console.error("Could not poll desktop navigation", error);
    } finally {
      navigationPollInFlight = false;
    }
  }

  // Sidecar respawns are silent by design (see sidecar.rs) — the new
  // process has no project open, so anything project-scoped will fail
  // with "No project open" until this reconnects it. This is the recovery
  // path for that, not just a status update.
  async function handleEngineRespawn(): Promise<void> {
    if (engineNoticeTimer) clearTimeout(engineNoticeTimer);
    engineNotice = "Engine restarted — reconnecting…";
    try {
      await bridge.ping();
      engineStatus = "ready";
      await refreshNavigationStatus();
    } catch {
      engineStatus = "error";
    }
    const reopenPath = $project?.path;
    if (reopenPath) {
      try {
        const info = await bridge.openProject(reopenPath, $project?.projectId);
        const siblings = $project?.importedProjects;
        if (!info.importedProjects && siblings) info.importedProjects = siblings;
        project.set(info);
        lastNavigationReference = "";
        engineNotice = "Engine restarted — project reconnected automatically.";
      } catch (error) {
        engineNotice = `Engine restarted, but the project could not be reopened automatically (${error instanceof Error ? error.message : String(error)}). Reopen it from Projects if things look stale.`;
      }
    } else {
      engineNotice = "Engine restarted.";
    }
    engineNoticeTimer = setTimeout(() => { engineNotice = ""; }, 10000);
  }

  // The verse marks' own poll (languageQaInline.ts), on the same lifecycle as
  // LanguageQaPanel below -- running while a book is open, restarted when the
  // book changes -- but independent of the panel, which only pages its list.
  let stopLanguageQaInline: (() => void) | null = null;
  let stopFlagLoader: (() => void) | null = null;
  let languageQaInlinePath = "";
  $: {
    const path = $project && opened ? $project.path : "";
    if (path !== languageQaInlinePath) {
      stopLanguageQaInline?.();
      stopLanguageQaInline = null;
      stopFlagLoader?.();
      stopFlagLoader = null;
      languageQaInlinePath = path;
      // A scoped correction's batch belongs to the book it was made in.
      resetScopedApply();
      if (path) stopLanguageQaInline = startLanguageQaInline(path);
      // Reviewer flags (⚑) of each chapter as it is shown.
      if (path) stopFlagLoader = startFlagLoader(path);
    }
  }
  onDestroy(() => {
    stopLanguageQaInline?.();
    stopFlagLoader?.();
  });

  // Collection QA (layered-rules 4.4): while a run checks every book, the app
  // is read-only. checkingProgress.running is what already holds editing,
  // alignment and AI review; the book switcher checks collectionQaRunning.
  let collectionHeldProgress = false;
  $: if ($collectionQaRunning && !collectionHeldProgress) {
    collectionHeldProgress = true;
    checkingProgress.update((p) => ({ ...p, running: true, label: "Collection QA running", state: "running" }));
  } else if (!$collectionQaRunning && collectionHeldProgress) {
    collectionHeldProgress = false;
    checkingProgress.update((p) => ({ ...p, running: false, label: "Collection QA finished", state: "succeeded" }));
  }
  $: if (!$project || !opened) stopCollectionQa();
  // #279: the signed-in user's role on the open project, re-read when the
  // project or the user changes (a role set in Settings > Users refreshes it too).
  $: projectRoleKey = $project && opened && engineStatus === "ready" ? `${$project.path}|${$localUserId}` : "";
  $: void refreshProjectRoles(Boolean(projectRoleKey));

  // Startup (#233). The loading screen covers the window until the engine
  // answers its first ping; its status line is the latest stage the shell
  // reported. Listen first, then fetch the stages that accumulated before
  // this webview existed (the sidecar usually spawns before the page loads),
  // merged by sequence number so a stage seen both ways counts once. A
  // failure is shown the moment a "failed" or "exited" stage arrives, or
  // after STARTUP_TIMEOUT_MS with no answer; Retry pings again, which
  // respawns a dead sidecar (sidecar.rs send_request).
  let startupState: EngineStartupState | null = null;
  let startupStages: EngineStartupStage[] = [];
  let startupFailure = "";
  let startupDone = false;
  // #237: several users and none chosen yet: the picker comes before Home.
  let needsUserChoice = false;
  // #240: who is signed in (for "My work") and the assignments dialog.
  let localUserRole: UserRole = "project_admin";
  let assigningPath = "";
  let assigningUsers: WorkspaceUser[] = [];
  let assigningBusy = false;
  let assigningError = "";
  let startupTimer: ReturnType<typeof setTimeout> | undefined;
  let startupAttempt = 0;
  let unlistenFileDrop: (() => void) | null = null;
  let appDisposed = false;

  // #287: the window starts hidden behind a small splash window. Show it the
  // moment startup has an outcome: Home on success, the full loading card's
  // failure view (log, Copy diagnostics, Retry) otherwise. The shell also
  // shows it on its own if this never runs (sidecar.rs has the fallback).
  $: if (startupDone || startupFailure) {
    bridge.revealMainWindow().catch((error) => console.error("Could not show the main window", error));
  }

  function noteStartupStage(stage: EngineStartupStage): void {
    startupStages = mergeStage(startupStages, stage);
    if (startupDone) return;
    if (stage.stage === "spawning") startupFailure = "";
    else if (stage.stage === "failed" || stage.stage === "exited") startupFailure = stage.label;
  }

  function armStartupTimeout(attempt: number): void {
    if (startupTimer) clearTimeout(startupTimer);
    startupTimer = setTimeout(() => {
      if (attempt !== startupAttempt || startupDone || appDisposed) return;
      startupFailure = startupFailure || `The engine did not answer within ${STARTUP_TIMEOUT_MS / 1000} seconds.`;
    }, STARTUP_TIMEOUT_MS);
  }

  async function connectEngine(): Promise<void> {
    const attempt = ++startupAttempt;
    engineStatus = "checking";
    startupFailure = "";
    armStartupTimeout(attempt);
    try {
      await bridge.ping();
      if (appDisposed || attempt !== startupAttempt) return;
      if (startupTimer) clearTimeout(startupTimer);
      engineStatus = "ready";
      startupDone = true;
      await refreshNavigationStatus();
      try {
        const settings = await bridge.getSettings();
        reviewerMode.set(settings.reviewerMode);
        needsUserChoice = Boolean(settings.needsUserChoice);
        localUserId.set(settings.localUserId || "");
        localUserRole = settings.localUserRole ?? "project_admin";
        setPlaces(settings);
        triageThreshold = settings.triageHideThreshold > 0 ? settings.triageHideThreshold : null;
      } catch (error) {
        console.error("Could not load reviewer mode", error);
      }
      if (!unlistenFileDrop) {
        const stopListening = await bridge.onFileDrop(
          (paths) => void handleDroppedPaths(paths),
          (phase) => { draggingOver = phase === "over"; },
        );
        if (appDisposed) stopListening();
        else unlistenFileDrop = stopListening;
      }
    } catch (error) {
      if (attempt !== startupAttempt) return;
      engineStatus = "error";
      // A stage that already named the failure (spawn error, early exit) is
      // the better text; the ping's own error is the fallback.
      startupFailure = startupFailure
        || `The engine did not answer: ${error instanceof Error ? error.message : String(error)}`;
    }
  }

  onMount(() => {
    let unlistenLog: (() => void) | null = null;
    let unlistenRespawn: (() => void) | null = null;
    let unlistenStage: (() => void) | null = null;
    const navigationTimer = window.setInterval(() => void pollNavigation(), 800);
    void (async () => {
      try {
        const stopStage = await bridge.onEngineStage(noteStartupStage);
        if (appDisposed) stopStage();
        else unlistenStage = stopStage;
      } catch (error) {
        console.error("Could not subscribe to engine startup stages", error);
      }
      try {
        const state = await bridge.engineStartupState();
        if (!appDisposed) {
          startupState = state;
          for (const stage of state.stages) noteStartupStage(stage);
        }
      } catch (error) {
        console.error("Could not read engine startup state", error);
      }
      try {
        const initialLog = await bridge.engineLogRecent(200);
        if (!appDisposed) engineLog.set(initialLog);
      } catch (error) {
        console.error("Could not load engine diagnostics", error);
      }
      try {
        const stopLog = await bridge.onEngineLog(appendEngineLog);
        if (appDisposed) stopLog();
        else unlistenLog = stopLog;
      } catch (error) {
        // Diagnostics are helpful but must never prevent the engine, settings,
        // file-drop handling, or project editor from finishing startup.
        console.error("Could not subscribe to engine diagnostics", error);
      }
      try {
        const stopRespawn = await bridge.onEngineRespawned(() => void handleEngineRespawn());
        if (appDisposed) stopRespawn();
        else unlistenRespawn = stopRespawn;
      } catch (error) {
        console.error("Could not subscribe to engine restart events", error);
      }
      await connectEngine();
    })();
    return () => {
      appDisposed = true;
      unlistenFileDrop?.();
      unlistenLog?.();
      unlistenRespawn?.();
      unlistenStage?.();
      if (startupTimer) clearTimeout(startupTimer);
      if (engineNoticeTimer) clearTimeout(engineNoticeTimer);
      if (navigationRetryTimer) clearTimeout(navigationRetryTimer);
      window.clearInterval(navigationTimer);
    };
  });

  async function handleDroppedPaths(paths: string[]) {
    draggingOver = false;
    dropError = "";
    if (paths.length !== 1) {
      dropError = "Drop exactly one project file or folder at a time.";
      return;
    }
    await showProjectHome();
    droppedPath = paths[0];
    dropSequence += 1;
  }

  async function showProjectHome() {
    await stopActiveJob();
    resetBookState();
    resetReviewState();
    project.set(null);
    opened = false;
    showingAlignmentReview = false;
    showingReport = false;
    stopReportPolling();
    qaReport = null;
    qaReportJob = null;
    qaReportError = "";
    openingBook = "";
    bookOpenError = "";
  }

  // #240: the open book's assignments, for the chapter list's marks.
  async function loadAssignments(): Promise<void> {
    try {
      bookAssignments.set((await bridge.assignmentsList()).assignments);
    } catch {
      bookAssignments.set([]);
    }
  }

  async function openAssignments(path: string): Promise<void> {
    assigningError = "";
    if ($project && path !== $project.path && !(await switchBook(path, false))) return;
    try {
      assigningUsers = (await bridge.usersList()).users;
      await loadAssignments();
      assigningPath = path;
    } catch (error) {
      assigningError = error instanceof Error ? error.message : String(error);
    }
  }

  /** One chapter ("" = whole book) set or cleared through the existing
   *  team_assignments calls (#240). #378: the Assign dialog applies a batch
   *  as one call per changed chapter, so the dashboard is refreshed once by
   *  onApplied rather than after each; resolves false when the save failed,
   *  so the dialog stops there. */
  async function assign(chapter: string, userId: string, refresh = true): Promise<boolean> {
    assigningBusy = true;
    assigningError = "";
    try {
      const listed = userId ? await bridge.assignmentsSet(chapter, userId) : await bridge.assignmentsClear(chapter);
      bookAssignments.set(listed.assignments);
      if (refresh) void loadDashboard();
      return true;
    } catch (error) {
      assigningError = error instanceof Error ? error.message : String(error);
      return false;
    } finally {
      assigningBusy = false;
    }
  }

  async function handleOpened() {
    opened = true;
    showingDashboard = true;
    report = null;
    reportError = "";
    void loadAssignments();
    // #232: "open a project" ends when the dashboard it lands on has painted.
    void loadDashboard().then(() => perfEnd("project.open"));
    // The QA report is deliberately NOT built here. Measured on Genesis of a
    // real Hindi IRV import: build_book_report() takes ~130 s (project_scan
    // 78 s + exception_first_queue 44 s), and the sidecar's stdio loop is
    // single-threaded, so every other request queues behind it -- the 30 s
    // client timeout fired and the whole app was unresponsive until Python
    // finished. It is requested explicitly from the dashboard instead.
  }

  async function loadDashboard(): Promise<void> {
    dashboardLoading = true;
    dashboardError = "";
    try {
      bookProgress = (await bridge.listBookProgress()).books;
    } catch (error) {
      dashboardError = error instanceof Error ? error.message : String(error);
    } finally {
      dashboardLoading = false;
    }
  }

  async function loadReport(): Promise<void> {
    perfBegin("book.report", $project?.bookId ?? "");
    reportLoading = true;
    reportError = "";
    perfResponded("book.report");
    try {
      report = await bridge.projectReport();
    } catch (error) {
      reportError = error instanceof Error ? error.message : String(error);
    } finally {
      reportLoading = false;
      void perfEnd("book.report");
    }
  }

  function openDashboard(): void {
    showingAlignmentReview = false;
    showingReport = false;
    showingDashboard = true;
    void loadDashboard();
    // Same reasoning as handleOpened: whichever book is open, the report is
    // minutes of synchronous work that blocks the sidecar, so it is a button.
  }

  // -- whole-collection QA report ---------------------------------------

  const REPORT_TERMINAL = new Set(["succeeded", "failed", "cancelled"]);

  function stopReportPolling(): void {
    qaReportPollGeneration += 1;
    if (qaReportPollTimer) clearTimeout(qaReportPollTimer);
    qaReportPollTimer = undefined;
  }

  function openReportScreen(): void {
    showingAlignmentReview = false;
    showingReport = true;
    if (!qaReport && !qaReportJob) void generateReport();
    // Verdicts live on disk, so a previous session's triage is already
    // available the moment the screen opens — no run required.
    void loadTriageResults();
  }

  async function generateReport(): Promise<void> {
    qaReportError = "";
    stopReportPolling();
    const generation = qaReportPollGeneration;
    try {
      let snapshot: ReportJobSnapshot;
      try {
        snapshot = await bridge.reportGenerate();
      } catch (error) {
        // A build is already running (a double click, or a second window
        // on the same sidecar): follow it rather than fail.
        const message = error instanceof Error ? error.message : String(error);
        if (!/already/i.test(message)) throw error;
        snapshot = await bridge.reportStatus("");
      }
      if (generation !== qaReportPollGeneration) return;
      qaReportJob = snapshot;
      await pollReport(snapshot.jobId, generation);
    } catch (error) {
      if (generation !== qaReportPollGeneration) return;
      qaReportError = error instanceof Error ? error.message : String(error);
      qaReportJob = null;
    }
  }

  async function pollReport(jobId: string, generation: number): Promise<void> {
    while (generation === qaReportPollGeneration) {
      const snapshot = await bridge.reportStatus(jobId);
      if (generation !== qaReportPollGeneration) return;
      qaReportJob = snapshot;
      if (REPORT_TERMINAL.has(snapshot.state)) {
        if (snapshot.ready) {
          const fetched = await bridge.reportGet(jobId);
          if (generation !== qaReportPollGeneration) return;
          qaReport = fetched.report;
          // Some books unreadable: the report still stands, say which part is missing.
          if (snapshot.error) qaReportError = snapshot.error;
        } else {
          qaReportError = snapshot.error
            || (snapshot.state === "cancelled" ? "Report generation was cancelled." : "Report generation failed.");
        }
        return;
      }
      await new Promise<void>((resolve) => { qaReportPollTimer = setTimeout(resolve, 500); });
    }
  }

  async function cancelReport(): Promise<void> {
    if (!qaReportJob) return;
    try {
      qaReportJob = await bridge.reportCancel(qaReportJob.jobId);
    } catch (error) {
      qaReportError = error instanceof Error ? error.message : String(error);
    }
  }

  // -- AI triage overlay -------------------------------------------------
  //
  // Verdicts are persisted per book by the engine, so they are always read
  // from disk (triage.results) rather than from the job — they survive a
  // restart, and a cancelled run keeps whatever it already paid for. The
  // report itself never depends on any of this having happened.

  /**
   * Reads verdicts off disk. With no `book` this replaces the whole map;
   * with one it merges just that book's verdicts in, which is what the
   * mid-run refresh wants — re-reading all 66 books every second to watch
   * one of them change would be pointless file I/O.
   */
  async function loadTriageResults(book = ""): Promise<void> {
    try {
      const results = await bridge.triageResults(book);
      triageEntries = book ? { ...triageEntries, ...results.entries } : results.entries;
      triageAvailable = results.available;
      triageUnavailableReason = results.unavailableReason;
    } catch (error) {
      // A failure here must never break the report: the page simply shows
      // no verdicts and the run button stays disabled.
      triageError = error instanceof Error ? error.message : String(error);
    }
  }

  async function runTriage(): Promise<void> {
    triageError = "";
    stopTriagePolling();
    const generation = triagePollGeneration;
    try {
      const started = await bridge.triageRun();
      if (generation !== triagePollGeneration) return;
      if (isTriageUnavailable(started)) {
        triageError = started.message;
        triageAvailable = false;
        triageUnavailableReason = started.message;
        return;
      }
      triageJob = started;
      await pollTriage(started.jobId, generation);
    } catch (error) {
      if (generation !== triagePollGeneration) return;
      triageError = error instanceof Error ? error.message : String(error);
      triageJob = null;
    }
  }

  async function pollTriage(jobId: string, generation: number): Promise<void> {
    while (generation === triagePollGeneration) {
      const snapshot = await bridge.triageStatus(jobId);
      if (generation !== triagePollGeneration) return;
      triageJob = snapshot;
      if (REPORT_TERMINAL.has(snapshot.state)) {
        // Even a cancelled or partly-failed run leaves verdicts on disk, so
        // this full read is always worth doing.
        await loadTriageResults();
        if (snapshot.error) triageError = snapshot.error;
        return;
      }
      // Refresh mid-run so verdicts appear as they are bought, not only at
      // the end — a whole-Bible run is long and silent otherwise. Scoped to
      // the book in flight: nothing else can have changed.
      if (snapshot.currentBook) await loadTriageResults(snapshot.currentBook);
      await new Promise<void>((resolve) => { triagePollTimer = setTimeout(resolve, 1000); });
    }
  }

  function stopTriagePolling(): void {
    triagePollGeneration += 1;
    if (triagePollTimer) clearTimeout(triagePollTimer);
    triagePollTimer = undefined;
  }

  async function cancelTriage(): Promise<void> {
    if (!triageJob) return;
    try {
      triageJob = await bridge.triageCancel(triageJob.jobId);
    } catch (error) {
      triageError = error instanceof Error ? error.message : String(error);
    }
  }

  async function setTriageThreshold(value: number | null): Promise<void> {
    triageThreshold = value;
    try {
      await bridge.setSettings({ triageHideThreshold: value ?? 0 });
    } catch {
      // A settings write failure must not fight the reviewer's slider: the
      // value stands for this session and simply is not remembered.
    }
  }

  async function overrideTriage(
    book: string, hash: string, verdict: TriageOverrideVerdict | "",
  ): Promise<void> {
    try {
      const result = await bridge.triageOverride(book, hash, verdict);
      triageEntries = { ...triageEntries, [hash]: result.record };
    } catch (error) {
      triageError = error instanceof Error ? error.message : String(error);
    }
  }

  // A row in the report table → that verse in the editor, switching to the
  // row's book first when it isn't the one currently open.
  async function navigateToReportRow(bookId: string, chapter: string, verse: string): Promise<void> {
    if (!$project) return;
    const wanted = bookId.toLowerCase();
    if ($project.bookId.toLowerCase() !== wanted) {
      const path = $project.importedProjects?.find((book) => book.bookId.toLowerCase() === wanted)?.path
        ?? bookProgress.find((book) => book.bookId.toLowerCase() === wanted)?.path;
      if (!path) {
        showNavigationNotice(`${bookId.toUpperCase()} is not in the open collection.`);
        return;
      }
      if (!(await switchBook(path, false))) return;
    }
    await navigateToFinding(chapter, verse);
  }

  async function enterBookFromDashboard(path: string): Promise<void> {
    // switchBook() no-ops when path === $project.path, which is exactly the
    // first-open interstitial case (enterCurrentProject was never called
    // yet) — so the already-open primary book's own row needs this instead.
    if ($project && path === $project.path) {
      showingDashboard = false;
      if (!$loadedChapters[$currentChapter]) await enterCurrentProject();
      return;
    }
    await switchBook(path);
    showingDashboard = false;
  }

  // Clicking a book row (not its Open button) previews that book's report in
  // the dashboard's right panel without leaving the dashboard — the
  // switchBook(path, false) seam activates a sibling book with no editor
  // navigation.
  async function previewBookOnDashboard(path: string): Promise<void> {
    if ($project && path === $project.path) return;
    if (await switchBook(path, false)) void loadReport();
  }

  // Shared by initial open and book switching: land on the first chapter
  // and its first verse once `project` points at the book to display.
  async function enterCurrentProject(): Promise<void> {
    const firstChapter = $project?.chapters[0] ?? "1";
    await activateChapter(firstChapter);
  }

  // Switch to a sibling book from a multi-book import. The sidecar's
  // project.open doesn't echo back importedProjects (only project.import
  // does), so the sibling list is carried forward on the frontend instead
  // of being re-fetched.
  async function switchBook(path: string, enterEditor = true): Promise<boolean> {
    if (!$project || openingBook) return false;
    if (path === $project.path) return true;
    if ($collectionQaRunning) {
      bookOpenError = "Collection QA is running. Pause or cancel it before switching books.";
      return false;
    }
    const siblings = $project.importedProjects;
    const destination = siblings?.find((book) => book.path === path);
    perfBegin("book.switch", destination?.bookId ?? "");
    openingBook = destination?.bookName ?? "book";
    openingDetail = "";
    bookOpenError = "";
    perfResponded("book.switch");
    try {
      await stopActiveJob();
      const info = await bridge.openProject(path, undefined, (snapshot) => {
        openingDetail = snapshot.chapter && snapshot.chapterCount
          ? `preparing chapter ${snapshot.chapter} of ${snapshot.chapterCount}`
          : snapshot.state === "succeeded" ? "" : "preparing";
      });
      openingDetail = "";
      if (!info.importedProjects && siblings) info.importedProjects = siblings;
      resetBookState();
    resetReviewState();
      project.set(info);
      void loadAssignments();
      if (enterEditor) await enterCurrentProject();
      void perfEnd("book.switch");
      return true;
    } catch (error) {
      perfAbort("book.switch");
      bookOpenError = error instanceof Error ? error.message : String(error);
      return false;
    } finally {
      openingBook = "";
    }
  }

  async function ensureChapterData(chapter: string): Promise<void> {
    const knownVerses = $chapterVerseNums[chapter] ?? [];
    if (
      knownVerses.length > 0 &&
      knownVerses.every((verse) => Object.prototype.hasOwnProperty.call($verseTexts, verseKey(chapter, verse)))
    ) return;
    const { verses, headings, editCounts } = await bridge.chapterVerseData(chapter);
    const verseIds = Object.keys(verses);
    chapterVerseNums.update((m) => ({ ...m, [chapter]: verseIds }));

    const texts: Record<string, string> = {};
    const displays: Record<string, VerseDisplay> = {};
    const alignmentStatuses: Record<string, AlignmentWorkStatus> = {};
    for (const [v, data] of Object.entries(verses)) {
      texts[verseKey(chapter, v)] = data.text;
      // The engine says what the verse shows (#91); the reader never parses USFM.
      if (data.display) displays[verseKey(chapter, v)] = data.display;
      alignmentStatuses[verseKey(chapter, v)] = data.alignmentStatus;
    }
    // Keyed by verseKey like everything else here: a bare verse number would
    // collide across chapters (gotcha 7).
    const headingRows: Record<string, VerseHeading[]> = {};
    for (const [v, rows] of Object.entries(headings ?? {})) {
      headingRows[verseKey(chapter, v)] = rows;
    }
    verseTexts.update((t) => ({ ...t, ...texts }));
    verseDisplay.update((d) => ({ ...d, ...displays }));
    headingsByVerse.update((h) => ({ ...h, ...headingRows }));
    alignmentStatusByVerse.update((existing) => ({ ...existing, ...alignmentStatuses }));
    const counts: Record<string, number> = {};
    for (const [v, n] of Object.entries(editCounts ?? {})) counts[verseKey(chapter, v)] = n;
    historyCountByVerse.update((existing) => ({ ...existing, ...counts }));
  }

  async function hydrateChapterAIReviews(
    chapter: string, expectedProjectPath: string, sequence: number,
  ): Promise<void> {
    try {
      const result = await bridge.listAIReviewsForChapter(chapter);
      if (
        sequence !== chapterLoadSequence || chapter !== $currentChapter
        || ($project?.path ?? "") !== expectedProjectPath
      ) return;
      const updates: Record<string, AiCheckReview[]> = {};
      for (const [verse, reviews] of Object.entries(result.reviewsByVerse)) {
        updates[verseKey(chapter, verse)] = reviews;
      }
      aiCheckReviewsByVerse.update((existing) => ({ ...existing, ...updates }));
    } catch (error) {
      console.error("Could not restore chapter AI reviews", error);
    }
  }

  /** `seen`: every verse status this job has reported so far. monitorJob polls
   *  checks.status with a cursor, so each snapshot carries only the verses
   *  finished since the previous poll (#229) and the end-of-job bookkeeping
   *  below reads the tally instead. A caller holding a full snapshot omits it. */
  function applyJobSnapshot(
    snapshot: CheckJobSnapshot, seen: Record<string, "succeeded" | "failed"> = {},
  ): void {
    chapterVerseNums.update((existing) => ({ ...existing, ...snapshot.chapterVerses }));

    // #251: the job ran some checks. Each verse keeps its findings of the
    // others, remembers what has run, and earns its ✓ only once every check
    // in the reviewer's selection has run on it.
    const groups = snapshot.checkGroups ?? groupsOf(snapshot.checks);
    const selection = editorCheckList();
    const results = Object.entries(snapshot.results);
    for (const [key, result] of results) seen[key] = result.status;
    if (results.length > 0) {
      const ranByVerse = get(checkGroupsByVerse);
      const groupUpdates: Record<string, string[]> = {};
      const statusUpdates: Record<string, CheckStatus> = {};
      for (const [key, result] of results) {
        const ran = result.status === "succeeded"
          ? [...new Set([...(ranByVerse[key] ?? []), ...groups])] : (ranByVerse[key] ?? []);
        groupUpdates[key] = ran;
        statusUpdates[key] = result.status === "failed" ? "failed"
          : coversSelection(ran, selection) ? "succeeded" : "pending";
      }
      findingsByVerse.update((existing) => {
        const next = { ...existing };
        for (const [key, result] of results) next[key] = mergeFindings(existing[key], result.findings, groups);
        return next;
      });
      checkGroupsByVerse.update((existing) => ({ ...existing, ...groupUpdates }));
      checkStatusByVerse.update((existing) => ({ ...existing, ...statusUpdates }));
    }

    const terminal = ["succeeded", "failed", "cancelled"].includes(snapshot.state);
    // The job's Language QA pass published a new generation: redraw the marks
    // now rather than at the channel's next idle tick.
    if (terminal && snapshot.checks.includes("languageQa")) nudgeLanguageQa();
    if (terminal) {
      checkStatusByVerse.update((existing) => {
        const next = { ...existing };
        for (const [chapter, verses] of Object.entries(snapshot.chapterVerses)) {
          for (const verse of verses) {
            const key = verseKey(chapter, verse);
            if (!seen[key]) next[key] = snapshot.state === "cancelled" ? "cancelled" : "failed";
          }
        }
        return next;
      });
      loadedChapters.update((existing) => {
        const next = { ...existing };
        for (const [chapter, verses] of Object.entries(snapshot.chapterVerses)) {
          next[chapter] = verses.length > 0 && verses.every(
            (verse) => seen[verseKey(chapter, verse)] === "succeeded",
          );
        }
        return next;
      });
    }

    const reference = snapshot.currentChapter
      ? ` · ${snapshot.currentChapter}${snapshot.currentVerse ? `:${snapshot.currentVerse}` : ""}`
      : "";
    // The stage names the checks running; at the end, say which ran (#251).
    const label = snapshot.state === "succeeded"
      ? `Checked: ${checkListLabel(snapshot.checks)}`
      : `${snapshot.currentStage}${reference}`;
    checkingProgress.set({
      running: !terminal,
      percent: snapshot.percent,
      label,
      jobId: snapshot.jobId,
      state: snapshot.state,
      error: snapshot.error ?? "",
      scope: snapshot.scope,
    });
  }

  async function monitorJob(initial: CheckJobSnapshot, generation: number): Promise<void> {
    let snapshot = initial;
    const seen: Record<string, "succeeded" | "failed"> = {};
    for (const [key, result] of Object.entries(initial.results)) seen[key] = result.status;
    let cursor = initial.resultsCursor ?? 0;
    let busyTimeouts = 0;
    try {
      while (!["succeeded", "failed", "cancelled"].includes(snapshot.state)) {
        await new Promise((resolve) => setTimeout(resolve, 750));
        if (generation !== monitorGeneration) return;
        try {
          snapshot = await bridge.checkStatus(snapshot.jobId, cursor);
        } catch (error) {
          // A busy sidecar, not a failed check (#210): say so and poll again.
          if (!isBusyTimeout(error) || ++busyTimeouts >= MAX_BUSY_TIMEOUTS) throw error;
          if (generation !== monitorGeneration) return;
          checkingProgress.update((progress) => ({ ...progress, label: BUSY_LABEL }));
          continue;
        }
        busyTimeouts = 0;
        if (generation !== monitorGeneration) return;
        cursor = snapshot.resultsCursor ?? cursor;
        applyJobSnapshot(snapshot, seen);
      }
    } catch (error) {
      if (generation !== monitorGeneration) return;
      checkingProgress.set({
        running: false,
        percent: snapshot.percent,
        label: "Checking failed",
        jobId: snapshot.jobId,
        state: "failed",
        error: checkFailureMessage(error),
        scope: snapshot.scope,
      });
    } finally {
      if (generation === monitorGeneration) activeJobId = "";
    }
  }

  function markJobPending(snapshot: CheckJobSnapshot): void {
    checkStatusByVerse.update((existing) => {
      const next = { ...existing };
      for (const [chapter, verses] of Object.entries(snapshot.chapterVerses)) {
        for (const verse of verses) next[verseKey(chapter, verse)] = "pending";
      }
      return next;
    });
  }

  /** `checks`: the reviewer's selection (#251), or ["greekroom"] for Run Greek
   *  Room (#252). Language QA is a stage of the same job (layered-rules Phase
   *  4.1): its pass is the authoritative one and shares the live-edit cache.
   *  Nothing starts while Collection QA runs; the engine would refuse it. */
  async function beginChecks(
    scope: "chapter" | "book", chapters: string[], checks: string[] = editorCheckList(),
  ): Promise<void> {
    if (activeJobId || $collectionQaRunning) return;
    const snapshot = await bridge.startChecks(scope, chapters, checks);
    activeJobId = snapshot.jobId;
    const generation = ++monitorGeneration;
    markJobPending(snapshot);
    applyJobSnapshot(snapshot);
    void monitorJob(snapshot, generation);
  }

  async function activateChapter(chapter: string, targetVerse?: string): Promise<void> {
    const sequence = ++chapterLoadSequence;
    // #232 (Tier B): the chapter number is the first visible change; the
    // chapter is open once its verses are in the stores and one is selected.
    // A book switch owns the whole span, so its chapter open is not timed.
    const timed = !perfInFlightBookOrProject();
    if (timed) perfBegin("chapter.open", chapter);
    currentChapter.set(chapter);
    selectedVerseSet.set([]); // the multi-selection is chapter-scoped (#118)
    if (timed) perfResponded("chapter.open");
    await ensureChapterData(chapter);
    if (sequence !== chapterLoadSequence || chapter !== $currentChapter) {
      if (timed) perfAbort("chapter.open");
      return;
    }
    const verses = $chapterVerseNums[chapter] ?? [];
    selectedVerse.set(
      targetVerse && verses.includes(targetVerse) ? targetVerse : (verses.length > 0 ? verses[0] : null),
    );
    if (timed) void perfEnd("chapter.open");
    void hydrateChapterAIReviews(chapter, $project?.path ?? "", sequence);
    if ($project) recordRecentChapter({ collection: collectionOf($project), book: $project.bookId.toLowerCase(), chapter });
    await enterChapterChecks(chapter, sequence);
  }

  /** #272: on first entry, show the chapter's stored findings when they still
   *  describe it, and run only the selected checks they do not cover; with
   *  nothing current stored, run the chapter job as before (#114). */
  async function enterChapterChecks(chapter: string, sequence: number): Promise<void> {
    const state = () => ({
      loaded: Boolean($loadedChapters[chapter]), jobActive: Boolean(activeJobId), collectionRunning: $collectionQaRunning,
    });
    if (!shouldReadStored(state())) return;
    let stored: StoredChapterFindings | null = null;
    try {
      stored = await bridge.loadChapterFindings(chapter);
    } catch (error) {
      console.error("Stored chapter findings could not be read", error);
    }
    if (sequence !== chapterLoadSequence) return;
    const selection = editorCheckList();
    const plan = planChapterEntry(state(), stored, selection);
    if (plan.kind === "stored" && stored) showStoredChapter(chapter, stored, selection, plan.run.length === 0);
    if ((plan.kind === "stored" || plan.kind === "job") && plan.run.length) {
      await beginChecks("chapter", [chapter], plan.run);
    }
  }

  function showStoredChapter(
    chapter: string, stored: StoredChapterFindings, selection: string[], complete: boolean,
  ): void {
    const verses = $chapterVerseNums[chapter] ?? [];
    const covered = coversSelection(stored.checkGroups, selection);
    const findings: Record<string, QaFinding[]> = {};
    const groups: Record<string, string[]> = {};
    const statuses: Record<string, CheckStatus> = {};
    for (const verse of verses) {
      const key = verseKey(chapter, verse);
      findings[key] = stored.verses[verse] ?? [];
      groups[key] = [...stored.checkGroups];
      statuses[key] = covered ? "succeeded" : "pending";
    }
    findingsByVerse.update((existing) => ({ ...existing, ...findings }));
    checkGroupsByVerse.update((existing) => ({ ...existing, ...groups }));
    checkStatusByVerse.update((existing) => ({ ...existing, ...statuses }));
    if (complete) {
      loadedChapters.update((existing) => ({ ...existing, [chapter]: true }));
      checkingProgress.set({
        running: false, percent: 100, jobId: "", state: "succeeded", error: "", scope: "chapter",
        label: `Stored results, text unchanged: ${checkListLabel(boxesRan(stored.checkGroups))}`,
      });
    }
  }

  // Report/dashboard click-through (see ProjectDashboard's exceptionQueue
  // rows): project.report is scoped to whichever book is currently open,
  // so this never needs to switch books — just land on the right
  // chapter:verse and close the dashboard so the editor is visible.
  async function navigateToFinding(chapter: string, verse: string): Promise<void> {
    showingDashboard = false;
    showingAlignmentReview = false;
    showingReport = false;
    await activateChapter(chapter, verse);
  }

  async function cancelChecks(): Promise<void> {
    if (!activeJobId) return;
    applyJobSnapshot(await bridge.cancelChecks(activeJobId));
  }

  async function stopActiveJob(): Promise<void> {
    const jobId = activeJobId;
    if (!jobId) return;
    await bridge.cancelChecks(jobId);
    // Wait without copying any results (#229), then read them all once.
    let snapshot = await bridge.checkStatus(jobId, Number.MAX_SAFE_INTEGER);
    while (!["succeeded", "failed", "cancelled"].includes(snapshot.state)) {
      await new Promise((resolve) => setTimeout(resolve, 400));
      snapshot = await bridge.checkStatus(jobId, Number.MAX_SAFE_INTEGER);
    }
    snapshot = await bridge.checkStatus(jobId);
    monitorGeneration++;
    activeJobId = "";
    applyJobSnapshot(snapshot);
  }

  async function retryChecks(): Promise<void> {
    const failedJobId = $checkingProgress.jobId;
    if (!failedJobId || activeJobId) return;
    const snapshot = await bridge.retryChecks(failedJobId);
    activeJobId = snapshot.jobId;
    const generation = ++monitorGeneration;
    markJobPending(snapshot);
    applyJobSnapshot(snapshot);
    void monitorJob(snapshot, generation);
  }

  function dismissCheckNotice(): void {
    checkingProgress.set({
      running: false, percent: 0, label: "", jobId: "", state: "idle", error: "", scope: "chapter",
    });
  }

  async function switchChapter(chapter: string) {
    await activateChapter(chapter);
  }

  async function runWholeBook() {
    const chapters = $project?.chapters ?? [];
    await beginChecks("book", chapters);
  }

  async function runChapterChecks() {
    await beginChecks("chapter", [$currentChapter]);
  }

  /** Run Greek Room (#252), on demand and last: the verse in place, the
   *  chapter or the book as a job with the usual progress and cancel. */
  async function runGreekRoom(scope: "verse" | "chapter" | "book") {
    if (scope === "verse") {
      if ($selectedVerse) await runVerseGreekRoom($currentChapter, $selectedVerse);
      return;
    }
    await beginChecks(scope, scope === "book" ? ($project?.chapters ?? []) : [$currentChapter], ["greekroom"]);
  }

  // #118: a finding may name verses of another chapter. Switch first (the
  // page is chapter-scoped and closes itself on a chapter change), then open.
  $: if ($crossVerseRequest && opened) void resolveCrossVerseRequest($crossVerseRequest);
  async function resolveCrossVerseRequest(request: { chapter: string; verses: string[] }) {
    crossVerseRequest.set(null);
    if (request.chapter !== $currentChapter) await activateChapter(request.chapter, request.verses[0]);
    if ($currentChapter !== request.chapter) return;
    openCrossVerse(request.verses[0], request.verses);
  }

  function perfInFlightBookOrProject(): boolean {
    return perfInFlight("book.switch") || perfInFlight("project.open");
  }

  function selectVerse(v: string) {
    selectedVerse.set(v);
  }

  function gotoVerse(v: string) {
    if (($chapterVerseNums[$currentChapter] ?? []).includes(v)) selectedVerse.set(v);
  }

  // The stores are named here, not read inside a function: Svelte 4 re-runs a
  // `$:` statement only for the names written in it, and the old
  // `currentBridgeReference()` call never re-ran, so Bridge never published a
  // verse change to Paratext or Logos (#110).
  // #347: when Paratext has a different project active, the engine stops
  // following and sending navigation and says so in the status; show that
  // sentence once each time it appears (the top bar keeps it as a tooltip).
  let lastMismatchMessage = "";
  $: {
    const message = $navigationStatus.paratext.mismatchMessage ?? "";
    if (message !== lastMismatchMessage) {
      lastMismatchMessage = message;
      if (message) showNavigationNotice(message);
    }
  }
  $: navigationReference = bridgeReference($project, $currentChapter, $selectedVerse);
  $: if (!navigationReference) {
    lastNavigationReference = "";
  } else if (engineStatus === "ready" && navigationReference !== lastNavigationReference) {
    const publishedReference = navigationReference;
    if (publishedReference !== navigationRetryReference) {
      navigationRetryReference = publishedReference;
      navigationRetries = 0;
    }
    lastNavigationReference = publishedReference;
    void bridge.navigationBridgeChanged(publishedReference)
      .then((state) => {
        navigationStatus.set(state);
        navigationRetries = 0;
      })
      .catch((error) => {
        console.error("Could not publish Bridge navigation", error);
        // Retrying by clearing lastNavigationReference re-enters this block, so
        // the attempts must be bounded: a persistently failing publish would
        // otherwise spin an RPC every 800ms for the rest of the session.
        if (navigationRetries >= 3) return;
        navigationRetries += 1;
        if (navigationRetryTimer) clearTimeout(navigationRetryTimer);
        navigationRetryTimer = setTimeout(() => {
          if (navigationReference === publishedReference && lastNavigationReference === publishedReference) {
            lastNavigationReference = "";
          }
        }, 800);
      });
  }

  // Export is enabled only once every chapter in the whole book has been
  // loaded AND fully approved — not just the currently visible one.
  $: bookSummary = bookApprovedSummary();
  $: allApproved =
    $project !== null &&
    bookSummary.totalChapters > 0 &&
    bookSummary.approvedChapters === bookSummary.totalChapters;

  // recompute bookSummary reactively when findings/loadedChapters change
  $: void $findingsByVerse, void $checkStatusByVerse, void $loadedChapters, (bookSummary = bookApprovedSummary());

  $: screen = (
    !opened ? "home"
      : showingAlignmentReview ? "review"
      : showingReport ? "report"
      : showingDashboard ? "dashboard"
      : "editor"
  ) as "home" | "dashboard" | "review" | "editor" | "report";
  $: projectName = $project?.projectName || $project?.bibleName || $project?.bookName || "";
  $: dashboardSubtitle = [
    $project?.targetLanguage,
    bookProgress.length > 0 ? `${bookProgress.length} ${bookProgress.length === 1 ? "book" : "books"}` : "",
  ].filter(Boolean).join(" · ");

  $: alignmentChapterSummary = ($chapterVerseNums[$currentChapter] ?? []).reduce(
    (counts, verse) => {
      const status = $alignmentStatusByVerse[verseKey($currentChapter, verse)] ?? "untouched";
      counts[status] += 1;
      return counts;
    },
    { complete: 0, complete_cross_verse: 0, partial: 0, untouched: 0, invalid: 0 },
  );
  // The status bar's facts, one per line, for its tooltip: a narrow window
  // cuts the bar short (#324).
  $: statusFacts = $project ? [
    `Project: ${$project.bookName}`,
    `Chapter: ${$currentChapter}`,
    `✓ Approved: ${$approvedCount}/${$verseNums.length}`,
    `Word alignment in this chapter: ${alignmentChapterSummary.complete} complete`
      + (alignmentChapterSummary.complete_cross_verse ? ` · ${alignmentChapterSummary.complete_cross_verse} via cross-verse` : "")
      + ` · ${alignmentChapterSummary.partial} partial`
      + (alignmentChapterSummary.invalid ? ` · ${alignmentChapterSummary.invalid} invalid` : ""),
    `${bookSummary.approvedChapters}/${bookSummary.totalChapters} chapters approved`,
    `Greek Room on this chapter (open findings · verses checked): ${$greekRoomChapterSummary.checkedVerses === 0 ? "not run" : `${$greekRoomChapterSummary.openFindings} open · ${$greekRoomChapterSummary.checkedVerses}/${$greekRoomChapterSummary.totalVerses} verses`}`,
  ].join("\n") : "";
</script>

<div class="frame print-expand">
  {#if assigningPath && $project}
    <AssignmentsDialog
      bookName={$project.bookName || $project.bookId.toUpperCase()}
      chapters={$project.chapters}
      users={assigningUsers}
      assignments={$bookAssignments}
      busy={assigningBusy}
      error={assigningError}
      onSet={(chapter, userId) => assign(chapter, userId, false)}
      onClear={(chapter) => assign(chapter, "", false)}
      onApplied={() => void loadDashboard()}
      onClose={() => { assigningPath = ""; }}
    />
  {/if}
  {#if startupDone && needsUserChoice}
    <UserPicker onDone={() => { needsUserChoice = false; }} />
  {/if}
  {#if !startupDone}
    <StartupScreen
      version={startupState?.version ?? ""}
      stages={startupStages}
      failure={startupFailure}
      log={$engineLog}
      paths={startupState
        ? { logPath: startupState.logPath, dataDir: startupState.dataDir, resourceDir: startupState.resourceDir, exePath: startupState.exePath }
        : null}
      onRetry={() => void connectEngine()}
    />
  {/if}
  <TopBar
    {screen}
    {projectName}
    onGoHome={showProjectHome}
    onGoToDashboard={openDashboard}
    onOpenSettings={() => openSettings("ai")}
    onOpenConnections={() => openSettings("connections")}
    onOpenExport={() => exportOpen.set(true)}
    onGenerateReport={openReportScreen}
    onGotoVerse={gotoVerse}
    onChapterChange={switchChapter}
    onBookChange={switchBook}
    exportEnabled={$project !== null}
    bookSwitching={Boolean(openingBook)}
  />

  {#if openingBook}
    <div class="progress-row checking-row">
      <div class="spin" />
      <span class="progress-label">Opening {openingBook}…{openingDetail ? ` ${openingDetail}` : ""}</span>
      <div class="track"><div class="fill indeterminate" /></div>
      <span />
    </div>
  {:else if bookOpenError}
    <div class="progress-row check-notice">
      <span class="check-message">Could not open book: {bookOpenError}</span>
      <span class="grow" />
      <button class="progress-action" on:click={() => (bookOpenError = "")}>Dismiss</button>
    </div>
  {:else if $checkingProgress.running}
    <div class="progress-row checking-row">
      <div class="spin" />
      <span class="progress-label" title={$checkingProgress.label}>
        {$checkingProgress.label} — {$checkingProgress.percent}%
      </span>
      <div class="track"><div class="fill" style="width:{$checkingProgress.percent}%" /></div>
      <button class="progress-action cancel-action" on:click={cancelChecks} disabled={$checkingProgress.state === "cancelling" || $checkingProgress.state === "finalizing"}>
        {$checkingProgress.state === "cancelling" ? "Cancelling…" : "Cancel"}
      </button>
    </div>
  {:else if $checkingProgress.state === "failed" || $checkingProgress.state === "cancelled"}
    <div class="progress-row check-notice">
      <span class="check-message" title={$checkingProgress.error}>{$checkingProgress.error || ($checkingProgress.state === "cancelled" ? "Checking was cancelled." : "Checking failed.")}</span>
      <span class="grow" />
      <button class="progress-action" on:click={retryChecks}>Retry</button>
      <button class="progress-action" on:click={dismissCheckNotice}>Dismiss</button>
    </div>
  {/if}

  {#if screen === "home"}
    <ImportScreen onOpened={handleOpened} {droppedPath} {dropSequence} />
  {:else if screen === "dashboard"}
    {#if bookProgress.length > 1}
      <div class="collection-qa-host">
        <CollectionQaPanel bookCount={bookProgress.length} onOpenBook={enterBookFromDashboard} />
      </div>
    {/if}
    <ProjectDashboard
      {projectName}
      subtitle={dashboardSubtitle}
      books={bookProgress}
      loading={dashboardLoading}
      error={dashboardError}
      onSelectBook={enterBookFromDashboard}
      onPreviewBook={previewBookOnDashboard}
      onRetry={loadDashboard}
      {report}
      reportLoading={reportLoading}
      reportError={reportError}
      openBookName={$project?.bookName || $project?.bookId?.toUpperCase() || ""}
      onLoadReport={loadReport}
      onNavigateToFinding={navigateToFinding}
      myUserId={$localUserId}
      canAssign={localUserRole === "project_admin"}
      onAssign={(path) => void openAssignments(path)}
    />
  {:else if screen === "report"}
    <ProjectReportScreen
      {projectName}
      report={qaReport}
      job={qaReportJob}
      error={qaReportError}
      onGenerate={generateReport}
      onCancel={cancelReport}
      onNavigate={navigateToReportRow}
      triage={triageEntries}
      {triageJob}
      {triageAvailable}
      {triageUnavailableReason}
      {triageError}
      {triageThreshold}
      onRunTriage={runTriage}
      onCancelTriage={cancelTriage}
      onTriageThreshold={setTriageThreshold}
      onTriageOverride={overrideTriage}
    />
  {:else if screen === "review"}
    {#key $project?.path}
      <AlignmentReview
        chapter={$currentChapter}
        verse={$selectedVerse}
        onClose={() => (showingAlignmentReview = false)}
      />
    {/key}
  {:else}
    <div class="body">
      <!-- The toolbar spans the text and the reference panel, so the two start
           at the same height under it. The review panel keeps the full height. -->
      <div class="work-col" style:--verse-scale={$textScale}>
        {#if $projectRoles?.effectiveRole === "reporter"}
          <!-- #279: the engine refuses every change; say so before a click finds out. -->
          <p class="role-banner" role="status">You are a reporter on this project: you can read, report and export, and changes are refused.</p>
        {/if}
        <div class="editor-toolbar">
          <span>Chapter {$currentChapter} of {$project?.chapters.length ?? "?"}</span>
          <button class="whole-book-btn" on:click={runWholeBook} disabled={Boolean(activeJobId)}
            title={`Run ${checkListLabel($selectedEditorChecks)} on every chapter`}>
            {$checkingProgress.scope === "book" && $checkingProgress.running ? "Running…" : "Run whole book"}
          </button>
          <CheckMenu
            disabled={Boolean(activeJobId) || $checkingProgress.running}
            verse={$selectedVerse ? `${$currentChapter}:${$selectedVerse}` : ""}
            chapter={$currentChapter}
            onRunChapter={runChapterChecks}
            onRunBook={runWholeBook}
            onRunGreekRoom={runGreekRoom}
          />
          <button class="whole-book-btn" on:click={() => (showingAlignmentReview = true)}>
            Alignment Review
          </button>
          <button
            class="whole-book-btn"
            on:click={() => openCrossVerse($selectedVerse ?? "", $selectedVerseSet)}
            disabled={!$selectedVerse}
            title={$selectedVerseSet.length > 1
              ? `Open the ${$selectedVerseSet.length} selected verses side by side`
              : "Align several verses of this chapter side by side (Ctrl-click or Shift-click verses to pick them first)"}
          >
            Cross-verse alignment{#if $selectedVerseSet.length > 1}&nbsp;({$selectedVerseSet.length}){/if}
          </button>
          <AutoAlignChapterButton
            chapter={$currentChapter}
            disabled={Boolean(activeJobId)}
            onOpenReview={(verse, verses) => openCrossVerse(verse, verses)}
            onFinished={() => { void activateChapter($currentChapter); }}
          />
          <span class="toolbar-divider" aria-hidden="true" />
          <button class="whole-book-btn" class:on={$sidePanels.reference.open} aria-pressed={$sidePanels.reference.open}
            title="Show a reference Bible (an Old Version) beside the text"
            on:click={() => toggleSidePanel("reference")}>Ref.</button>
          <button class="whole-book-btn" class:on={$rawView} aria-pressed={$rawView}
            title="Show each verse exactly as stored, USFM markers included"
            on:click={() => rawView.update((on) => !on)}>Raw</button>
          <button class="whole-book-btn" aria-haspopup="menu" disabled={!$project}
            title="Bookmark this verse, or go to a bookmark or a recent chapter"
            on:click={openPlacesMenu}>★ Bookmarks</button>
          <span class="text-size" role="group" aria-label="Text size">
            <button class="whole-book-btn" title="Smaller text" aria-label="Smaller text"
              disabled={$textScale === TEXT_SCALES[0]} on:click={() => bumpTextScale(-1)}>A−</button>
            <button class="whole-book-btn" title="Larger text" aria-label="Larger text"
              disabled={$textScale === TEXT_SCALES[TEXT_SCALES.length - 1]} on:click={() => bumpTextScale(1)}>A+</button>
          </span>
        </div>
        <!-- The text, then the side-panel columns (Benz, 2026-10-09): each
             opened from the rail at the far right, resized or closed by
             dragging its left edge; several may be open at once. All start
             under the toolbar, level with the text. -->
        <div class="work-row">
          <!-- #324: the verse list never goes below this width; the side
               panels shrink and then fold to the rail first (panelFit.ts). -->
          <div class="editor-col" style:min-width="{$verseMin}px">
            <VerseList onSelect={selectVerse} onNavigate={navigateToReportRow} />
          </div>
          <!-- #389: the columns run in the reviewer's order (sidePanelOrder,
               ◂ ▸ in each panel's bar); the rail lists them the same way.
               Review stays mounted with no project, as before. -->
          {#each $sidePanelOrder as panelId (panelId)}
            {#if panelId === "review"}
              <SidePanel id="review" label="Review" keepMounted>
                <ReviewPanel onNavigate={navigateToReportRow} />
              </SidePanel>
            {:else if $project}
              {#if panelId === "source"}
                <SidePanel id="source" label="Source text">
                  {#key $project.path}<SourceTextPanel onSelectVerse={selectVerse} />{/key}
                </SidePanel>
              {:else if panelId === "reference"}
                <SidePanel id="reference" label="Reference">
                  {#key $project.path}
                    <ReferencePanel onOpenSettings={() => openSettings("languageQa")} onSelectVerse={selectVerse} />
                  {/key}
                </SidePanel>
              {:else if panelId === "languageQa"}
                <SidePanel id="languageQa" label="Language QA" keepMounted>
                  {#key $project.path}
                    <LanguageQaPanel projectPath={$project.path} onNavigate={navigateToReportRow} docked />
                  {/key}
                </SidePanel>
              {:else if panelId === "paratext"}
                <SidePanel id="paratext" label="Paratext notes">
                  {#key $project.path}<ParatextNotesPanel />{/key}
                </SidePanel>
              {/if}
            {/if}
          {/each}
          <SideRail onOpenSettings={() => openSettings("ai")} />
        </div>
      </div>
    </div>

    <div class="statusbar">
      {#if $project}
        <!-- One line (#324): the chapter facts truncate with an ellipsis in a
             narrow window, the full line in the tooltip. -->
        <span class="status-facts" title={statusFacts}>
        <span>Project: <b>{$project.bookName}</b></span>
        <span>Chapter: <b>{$currentChapter}</b></span>
        <span style="color:var(--success);">✓ Approved: {$approvedCount}/{$verseNums.length}</span>
        <span>
          Alignment: {alignmentChapterSummary.complete} complete{#if alignmentChapterSummary.complete_cross_verse} · {alignmentChapterSummary.complete_cross_verse} via cross-verse{/if} · {alignmentChapterSummary.partial} partial
          {#if alignmentChapterSummary.invalid} · {alignmentChapterSummary.invalid} invalid{/if}
        </span>
        <span>{bookSummary.approvedChapters}/{bookSummary.totalChapters} chapters approved</span>
        <span>
          Greek Room: {$greekRoomChapterSummary.checkedVerses === 0 ? "not run" : `${$greekRoomChapterSummary.openFindings} open · ${$greekRoomChapterSummary.checkedVerses}/${$greekRoomChapterSummary.totalVerses} verses`}
        </span>
        </span>
      {/if}
      <span class="grow" />
      {#if $project && opened}
        <button class="diagnostics-btn" on:click={toggleLanguageQaPanel}
          title="Open or close the Language QA panel">
          Language QA{#if $languageQaChannel.error}: unavailable{:else if $languageQaChannel.status}: {$languageQaChannel.status.state}{#if $languageQaChannel.status.totalFindings} · {$languageQaChannel.status.totalFindings}{/if}{/if}
        </button>
      {/if}
      {#if engineNotice}<span class="engine-notice" title={engineNotice}>{engineNotice}</span>{/if}
      <span>Engine: {engineStatus}</span>
      <button class="diagnostics-btn" on:click={() => diagnosticsOpen.set(true)}>
        Diagnostics
        {#if $engineLog.some((entry) => entry.level === "error")}<span class="error-dot" />{/if}
      </button>
    </div>
  {/if}

  {#if $project && opened}
    {#if screen !== "editor"}
      <!-- The editor docks Language QA in a side column; the other screens
           keep the floating panel and its launcher. -->
      {#key $project.path}
        <LanguageQaPanel projectPath={$project.path} onNavigate={navigateToReportRow} />
      {/key}
    {/if}
    <ScopeNotice />
    {#if $scopeDialog}<ScopeConfirmDialog />{/if}
  {/if}

  {#if $project && $crossVerseOpen && $crossVerseAnchor}
    {#key `${$project.path}:${$currentChapter}:${$crossVerseAnchor}`}
      <CrossVerseAlignmentModal
        chapter={$currentChapter}
        verse={$crossVerseAnchor}
        initialVerses={$crossVerseInitialVerses}
        onClose={closeCrossVerse}
      />
    {/key}
  {/if}

  {#if placesMenu}
    <FindingContextMenu x={placesMenu.x} y={placesMenu.y} findingLabel="Bookmarks and recent chapters"
      actions={placesActions} on:action={onPlacesAction} on:close={() => (placesMenu = null)} />
  {/if}

  {#if $settingsOpen}
    <SettingsModal initialPane={settingsInitialPane} onClose={() => settingsOpen.set(false)} />
  {/if}

  <!-- #372: the in-app confirmation (chapter/book AI review, Remove key).
       Outside the project block: Settings can ask with no project open. -->
  {#if $confirmRequest}<ConfirmDialog />{/if}

  {#if $diagnosticsOpen}
    <DiagnosticsPanel onClose={() => diagnosticsOpen.set(false)} />
  {/if}

  {#if $exportOpen}
    <ExportModal reviewComplete={allApproved} onClose={() => exportOpen.set(false)} />
  {/if}

  {#if draggingOver}
    <div class="global-drop" role="presentation">Drop to review this project source</div>
  {/if}
  {#if dropError}
    <div class="drop-error">{dropError}<button on:click={() => (dropError = "")}>Dismiss</button></div>
  {/if}
</div>

<style>
  .frame { width: 100vw; height: 100vh; background: var(--bg); display: flex; flex-direction: column; position: relative; overflow: hidden; }
  .progress-row { height: 32px; background: var(--surface-2); border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 10px; padding: 0 16px; font-size: var(--fs-xs); color: var(--text-2); flex-shrink: 0; }
  .checking-row { display: grid; grid-template-columns: 12px minmax(220px, 320px) minmax(120px, 1fr) 84px; }
  .progress-label { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .spin { width: 12px; height: 12px; border-radius: 50%; border: 2px solid var(--accent-bg); border-top-color: var(--accent); animation: spin 0.8s linear infinite; flex-shrink: 0; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .track { width: 100%; height: 6px; background: #EEF0F3; border-radius: 4px; overflow: hidden; }
  .fill { height: 100%; background: var(--accent); transition: width 0.3s; }
  .indeterminate { width: 35%; animation: slide 1.1s ease-in-out infinite; }
  @keyframes slide { from { transform: translateX(-100%); } to { transform: translateX(300%); } }
  .progress-action { border: 1px solid var(--border-strong); background: var(--surface); color: var(--text-2); border-radius: 5px; padding: 2px 8px; font-size: var(--fs-xs); cursor: pointer; }
  .cancel-action { width: 84px; }
  .progress-action:disabled { opacity: 0.55; cursor: wait; }
  .check-notice { color: var(--danger); height: auto; min-height: 32px; max-height: 96px; align-items: flex-start; padding-top: 7px; padding-bottom: 7px; }
  .check-message { flex: 1; min-width: 0; max-height: 78px; overflow: auto; white-space: normal; overflow-wrap: anywhere; line-height: 1.35; }
  .body { flex: 1; display: flex; overflow: hidden; }
  /* A 66-book table must not push the dashboard off screen: it scrolls. */
  .collection-qa-host { flex-shrink: 0; max-height: 40vh; overflow: auto; padding: 12px 16px 0; background: var(--bg); }
  .work-col { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; }
  .work-row { flex: 1; min-height: 0; display: flex; overflow: hidden; }
  .editor-col { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; }
  .text-size { display: inline-flex; gap: 2px; }
  /* min-height + wrap, not a fixed height: on a narrow window the items used to
     shrink, break their labels onto two lines and get clipped by the 34px box.
     Now each item keeps its label on one line and the row wraps instead. */
  .editor-toolbar { min-height: 34px; background: var(--surface-2); border-bottom: 1px solid var(--border); display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; padding: 4px 16px; font-size: var(--fs-xs); color: var(--text-2); flex-shrink: 0; }
  .editor-toolbar > * { white-space: nowrap; flex-shrink: 0; }
  .whole-book-btn { font-size: var(--fs-xs); font-weight: 600; padding: 4px 10px; border-radius: 6px; border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); cursor: pointer; }
  .whole-book-btn:disabled { opacity: 0.6; cursor: not-allowed; }
  .whole-book-btn.on { background: var(--accent-bg); border-color: var(--accent); color: var(--accent); }
  .role-banner { margin: 0; padding: 6px 14px; background: var(--accent-bg); color: var(--accent); font-size: var(--fs-xs); font-weight: 600; border-bottom: 1px solid var(--border); }
  .toolbar-divider { width: 1px; height: 20px; background: var(--border-strong); }
  .grow { flex: 1; }
  .statusbar { height: 28px; background: var(--surface); border-top: 1px solid var(--border); display: flex; align-items: center; padding: 0 16px; gap: 16px; font-size: var(--fs-xs); color: var(--text-2); flex-shrink: 0; overflow: hidden; white-space: nowrap; }
  .statusbar > * { flex-shrink: 0; }
  /* The facts give way first, then an engine notice; buttons keep their labels. */
  .statusbar > .status-facts { flex-shrink: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .status-facts > span + span { margin-left: 16px; }
  .statusbar > .grow { flex-shrink: 1; min-width: 0; }
  .engine-notice { color: var(--warning); font-weight: 600; }
  .statusbar > .engine-notice { flex-shrink: 1; min-width: 40px; overflow: hidden; text-overflow: ellipsis; }
  .diagnostics-btn { position: relative; font-size: var(--fs-2xs); font-weight: 650; padding: 3px 9px; border-radius: 999px; border: 1px solid var(--border-strong); background: var(--surface-2); color: var(--text-2); cursor: pointer; display: flex; align-items: center; gap: 5px; }
  .diagnostics-btn:hover { background: var(--surface); }
  .error-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--danger); }
  .global-drop { position: absolute; inset: 12px; z-index: 100; display: grid; place-items: center; border: 3px dashed var(--accent); border-radius: 14px; background: color-mix(in srgb, var(--accent-bg) 92%, transparent); color: var(--accent); font-size: var(--fs-2xl); font-weight: 750; pointer-events: none; }
  .drop-error { position: absolute; z-index: 101; left: 50%; bottom: 42px; transform: translateX(-50%); display: flex; align-items: center; gap: 14px; border: 1px solid var(--danger); border-radius: 8px; background: var(--surface); color: var(--danger); padding: 9px 12px; font-size: var(--fs-xs); box-shadow: 0 8px 24px rgba(0,0,0,.14); }
  .drop-error button { border: 0; background: transparent; color: var(--accent); cursor: pointer; font-size: var(--fs-xs); }
</style>
