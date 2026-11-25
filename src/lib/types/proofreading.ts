/** Wire types for the proofreading run (#505): engine/proofreading_service.py
 *  (`proofreading.*`) and engine/proofreading_jobs.py. */

export type ProofreadingBookState = "pending" | "running" | "done" | "skipped" | "failed";
export type ProofreadingSeverity = "High" | "Medium" | "Low";

export interface ProofreadingUsage {
  calls?: number;
  inputTokens?: number;
  outputTokens?: number;
  cachedInputTokens?: number;
  totalTokens?: number;
  estimatedCostUSD?: number;
}

export interface ProofreadingBook {
  bookId: string;
  bookName: string;
  path: string;
  state: ProofreadingBookState;
  elapsedSeconds: number | null;
  findings: number;
  bySeverity: Partial<Record<ProofreadingSeverity, number>>;
  /** Groups of chapters read so far, of how many: the book's own progress. */
  chunksDone: number;
  chunksTotal: number;
  usage: ProofreadingUsage;
  error: string | null;
  /** Why a book was skipped, or what the toolkit could not do for it. */
  note: string | null;
  completedAt: string | null;
}

export interface ProofreadingSnapshot {
  jobId: string;
  /** "idle" when no run exists in this session: `books` then holds each book's last recorded run. */
  state: "idle" | "queued" | "running" | "cancelling" | "succeeded" | "failed" | "cancelled";
  paused: boolean;
  /** What the run is doing now, in words ("Reading chapters 4 to 6"). */
  stage: string;
  /** The run stopped because the provider takes no more requests for now
   *  (a ChatGPT plan's limit, a lapsed sign-in); `error` says which. */
  halted: boolean;
  collectionPath: string;
  reference: string;
  totalBooks: number;
  completedBooks: number;
  percent: number;
  currentBook: string | null;
  books: ProofreadingBook[];
  findings: number;
  usage: ProofreadingUsage;
  elapsedSeconds: number;
  estimatedRemainingSeconds: number | null;
  error: string | null;
  createdAt: string | null;
  finishedAt: string | null;
}

export interface ProofreadingReference {
  path: string;
  label: string;
  /** "proofreading": chosen for proofreading; "project": the project's own
   *  reference Bible; "none": nothing chosen yet. */
  origin: "proofreading" | "project" | "none";
  kind: string;
  files: string;
  /** Why this reference cannot be used, or "". */
  error: string;
}

export interface ProofreadingEstimate {
  requests: number;
  inputTokens: number;
  outputTokens: number;
  cachedInputTokens: number;
  estimatedCostUSD: number;
}

export interface ProofreadingPreflightBook {
  bookId: string;
  bookName: string;
  path: string;
  /** False for a book outside the 66 the toolkit knows: it cannot be read. */
  supported: boolean;
  estimate: ProofreadingEstimate;
  previous: {
    completedAt?: string | null; findings?: number;
    bySeverity?: Partial<Record<ProofreadingSeverity, number>>; reference?: string; model?: string;
  } | null;
}

export interface ProofreadingPreflight {
  aiReady: boolean;
  /** On a ChatGPT sign-in a run uses plan allowance, not dollars. */
  planUsage: boolean;
  model: string;
  haltReason: string;
  reference: ProofreadingReference;
  language: { code: string; label: string };
  profile: { name: string; code: string; status: string };
  toolkit: { name: string; fingerprint: string; pipeline: number };
  paratextLinked: boolean;
  books: ProofreadingPreflightBook[];
  running: boolean;
  checkRunning: boolean;
}

export interface ProofreadingReportBook {
  bookId: string;
  bookName: string;
  state: "done" | "notRun";
  completedAt?: string | null;
  findings?: number;
  bySeverity?: Partial<Record<ProofreadingSeverity, number>>;
  byIssueType?: Record<string, number>;
  reference?: string;
  model?: string;
  provider?: string;
  chunks?: number;
  /** Rows the reader returned, before evidence and placing. */
  reported?: number;
  /** Leads and rows set aside (house style, found nearby, could not be placed). */
  rejected?: number;
  unplaced?: number;
  overlapping?: number;
  notes?: string[];
  usage?: ProofreadingUsage;
  elapsedSeconds?: number;
  hasReference?: boolean;
}

export interface ProofreadingReport {
  books: ProofreadingReportBook[];
  booksRead: number;
  totalBooks: number;
  findings: number;
  bySeverity: Record<ProofreadingSeverity, number>;
  byIssueType: Record<string, number>;
  usage: ProofreadingUsage;
  outputFolder: string;
  /** The toolkit's own files, by what they are: runReport (the workbook),
   *  runSummary, paratextNotes. Absent until a run has written them. */
  files: Record<string, string>;
  note: string;
}

export interface ProofreadingRow {
  id: string;
  book: string;
  /** A chapter number, or "Intro". */
  chapter: string;
  verse: string;
  issueType: string;
  category: string;
  severity: string;
  confidence: string;
  original: string;
  suggested: string;
  explanation: string;
  referenceNote: string;
  decisionNeeded: string;
  /** Verse text, Heading, Footnote, Cross-reference or Introduction. */
  location: string;
  anchor: string;
}

export interface ProofreadingRows {
  bookId: string;
  rows: ProofreadingRow[];
  /** The toolkit's files for this book: workbook, csv. */
  files: Record<string, string>;
}
