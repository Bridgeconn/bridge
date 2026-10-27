// An in-app confirmation (#372). `window.confirm` never asks in the
// installed app: the dialog plugin replaces it with an async function whose
// command is not in the ACL, so it rejects, and a Promise is truthy, so
// `if (!window.confirm(…)) return` always went on. Both paid or destructive
// actions (chapter/book AI review, Remove key) now wait on this instead: the
// same shape the scoped Language QA apply uses (a store the App mounts a
// dialog for), and the answer is a resolved boolean, never a Promise read as
// true. Decided on the issue (Revant, 2026-10-24): no capability or ACL change.
import { get, writable } from "svelte/store";

export interface ConfirmRequest {
  /** The question, as a heading: "Run AI review for this chapter?" */
  title: string;
  /** What happens if they say yes, in a sentence or two. */
  body: string;
  /** The yes button's label, naming the action: "Run for the chapter". */
  confirmLabel: string;
  /** The no button's label; "Cancel" by default. */
  cancelLabel?: string;
  /** True for an action that removes something: the yes button is drawn red. */
  danger?: boolean;
}

interface PendingConfirm extends ConfirmRequest {
  resolve: (confirmed: boolean) => void;
}

/** The open question, or null. One at a time; App mounts ConfirmDialog for it. */
export const confirmRequest = writable<PendingConfirm | null>(null);

/**
 * Ask, and resolve with the reviewer's answer. Resolves false when the dialog
 * is dismissed (Cancel, Escape) and when another question replaces this one
 * before it is answered: an unanswered question is a "no".
 */
export function askConfirmation(request: ConfirmRequest): Promise<boolean> {
  const previous = get(confirmRequest);
  previous?.resolve(false);
  return new Promise<boolean>((resolve) => {
    confirmRequest.set({ ...request, resolve });
  });
}

/** The dialog's buttons: answer the open question and close it. */
export function answerConfirmation(confirmed: boolean): void {
  const pending = get(confirmRequest);
  if (!pending) return;
  confirmRequest.set(null);
  pending.resolve(confirmed);
}
