import { setSidePanel } from "./editorPrefs";
import { reviewTabRequest } from "./stores";
import { setLanguageQaShown } from "./viewMenu";

/**
 * Brings the Review panel's Language QA tab on screen (#487): the status
 * bar's Language QA button. The View menu's entry toggles the tab
 * (viewMenu.ts); this one only ever shows it, and opens the Review column
 * if it is closed, so the button always lands the reviewer on the list.
 */
export function showLanguageQaTab(): void {
  setLanguageQaShown(true);
  setSidePanel("review", { open: true });
  reviewTabRequest.set("lqa");
}
