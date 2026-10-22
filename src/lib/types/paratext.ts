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
