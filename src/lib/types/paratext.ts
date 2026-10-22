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
