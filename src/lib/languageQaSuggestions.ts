import type { LanguageQaFinding, LanguageQaSuggestion } from "./types/languageQa";

/** The indic-qa editor's menu offers nine numbered suggestions. */
export const MAX_SUGGESTIONS = 9;

/**
 * A finding's suggestions as the indic-qa editor lists them: the reviewer's
 * learned fixes first, then the rest in rank order, at most nine. Falls back
 * to the one-release `suggestedReplacement` alias for a finding from an older
 * engine.
 */
export function orderedSuggestions(finding: LanguageQaFinding): LanguageQaSuggestion[] {
  const ranked = finding.suggestions?.length
    ? finding.suggestions
    : finding.suggestedReplacement
      ? [{ text: finding.suggestedReplacement, rank: 1, source: "rule" as const, rationale: "" }]
      : [];
  // Learned first, then the cut: a learned fix is never the one dropped.
  return [...ranked.filter((s) => s.source === "learned"), ...ranked.filter((s) => s.source !== "learned")]
    .slice(0, MAX_SUGGESTIONS);
}

/** What is shown beside a suggestion, as the indic-qa editor shows it: the
 * checker's edit class and how often the form is used ("vowel length · 412"),
 * "split", or "learned fix". Empty for a rule's fix, which has neither. */
export function suggestionTag(s: LanguageQaSuggestion): string {
  if (s.source === "learned") return "learned fix";
  if (s.kind === "split") return "split";
  return [s.kind ? s.kind.replace(/_/g, " ") : "", s.freq !== undefined ? String(s.freq) : ""]
    .filter(Boolean).join(" · ");
}

/**
 * The lines of the editor menu's "Why" (#250): what was found, how far
 * reviewers have confirmed the rule, why it is drawn, and the reason for the
 * first fix. A reviewed-inline rule is always drawn; any other is drawn
 * because the Settings › Language QA threshold lets it through
 * (language_qa_drawn.py). `rulePrecision` is absent from an older engine.
 */
export function findingWhy(finding: LanguageQaFinding): string[] {
  const measured = finding.rulePrecision != null && (finding.ruleLabelled ?? 0) > 0
    ? `Reviewers confirmed ${Math.round(finding.rulePrecision * 100)}% of ${finding.ruleLabelled} labelled findings of this rule.`
    : "No reviewer has labelled findings of this rule yet.";
  const fix = orderedSuggestions(finding).find((s) => s.rationale)?.rationale;
  return [
    finding.message,
    measured,
    finding.inline
      ? "Reviewed inline (at least 90% confirmed): always underlined."
      : `Underlined because your Settings › Language QA threshold lets it through (rule confidence: ${finding.confidence}).`,
    ...(fix ? [`Fix: ${fix}`] : []),
    `Rule: ${finding.ruleId}`,
  ].filter(Boolean);
}
