import type { QaFinding, Severity } from "./types/finding";
import type { LanguageQaFinding } from "./types/languageQa";

/** The Review panel's tabs (ReviewPanel.svelte); "ai" is never a landing here. */
export type ReviewTab = "greekroom" | "tntw" | "lqa" | "ai";

/**
 * The three real Greek Room engines (each adapter's own engine_name). Every
 * other `engine` value is native tC/Bridge QA. The same set as
 * ReviewPanel.svelte's, which decides the tab a finding is reviewed on.
 */
const GREEK_ROOM_ENGINES = new Set(["wildebeest", "usfm", "names"]);

const SEVERITY_RANK: Record<string, number> = { high: 3, medium: 2, low: 1, info: 0 };

/** What the pill says about one open finding, for the title's breakdown. */
function sourceLabel(finding: QaFinding): string {
  if (GREEK_ROOM_ENGINES.has(finding.engine)) return "Greek Room";
  if (finding.category === "alignment") return "alignment";
  if (finding.category === "translation_note") return "tN";
  if (finding.category === "translation_word") return "tW";
  return "other";
}

export interface OpenIssueSummary {
  /** Open findings plus Language QA findings on the verse. 0 means no pill. */
  count: number;
  /** The worst severity among them, the pill's colour. */
  worst: Severity;
  /** "3 open findings · 2 Language QA, 1 alignment". */
  title: string;
  /** The Review panel tab of the first open finding, in the row's order. */
  tab: ReviewTab;
}

/**
 * #383: the open-issue count beside a verse number. The count is the one
 * VerseList already used for ✓ (open QaFindings plus every Language QA
 * finding, which has no status of its own); the breakdown names where they
 * came from so "3" reads as "2 Language QA, 1 alignment" on hover.
 */
export function openIssueSummary(findings: QaFinding[], langFindings: LanguageQaFinding[]): OpenIssueSummary {
  const open = findings.filter((f) => f.status === "open");
  const count = open.length + langFindings.length;
  const groups = new Map<string, number>();
  let worst = -1;
  for (const f of open) {
    groups.set(sourceLabel(f), (groups.get(sourceLabel(f)) ?? 0) + 1);
    worst = Math.max(worst, SEVERITY_RANK[f.severity] ?? 1);
  }
  if (langFindings.length) {
    groups.set("Language QA", langFindings.length);
    for (const f of langFindings) worst = Math.max(worst, SEVERITY_RANK[f.severity] ?? 1);
  }
  const breakdown = [...groups.entries()].map(([label, n]) => `${n} ${label}`).join(", ");
  const first = open[0];
  const tab: ReviewTab = first ? (GREEK_ROOM_ENGINES.has(first.engine) ? "greekroom" : "tntw") : "lqa";
  return {
    count,
    worst: (["info", "low", "medium", "high"] as Severity[])[Math.max(worst, 0)],
    title: count ? `${count} open ${count === 1 ? "finding" : "findings"} · ${breakdown}` : "",
    tab,
  };
}
