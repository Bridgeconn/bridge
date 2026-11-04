import { invoke } from "@tauri-apps/api/core";
import { emitTo, listen } from "@tauri-apps/api/event";
import type { SidePanelId } from "./editorPrefs";
import type { Readable } from "svelte/store";
import type * as stores from "./stores";
import type { LanguageQaChannel } from "./languageQaInline";
import type { SidePanels } from "./editorPrefs";
type StoreValue<T> = T extends Readable<infer V> ? V : never;
export interface PanelContext {
  project: StoreValue<typeof stores.project>; chapter: string; verse: string | null; open: boolean;
  chapters: StoreValue<typeof stores.chapterVerseNums>; texts: StoreValue<typeof stores.verseTexts>;
  display: StoreValue<typeof stores.verseDisplay>; findings: StoreValue<typeof stores.findingsByVerse>;
  native: StoreValue<typeof stores.nativeChecksByVerse>; ai: StoreValue<typeof stores.aiCheckReviewsByVerse>;
  checks: StoreValue<typeof stores.checkStatusByVerse>; alignment: StoreValue<typeof stores.alignmentStatusByVerse>;
  languageQa: LanguageQaChannel; user: string; mode: StoreValue<typeof stores.reviewerMode>; panels: SidePanels;
  focused: string | null; selection: string[]; progress: StoreValue<typeof stores.checkingProgress>;
  revisions: StoreValue<typeof stores.alignmentRevisionByVerse>; inline: StoreValue<typeof stores.languageQaFindingsByVerse>;
}
export const panelLabel = (id: SidePanelId) => `panel-${id}`;
export const panelWindow = (id: SidePanelId, action: "open" | "hide") => invoke<void>("panel_window", { panel: id, action });
export const panelDesktop = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
export interface PanelMessage { kind: "ready" | "close" | "dock" | "navigate" | "settings" | "changed" | "edit" | "alignment" | "reviewQueue" | "focus"; id: SidePanelId; path?: string; chapter?: string; verse?: string; book?: string; findingId?: string; caret?: { start: number; end: number } | null; acceptFindingId?: string }
export const sendPanelMessage = (message: PanelMessage) => emitTo("main", "panel-message", message);
export const onPanelMessage = (handler: (message: PanelMessage) => void) => listen<PanelMessage>("panel-message", e => handler(e.payload));
