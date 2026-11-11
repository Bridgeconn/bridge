import { setSidePanel } from "./editorPrefs";
import { reviewTabRequest } from "./stores";

/**
 * Brings the Review panel's Language QA tab on screen (#487): the status
 * bar's Language QA button. The tab is always part of the Review panel, so
 * this opens the Review column if it is closed (or folded for width) and asks
 * for the tab; the button always lands the reviewer on the list.
 */
export function showLanguageQaTab(): void {
  setSidePanel("review", { open: true });
  reviewTabRequest.set("lqa");
}
