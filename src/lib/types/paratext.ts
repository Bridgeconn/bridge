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
}

// #358: Paratext write-back (engine: tc_ai_bridge/paratext_outbox.py).
export type ParatextWriteKind = "issue_resolution" | "finding" | "correction_proposal";
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
