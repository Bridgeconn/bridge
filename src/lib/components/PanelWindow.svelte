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
  import { SIDE_PANEL_ORDER, type SidePanelId } from "../editorPrefs";
  import { sendPanelMessage, panelLabel, type PanelContext } from "../panelWindow";
  import { setWindowProjectPath } from "../reviewProjectGuard";
  import { answerConfirmation, confirmRequest } from "../confirmAction";
  import SourceTextPanel from "./SourceTextPanel.svelte";
  import ReferencePanel from "./ReferencePanel.svelte";
  import LanguageQaPanel from "./LanguageQaPanel.svelte";
  import ParatextNotesPanel from "./ParatextNotesPanel.svelte";
  import ReviewPanel from "./ReviewPanel.svelte";
  import ConfirmDialog from "./ConfirmDialog.svelte";
  import type { ProjectInfo } from "../types/finding";
  const requested = new URLSearchParams(window.location.search).get("panel") as SidePanelId;
  const id = SIDE_PANEL_ORDER.includes(requested) ? requested : null;
  let open = false, path = "", error = "";
  let receiving = false;
  const message = (kind: "dock" | "close" | "settings" | "changed") => { if (id) void sendPanelMessage({ kind, id, path }); };
  function navigate(book: string, chapter: string, verse: string) { if (id) return sendPanelMessage({ kind: "navigate", id, path, book, chapter, verse }); }
  setContext("panel-window", { dock: () => message("dock"), close: () => message("close") });
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
        path = nextPath; open = value.open; setWindowProjectPath(path || "__no_project__");
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
{#if error}<p role="alert">{error}</p>{/if}
<main class="panel-window">
  {#if open && $project}
    {#key path}
      {#if id === "source"}<SourceTextPanel onSelectVerse={verse => { void navigate(($project?.bookId || ""), $currentChapter, verse); }} />
      {:else if id === "reference"}<ReferencePanel onSelectVerse={verse => { void navigate(($project?.bookId || ""), $currentChapter, verse); }} onOpenSettings={() => message("settings")} />
      {:else if id === "languageQa"}<LanguageQaPanel projectPath={path} onNavigate={navigate} docked />
      {:else if id === "paratext"}<ParatextNotesPanel />
      {:else if id === "review"}<ReviewPanel onNavigate={navigate} />{/if}
    {/key}
  {:else}<p>Open this panel from the Scripture editor.</p>{/if}
</main>
{#if $confirmRequest}<ConfirmDialog />{/if}
<style>.panel-window { height: 100vh; display: flex; flex-direction: column; overflow: hidden; min-width: 0; background: var(--surface); }</style>
