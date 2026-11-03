import { invoke } from "@tauri-apps/api/core";
import { emitTo, listen } from "@tauri-apps/api/event";
import { writable } from "svelte/store";
import type { ProjectInfo } from "./types/finding";

export const alignmentBusy = writable(false);
export const alignmentPinned = writable(false);
export const alignmentDetached = writable(false);
export const alignmentDesktop = () => "__TAURI_INTERNALS__" in window;
export const alignmentWindow = (action: "open" | "hide") => invoke<void>("alignment_window", { action });
export interface AlignmentWindowContext {
  project: ProjectInfo | null; chapter: string; verse: string; verses: string[];
  initialVerses: string[]; mode: "word" | "cross"; open: boolean; pinned: boolean; revision: number;
}
export type AlignmentMessage = { kind: "ready" } | { kind: "dock" | "close" | "pin" | "cross"; path: string }
  | { kind: "busy"; path: string; busy: boolean }
  | { kind: "saved"; path: string; chapter: string; verse: string };
export const sendAlignmentContext = (value: AlignmentWindowContext) => emitTo("alignment", "alignment-context", value);
export const sendAlignmentMessage = (value: AlignmentMessage) => emitTo("main", "alignment-message", value);
export const onAlignmentContext = (fn: (value: AlignmentWindowContext) => void) => listen<AlignmentWindowContext>("alignment-context", (e) => fn(e.payload));
export const onAlignmentMessage = (fn: (value: AlignmentMessage) => void) => listen<AlignmentMessage>("alignment-message", (e) => fn(e.payload));
