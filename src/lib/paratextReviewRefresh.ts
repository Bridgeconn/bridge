import { get } from "svelte/store";
import { bridge } from "./api/bridgeClient";
import { applyEngineChanges } from "./verseEditor";
import { alignmentStatusByVerse, headingsByVerse, historyCountByVerse, noteAlignmentChanged, project, verseKey } from "./stores";
import type { ParatextReviewDecision } from "./types/paratext";

/** #445: the queue writes through the engine; the editor must read its saved
 * text/display, not keep the chapter cache or reconstruct a replacement.
 * The operation may finish after the reviewer has switched books/projects.
 */
export async function refreshParatextReviewEditor(expectedPath: string, decision: ParatextReviewDecision): Promise<void> {
  const sameProject = () => {
    const open = get(project);
    return Boolean(expectedPath) && open?.path === expectedPath
      && open.bookId.toLowerCase() === decision.book?.toLowerCase();
  };
  if (!sameProject() || !decision.chapter || !decision.verse || decision.region === "introduction") return;
  if (decision.bridgeCopy === "none") return;
  const chapter = await bridge.chapterVerseData(decision.chapter);
  if (!sameProject()) return;
  const key = verseKey(decision.chapter, decision.verse);
  const headingOnly = decision.region === "heading" || decision.region === "structure" || decision.bridgeCopy === "heading";
  if (!headingOnly) {
    const saved = chapter.verses[decision.verse];
    if (!saved) throw new Error("The saved verse could not be read.");
    applyEngineChanges([{ chapter: decision.chapter, verse: decision.verse, newText: saved.text, display: saved.display }]);
    alignmentStatusByVerse.update((values) => ({ ...values, [key]: saved.alignmentStatus }));
    noteAlignmentChanged(key);
  }
  headingsByVerse.update((values) => ({ ...values, [key]: chapter.headings?.[decision.verse] ?? [] }));
  const edits = chapter.editCounts?.[decision.verse];
  if (edits !== undefined) historyCountByVerse.update((values) => ({ ...values, [key]: edits }));
}
