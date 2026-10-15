/**
 * The reference Bridge publishes to Paratext and Logos ("GEN 1:5"), or "" when
 * no verse is selected.
 *
 * It takes the project, chapter and verse as arguments on purpose. App.svelte's
 * `$: navigationReference = ...` must name the stores it depends on: Svelte 4
 * tracks only the names written in a reactive statement, so a call with no
 * arguments that reads the stores inside a function ran once at mount and never
 * again, and Bridge never told Paratext about a verse change (#110).
 */
export function bridgeReference(
  project: { bookId: string } | null | undefined,
  chapter: string | null | undefined,
  verse: string | null | undefined,
): string {
  if (!project || !verse) return "";
  return `${project.bookId.toUpperCase()} ${chapter}:${verse}`;
}
