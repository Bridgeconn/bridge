<script lang="ts">
  import { observePanelMutations } from "../api/bridgeClient";
  import { onMount, setContext, tick } from "svelte";
  import { get } from "svelte/store";
  import { editingChapter, editingVerse, cancelVerseEdit, currentEditIntent } from "../verseEditor";
  import { alignmentOpen, alignmentKey } from "../alignmentUi";
  import { paratextReviewQueueOpen } from "../paratextNotes";
  import { listen } from "@tauri-apps/api/event";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { project, currentChapter, selectedVerse, chapterVerseNums, verseTexts, verseDisplay, findingsByVerse,
    nativeChecksByVerse, aiCheckReviewsByVerse, checkStatusByVerse, alignmentStatusByVerse, localUserId, reviewerMode, resetBookState,
    focusedFindingId, selectedVerseSet, checkingProgress, alignmentRevisionByVerse, languageQaFindingsByVerse } from "../stores";
  import { languageQaChannel } from "../languageQaInline";
  import { SIDE_PANEL_ORDER, isAddedReference, isReferencePanel, type SidePanelId, type SidePanels } from "../editorPrefs";
  import { folderName, projectReferenceName } from "../referenceNames";
  import { sendPanelMessage, panelLabel, type PanelContext } from "../panelWindow";
  import { setWindowProjectPath } from "../reviewProjectGuard";
  import { answerConfirmation, confirmRequest } from "../confirmAction";
  import SourceTextPanel from "./SourceTextPanel.svelte";
  import ReferencePanel from "./ReferencePanel.svelte";
  import ParatextNotesPanel from "./ParatextNotesPanel.svelte";
  import ReviewPanel from "./ReviewPanel.svelte";
  import ConfirmDialog from "./ConfirmDialog.svelte";
  import WindowBar from "./WindowBar.svelte";
  import type { ProjectInfo } from "../types/finding";
  const requested = new URLSearchParams(window.location.search).get("panel") as SidePanelId;
  const id = SIDE_PANEL_ORDER.includes(requested) ? requested : null;
  let open = false, path = "", error = "";
  let receiving = false;
  const NAMES: Record<SidePanelId, string> = { source: "Source text", reference: "Reference", reference2: "Reference", reference3: "Reference", reference4: "Reference", paratext: "Paratext notes", review: "Review" };
  // #519: the main window's panels, for an added reference tab's folder. This
  // window's own `sidePanels` store is not the main window's and is left alone.
  let panels: SidePanels | null = null;
  $: referenceFolder = id && isAddedReference(id) ? panels?.[id]?.folder : undefined;
  // A reference window is named after its reference, as its tab is.
  $: windowTitle = !id ? "Bridge"
    : isReferencePanel(id) ? ((id === "reference" ? $projectReferenceName : folderName(referenceFolder)) || NAMES[id]) : NAMES[id];
  // The folder chosen here goes to the main window, which keeps it and sends it back.
  function chooseReferenceFolder(folder: string): void { if (id) void sendPanelMessage({ kind: "referenceFolder", id, path, folder }); }
  const message = (kind: "dock" | "close" | "settings" | "changed") => { if (id) void sendPanelMessage({ kind, id, path }); };
  function navigate(book: string, chapter: string, verse: string) { if (id) return sendPanelMessage({ kind: "navigate", id, path, book, chapter, verse }); }
  setContext("panel-window", {
    dock: () => message("dock"), close: () => message("close"),
    // #511: this window's stores are its own copies; the alignment tabs are in
    // the main window, which reloads a verse only when it is told it changed.
    alignmentChanged: (chapter: string, verse: string) => { if (id) void sendPanelMessage({ kind: "alignmentChanged", id, path, chapter, verse }); },
  });
  onMount(() => {
    observePanelMutations(() => message("changed"));
    let disposed = false; const stops: (() => void)[] = [];
    const keep = (stop: () => void) => { if (disposed) stop(); else stops.push(stop); };
    void (async () => {
      if (!id) throw new Error("Unknown editor panel");
      keep(await listen<PanelContext>(`panel-context-${id}`, ({ payload: value }) => {
        receiving = true;
        const nextPath = (value.project as ProjectInfo | null)?.path || "";
        if (nextPath !== path || !value.open) { answerConfirmation(false); if (nextPath !== path) resetBookState(); }
        path = nextPath; open = value.open; panels = value.panels; setWindowProjectPath(path || "__no_project__");
        project.set(value.project); currentChapter.set(value.chapter); selectedVerse.set(value.verse);
        chapterVerseNums.set(value.chapters); verseTexts.set(value.texts); verseDisplay.set(value.display); findingsByVerse.set(value.findings);
        nativeChecksByVerse.set(value.native); aiCheckReviewsByVerse.set(value.ai); checkStatusByVerse.set(value.checks); alignmentStatusByVerse.set(value.alignment);
        languageQaChannel.set(value.languageQa); localUserId.set(value.user); reviewerMode.set(value.mode);
        focusedFindingId.set(value.focused); selectedVerseSet.set(value.selection); checkingProgress.set(value.progress);
        alignmentRevisionByVerse.set(value.revisions); languageQaFindingsByVerse.set(value.inline);
        receiving = false;
      }, { target: panelLabel(id) }));
      keep(await getCurrentWindow().onCloseRequested(event => { event.preventDefault(); message("close"); }));
      keep(editingChapter.subscribe(chapter => {
        if (!chapter || !id) return;
        const expected = path;
        void tick().then(async () => {
          const verse = get(editingVerse);
          if (expected === path && verse) await sendPanelMessage({ kind: "edit", id, path, ...currentEditIntent(), book: get(project)?.bookId });
          cancelVerseEdit();
        });
      }));
      keep(focusedFindingId.subscribe(findingId => {
        if (receiving || !findingId || !id) return;
        void sendPanelMessage({ kind: "focus", id, path, findingId });
      }));
      keep(alignmentOpen.subscribe(value => {
        if (!value || !id) return;
        const key = get(alignmentKey);
        if (key) { const [chapter, verse] = key.split(":"); void sendPanelMessage({ kind: "alignment", id, path, chapter, verse }); }
        alignmentOpen.set(false);
      }));
      keep(paratextReviewQueueOpen.subscribe(value => {
        if (!value || !id) return;
        void sendPanelMessage({ kind: "reviewQueue", id, path }); paratextReviewQueueOpen.set(false);
      }));
      if (!disposed) await sendPanelMessage({ kind: "ready", id });
    })().catch(cause => error = String(cause));
    return () => { observePanelMutations(null); disposed = true; stops.forEach(stop => stop()); answerConfirmation(false); };
  });
