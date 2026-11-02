// Paratext project link (#355). Written by an import to every book of a
// collection, in `.bridge/collection.json` `paratext`; engine:
// `paratext_project.link_block`.

export interface ParatextNaming {
  prePart: string;
  postPart: string;
  bookNameForm: string;
}

export interface ParatextLink {
  schemaVersion: 1;
  guid: string;
  folder: string;
  name: string;
  fullName: string;
  versification: string | null;
  naming: ParatextNaming;
  booksPresent: string[];
  settingsSha256: string;
  linkedAt: string;
}

// #356: `paratext.linkStatus` (engine: paratext_session.ParatextSession.link_status).
export type ParatextLinkState = "linked" | "folderMissing" | "guidMismatch" | "folderMoved" | "notParatext";

export interface ParatextLinkStatus {
  state: ParatextLinkState;
  folder: string;
  /** folderMoved: the folder under Paratext's projects folder with the same Guid. */
  candidate?: string;
  guid: string;
  name: string;
  fullName: string;
  versification: string | null;
  encoding: string;
  booksPresent: string[];
  linkedAt: string;
  files: {
    notes: { count: number; users: string[] };
    bookNames: boolean;
    commentTags: boolean;
    userAccess: boolean;
    termRenderings: boolean;
    errorDenials: boolean;
    spellingStatus: boolean;
    checkingStatus: boolean;
    progress: boolean;
  };
  /** #357: the Project Notes index. */
  notesIndex: ParatextNotesIndexStatus;
}

export interface ParatextBookName {
  abbr: string;
  short: string;
  long: string;
}

export interface ParatextBookNames {
  bookNames: Record<string, ParatextBookName>;
  state: ParatextLinkState;
}

// #357: Paratext Project Notes, read-only (engine: paratext_session.ParatextSession).
export type ParatextNotesIndexState = "unavailable" | "building" | "ready" | "stale" | "error";
export type ParatextNoteKind = "note" | "conflict" | "biblicalTerm";

export interface ParatextNotesIndexStatus {
  state: ParatextNotesIndexState;
  threads: number;
  builtAt: string;
  buildSeconds: number | null;
  source: "" | "cache" | "files";
  error: string;
  staleFiles?: string[];
}

export interface ParatextNoteTag {
  id: string;
  name: string;
}

// #427: what a QA pass proposed in a note, parsed by the engine
// (tc_ai_bridge/paratext_proposals.py). Read-only: a route is the strongest
// claim the parser makes about the Suggested field, never a decision.
export type ParatextProposalRoute = "literal" | "review" | "structure" | "noChange" | "legacy" | "unreadable";
export type ParatextProposalOperation =
  "replace" | "insert" | "delete" | "alternatives" | "noChange" | "structural" | "markerRename" | "instruction" | "none";
export type ParatextProposalRegion = "body" | "introduction" | "heading" | "footnote" | "crossReference" | "structure";

export interface ParatextProposalSummary {
  total: number;
  outstanding: number;
  unreadable: number;
  byRoute: Record<ParatextProposalRoute, number>;
}

export interface ParatextProposal {
  proposalId: string;
  commentIndex: number;
  block: number;
  route: ParatextProposalRoute;
  operation: ParatextProposalOperation;
  region: ParatextProposalRegion;
  pass: string;
  topic: string;
  category: string;
  categoryKnown: boolean;
  original: string;
  suggested: string;
  reason: string;
  location: string;
  reference: string;
  severity: string;
  confidence: string;
  reviewerDecision: boolean;
  anchorWarning: boolean;
  historical: boolean;
  outstanding: boolean;
  alternatives: string[];
  structural: { fromMarker: string; toMarker: string; label: string } | null;
  diagnostics: string[];
  author: string;
  date: string;
}

export interface ParatextNoteSummary {
  id: string;
  kind: ParatextNoteKind;
  status: string;
  resolved: boolean;
  verseRef: string;
  verse: string;
  users: string[];
  firstDate: string;
  lastDate: string;
  lastUser: string;
  excerpt: string;
  selectedText: string;
  assignedUser: string;
  tags: ParatextNoteTag[];
  hidden: boolean;
  commentCount: number;
  /** #427: the QA proposals in the thread, counted. */
  proposals: ParatextProposalSummary;
}

export interface ParatextNoteComment {
  user: string;
  date: string;
  contents: string;
  status: string;
  type: string;
  assignedUser: string | null;
  replyToUser: string;
  language: string;
  tagsAdded: ParatextNoteTag[];
  tagsRemoved: ParatextNoteTag[];
}

export interface ParatextNoteThread extends ParatextNoteSummary {
  contextBefore: string;
  contextAfter: string;
  comments: ParatextNoteComment[];
  /** #427: every proposal in the thread, in comment order. */
  proposalItems: ParatextProposal[];
}

export interface ParatextNoteCount {
  open: number;
  resolved: number;
}

