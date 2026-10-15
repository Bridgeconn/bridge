/** The team dashboard's client for the hub it is served from (#81).
 *
 *  The dashboard reads the hub's own data, not the engine protocol: the hub
 *  holds no projects and no Scripture (Scripture never travels), so the
 *  engine methods the desktop uses would have nothing to answer with. Same
 *  origin as the hub, so every path is relative. Signing in is joining with
 *  a join code, as a device does; the token is kept in this browser's
 *  storage for this hub only. */

export type HubRole = "project_admin" | "editor" | "reporter";

export interface HubMe {
  userId: string;
  displayName: string;
  role: HubRole;
}

export interface HubAssignment {
  chapter: string;
  assigneeId: string;
  assigneeName: string;
  assignedBy: string;
  assignedAt: string;
}

export interface HubProject {
  hubProjectId: string;
  bookId: string;
  bookName: string;
  projectName: string;
  chapters: string[];
  totals: Record<string, number>;
  progressPostedAt: string | null;
  lastActivityAt: string | null;
  events: number;
  assignments: HubAssignment[];
  /** #279: the signed-in user's role on this project (theirs by token where
   *  the project gives them none), and every per-project role on it. */
  myRole: HubRole;
  roles: Record<string, HubRole>;
}

export interface HubUser {
  userId: string;
  displayName: string;
  role: HubRole;
  lastSeenAt: string | null;
  devices: number;
}

const TOKEN_KEY = "bridge.hub.dashboard.token.v1";

export function storedToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

function storeToken(token: string): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Private windows may refuse storage; the session still works until reload.
  }
}

let token = storedToken();

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) signOut();
    throw new Error((data as { detail?: string }).detail || `The hub answered ${response.status}.`);
  }
  return data as T;
}

export function signedIn(): boolean {
  return Boolean(token);
}

export function signOut(): void {
  token = "";
  storeToken("");
}

export const hubApi = {
  async join(joinCode: string, displayName: string): Promise<HubMe> {
    const joined = await request<HubMe & { token: string }>("POST", "/hub/join", { joinCode, displayName });
    token = joined.token;
    storeToken(token);
    return { userId: joined.userId, displayName: joined.displayName, role: joined.role };
  },
  me: () => request<HubMe>("GET", "/hub/me"),
  projects: () => request<{ projects: HubProject[] }>("GET", "/hub/projects"),
  users: () => request<{ users: HubUser[] }>("GET", "/hub/users"),
  assign: (hubProjectId: string, chapter: string, userId: string) =>
    request<{ changed: boolean }>("POST", "/hub/assignments", { hubProjectId, chapter, userId }),
  /** #279: a user's role on one project; null returns them to their token role. */
  setTeamRole: (hubProjectId: string, userId: string, role: HubRole | null) =>
    request<{ changed: boolean }>("POST", "/hub/team-roles", { hubProjectId, userId, role }),
  joinCode: (role: HubRole) => request<{ joinCode: string; role: HubRole }>("POST", "/hub/join-codes", { role }),
};

/** The projects table as CSV, for the reporters' export. */
export function projectsCsv(projects: HubProject[]): string {
  const header = ["Book", "Project", "Chapters", "Checked chapters", "Verses", "Reviewed verses",
    "Aligned verses", "Language QA clean verses", "Assigned to", "Last activity"];
  const quote = (value: unknown) => {
    const text = String(value ?? "");
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const rows = projects.map((p) => [
    p.bookName, p.projectName, p.totals.chapterCount ?? p.chapters.length, p.totals.checkedChapterCount ?? 0,
    p.totals.verseCount ?? 0, p.totals.reviewedVerseCount ?? 0, p.totals.alignedVerseCount ?? 0,
    p.totals.languageQaCleanVerseCount ?? 0,
    p.assignments.map((a) => `${a.chapter ? `ch ${a.chapter}` : "book"}: ${a.assigneeName || a.assigneeId}`).join("; "),
    p.lastActivityAt ?? "",
  ]);
  return [header, ...rows].map((row) => row.map(quote).join(",")).join("\n") + "\n";
}