</script>
<main class="panel-window">
  <!-- 2026-11-14 (Joel): the app's own title bar, the one Close this window has. -->
  <WindowBar title={windowTitle} onClose={() => message("close")} />
  {#if error}<p role="alert">{error}</p>{/if}
  {#if open && $project}
    {#key path}
      {#if id === "source"}<SourceTextPanel onSelectVerse={verse => { void navigate(($project?.bookId || ""), $currentChapter, verse); }} />
      {:else if id && isReferencePanel(id)}<ReferencePanel {id} folder={referenceFolder} onChooseFolder={chooseReferenceFolder} onChapterChange={chapter => { void navigate(($project?.bookId || ""), chapter, ""); }} onSelectVerse={verse => { void navigate(($project?.bookId || ""), $currentChapter, verse); }} onOpenSettings={() => message("settings")} />
      {:else if id === "paratext"}<ParatextNotesPanel />
      {:else if id === "review"}<ReviewPanel onNavigate={navigate} />{/if}
    {/key}
  {:else}<p>Open this panel from the Scripture editor.</p>{/if}
</main>
{#if $confirmRequest}<ConfirmDialog />{/if}
<style>.panel-window { height: 100vh; display: flex; flex-direction: column; overflow: hidden; min-width: 0; background: var(--surface); }</style>