export interface ParatextNotesForChapter {
  state: ParatextNotesIndexState;
  book: string;
  chapter: string;
  verses: Record<string, ParatextNoteSummary[]>;
  counts: Record<string, ParatextNoteCount>;
}

export interface ParatextNotesForVerse {
  state: ParatextNotesIndexState;
  book: string;
  chapter: string;
  verse: string;
  threads: ParatextNoteThread[];
  /** #426: this verse's writes still in the outbox: a note queued, refused
   *  or sent but not yet read back from Paratext's file; a reply or resolve
   *  on one of its threads not yet sent. Never shown as made. */
  pending: ParatextOutboxItem[];
}

// #428/#431/#432/#433/#434: the Paratext QA review queue (engine:
// tc_ai_bridge/paratext_review.py). An apply goes through verse.edit's writer
// on Bridge's copy of the verse; nothing here writes into Paratext.
export type ParatextReviewFilter = "unresolved" | "resolved" | "all";
export type ParatextReviewDecisionKind = "applied" | "rejected" | "manual" | "deferred" | "reverted";

export interface ParatextReviewSnapshot {
  raw: string;
  plain: string;
}

export interface ParatextReviewDecision {
  proposalId: string;
  threadId: string;
  book: string;
  chapter: string;
  verse: string;
  verseRef: string;
  pass: string;
  category: string;
  route: ParatextProposalRoute;
  operation: ParatextProposalOperation;
  decision: ParatextReviewDecisionKind;
  comment: string;
  reviewer: string;
  decidedAt: string;
  threadResolved: boolean;
  original: string;
  replacement: string;
  verified: boolean;
  before?: ParatextReviewSnapshot;
  after?: ParatextReviewSnapshot;
  observed?: ParatextReviewSnapshot;
  span?: { plainStart: number; plainEnd: number; rawStart: number; rawEnd: number };
  journalTransactionId?: string;
  unverifiedReason?: string;
  revertedAt?: string;
  revertVerified?: boolean;
  revision: number;
  updatedAt: string;
}

export interface ParatextReviewDraft {
  replacement: string;
  comment: string;
}

export interface ParatextReviewThreadCompletion {
  complete: boolean;
  blocking: string[];
}

export interface ParatextReviewItem {
  proposalId: string;
  threadId: string;
  book: string;
  chapter: string;
  verse: string;
  verseRef: string;
  threadResolved: boolean;
  selectedText: string;
  contextBefore: string;
  contextAfter: string;
  proposal: ParatextProposal;
  threadOutstanding: number;
  decision: ParatextReviewDecision | null;
  draft: ParatextReviewDraft | null;
  thread: ParatextReviewThreadCompletion;
}

export interface ParatextReviewState {
  status: ParatextReviewFilter;
  position: string;
  drafts: Record<string, ParatextReviewDraft>;
  sessionStartedAt: string;
}

export interface ParatextReviewPreset {
  id: string;
  label: string;
  text: string;
}

export interface ParatextReviewQueue {
  indexState: ParatextNotesIndexState;
  status: ParatextReviewFilter;
  book: string;
  items: ParatextReviewItem[];
  counts: Record<"total" | "undecided" | ParatextReviewDecisionKind, number>;
  state: ParatextReviewState;
  presets: ParatextReviewPreset[];
  reviewer: string;
}

export interface ParatextReviewPreview {
  proposalId: string;
  plain: string;
  found: number;
  ok: boolean;
  reason: string;
  after: string;
  span: { plainStart: number; plainEnd: number } | null;
  matches: { plainStart: number; plainEnd: number; wholeWord: boolean }[];
}

export interface ParatextReviewReport {
  written: boolean;
  path: string;
  html: string;
  count: number;
  reason?: string;
}

// #358: Paratext write-back (engine: tc_ai_bridge/paratext_outbox.py).
// "note" (#426): a note from the notes panel with no Bridge record behind it.
export type ParatextWriteKind = "issue_resolution" | "finding" | "correction_proposal" | "note";
export type ParatextOutboxOp = "create_thread" | "add_comment" | "resolve";

export interface ParatextOutboxItem {
  messageId: string;
  op: ParatextOutboxOp;
  threadId: string;
  status: "queued" | "refused" | "sent";
  attempts: number;
  lastError: string;
  sentAt: string;
  resultKey: string;
  createdAt: string;
  kind?: ParatextWriteKind;
  localId?: string;
  /** On a create: where it goes and what it says (with the Bridge footer). */
  reference?: string;
  selectedText?: string;
  text?: string;
}

export interface ParatextThreadLink {
  kind: ParatextWriteKind;
  localId: string;
  threadId: string;
  messageId: string;
  direction: "bridge_to_paratext" | "paratext_to_bridge";
  /** The thread as the notes index has it; null until Bridge has read it. */
  thread: ParatextNoteThread | null;
}

export interface ParatextThreadsFor {
  state: ParatextNotesIndexState;
  links: ParatextThreadLink[];
  /** This record's writes still waiting in the outbox. */
  pending: ParatextOutboxItem[];
}
