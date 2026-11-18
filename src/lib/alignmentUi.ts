// Alignment-modal open state, shared between ReviewPanel.svelte (the
// "⇄ Align words" button and the modal itself) and VerseList.svelte (the
// per-row alignment glyph, issue #70) so either entry point can drive the
// same modal without reaching into the other component's internals --
// same reasoning as verseEditor.ts's edit-session state.
//
// The Cross-verse alignment page (#116) follows the same pattern: the editor
// toolbar button in App.svelte and the link inside AlignmentModal both open
// it through `openCrossVerse`, and App.svelte hosts the one instance.
import { writable, get } from "svelte/store";
import { alignmentRevisionByVerse, checkingProgress, verseKey } from "./stores";
import { editSaving, recheckingKey } from "./verseEditor";
import { tabRequest } from "./editorPrefs";
import { alignmentBusy as editorBusy, alignmentDetached } from "./alignmentWindow";

export const alignmentOpen = writable(false);
export const alignmentKey = writable("");

export const crossVerseOpen = writable(false);
/** The verse the page was opened on; it centres the default range. */
export const crossVerseAnchor = writable("");
/** Verses the page should start with instead of anchor ±1 (#118): the
 *  editor's multi-selection, or a finding's references. Empty = default. */
export const crossVerseInitialVerses = writable<string[]>([]);
/** A request to open the page on a chapter that may not be the current one.
 *  App.svelte resolves it: switch chapter if needed, then openCrossVerse. */
export const crossVerseRequest = writable<{ chapter: string; verses: string[] } | null>(null);

/** True while alignment data underneath an editor is unstable: a background
 * check run, an in-flight edit save, or a post-edit recheck. */
function alignmentBusy(): boolean {
  return get(checkingProgress).running || Boolean(get(editSaving)) || Boolean(get(recheckingKey)) || get(editorBusy);
}

/** What the two alignment tabs draw (2026-11-15): the verse, and which of
 *  the two editors are open in the main window (an editor in its own window
 *  is not), or null while neither is. AlignmentHost owns it; AlignmentTabPane,
 *  in the work area, draws it. */
export interface AlignmentPaneState { path: string; chapter: string; verse: string; word: boolean; cross: boolean; canDetach: boolean }
export const alignmentPane = writable<AlignmentPaneState | null>(null);

/** The two editors are two tabs (Joel, 2026-11-15): "Word alignment" (tab id
 *  `alignment`) and "Cross-verse" (`crossVerse`). Both can be open at once,
 *  side by side; they read and write the same alignment, so each reloads when
 *  the other saves (watchAlignmentChanges) and waits while the other is
 *  saving (alignmentBusyElsewhere). */
export type AlignmentMode = "word" | "cross";
const TAB_OF = { word: "alignment", cross: "crossVerse" } as const;

/** Which editor the one separate Alignment window holds while
 *  `alignmentDetached` is true; the other stays a tab. */
export const alignmentDetachedMode = writable<AlignmentMode>("word");
export function detachAlignment(mode: AlignmentMode): void {
  alignmentDetachedMode.set(mode);
  alignmentDetached.set(true);
}

/** `alignmentBusy`, counted: with two editors open, one finishing must not
 *  clear the other's save. Each holder (an editor, the separate window) says
 *  when it starts and stops. */
const busyHolders = new Set<object>();
export function holdAlignmentBusy(holder: object, busy: boolean): void {
  if (busy) busyHolders.add(holder); else busyHolders.delete(holder);
  editorBusy.set(busyHolders.size > 0);
}
/** True while an editor other than `holder` is saving. */
export function alignmentBusyElsewhere(holder: object): boolean {
  for (const other of busyHolders) if (other !== holder) return true;
  return false;
}

/** Tell an open editor that a verse it shows was written somewhere else: the
 *  other alignment tab, the verse editor, an automatic pass. `keys` are the
 *  "chapter:verse" keys on screen; a change made while `ownBusy()` is the
 *  editor's own and is not reported. Returns the unsubscribe. */
export function watchAlignmentChanges(keys: () => string[], ownBusy: () => boolean, onOutside: () => void): () => void {
  let seen = get(alignmentRevisionByVerse);
  return alignmentRevisionByVerse.subscribe((values) => {
    const before = seen;
    seen = values;
    if (ownBusy()) return;
    if (keys().some((key) => (values[key] ?? 0) !== (before[key] ?? 0))) onOutside();
  });
}

/** Ask the work area to show one of the two tabs (editorTabs.ts): the way
 *  to a tab that is already open, from the rail's menu or the other tab's bar. */
export function showAlignmentTab(mode: AlignmentMode): void {
  tabRequest.update((request) => ({ id: TAB_OF[mode], seq: request.seq + 1 }));
}

/** Close both alignment editors: a project switch. */
export function closeAlignment(): void {
  alignmentOpen.set(false);
  closeCrossVerse();
  busyHolders.clear();
  editorBusy.set(false);
}

/** Close the single-verse editor: its tab's close, or its own. */
export function closeWordAlignment(): void {
  alignmentOpen.set(false);
}

/** Guards match ReviewPanel's original "Align words" button: no verse, a
 * background check run, an in-flight edit save, or a post-edit recheck all
 * mean the alignment data underneath the editor isn't stable yet; so does a
 * save inside the alignment editor itself.
 *
 * The editor is the work area's Alignment tab (2026-11-15), not a dialog, and
 * no longer lives in the Review panel, so Review is not opened with it (#306
 * did that, and closing the dialog left Review open). The cross-verse page, if
 * open, stays open in its own tab. */
export function openAlignment(chapter: string, verse: string): boolean {
  if (!verse || alignmentBusy()) return false;
  alignmentKey.set(verseKey(chapter, verse));
  alignmentOpen.set(true);
  showAlignmentTab("word");
  return true;
}

/** Same guards as openAlignment. The single-verse editor, if open, stays
 * open in its own tab. */
export function openCrossVerse(verse: string, verses: readonly string[] = []): boolean {
  if (!verse || alignmentBusy()) return false;
  crossVerseInitialVerses.set(verses.length > 1 ? [...verses] : []);
  crossVerseAnchor.set(verse);
  crossVerseOpen.set(true);
  showAlignmentTab("cross");
  return true;
}

/** From a finding (#118): the references may sit in another chapter, so the
 *  request goes through App.svelte, which owns chapter navigation. */
export function requestCrossVerse(chapter: string, verses: readonly string[]): boolean {
  if (!chapter || verses.length === 0 || alignmentBusy()) return false;
  crossVerseRequest.set({ chapter, verses: [...verses] });
  return true;
}

export function closeCrossVerse(): void {
  crossVerseOpen.set(false);
  crossVerseInitialVerses.set([]);
}
