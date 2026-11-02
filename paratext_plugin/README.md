# translationCore AI Bridge - Paratext companion plugin

This directory contains the source for the connector verified with Paratext
9.5.110.1. It serves protocol-1 newline-delimited JSON on the local-only named
pipe `\\.\pipe\translationCoreAIBridge`.

The connector (0.8.0, #358) supports:

- active user, project, reference, selection, and sync-group state, plus
  `projects`, every project on this PC (`id`, `short_name`, `editable`);
- two-way Scripture navigation;
- Project Notes through Paratext's own write lock: `create_note` in the project
  named by `project_id` (the Guid the book was imported from, never the active
  window; `IReadOnlyProject.ID`), answering with the note's `author`, `created`
  and `anchor`; `list_notes` for a chapter; `add_comment` and `resolve_note` on
  a thread found by its anchor and first comment (`key`). A Paratext note has no
  id, so author + created is its identity.

Since 0.9.0 (#429, DECISIONS 2026-11-02, decided by Benz) it also has **one**
Scripture write, `put_verse_text`: `CanEdit`, then under Paratext's chapter
write lock the chapter's tokens are read (`GetUSFMTokens(book, chapter)`), the
exact `original` located once in the verse's Scripture text tokens (never in a
footnote or cross-reference token, never across two tokens, on text-element
boundaries; repeats told apart by the note's before/after context), that one
token's text replaced, the chapter written with `PutUSFMTokens(lock, tokens,
book)`, notifications sent, and the tokens read again; `verified` is true only
when the chapter's USFM reads exactly as expected. A history point is taken
before and after. (#438: the installed 9.5.110.1 interfaces' `PutUSFM` takes
`(lock, usfm, bookNum)` -- a whole-book write -- so the first cut, which called
it with a chapter, did not compile; the token route is the one the reference
plugin ran on this host.)
Bridge sends it only after a reviewer confirmed the correction in the review
queue and it was applied and verified on Bridge's own copy. The plugin never
deletes or reopens a note and never restructures USFM. The logged-in Paratext
user is the author of every note, comment and edit; the Bridge user who
confirmed it travels as `bridge_user` for the evidence, never as the author.

**0.9.0's first cut failed to compile on Benz's Paratext PC (#438, 2026-11-02)**;
the token route above replaces it and has not yet been compiled there. The
machine it was written on has no Paratext, so `build.ps1` on a Paratext PC is
the compile check and `docs/PARATEXT_HOST_ACCEPTANCE_CHECKLIST.md` the live
one. The members used (`CanEdit(plugin, book, chapter)`, `RequestWriteLock(plugin,
release, book, chapter)`, `GetUSFMTokens`, `PutUSFMTokens`, `SendNotifications`,
`ConvertToUSFMString`, `MakeHistoryPoint`, and the `IUSFMTextToken` members of
`ChangedTextToken`) are exactly those selvabenz/Paratext-sug-in-context-menu
compiled and ran against the same 2.0.100.0 interfaces.

Since 0.10.0 (#429, #430, 2026-11-03) `put_verse_text` takes a `region`:
`body` (as before), `footnote` / `crossReference` (the verse's note tokens, by
note kind), `heading` (the heading tokens the verse introduces -- Paratext
anchors them on the verse before, so `firstVerse - 1` is accepted) and
`introduction` (chapter 0 to the token API, the `\i*` paragraphs). The token
classification is the reference plugin's `TokenMapping.Parts`, compiled and run
on the host. A region is never a fallback for another. The second write,
`rename_marker`, is the reference plugin's `ApplyMarkerRename`: an exact
heading / chapter-label marker rename (ms, ms1-3, s, s1-4, cl, cd) with the
label unchanged, unique at the anchor, no attributes, the edited chapter
rendered to USFM and parsed again by Paratext (`ConvertToUSFMTokens`) before
`PutUSFMTokens`, read back after. Capabilities `text_regions` and
`rename_marker` tell Bridge which connector it is talking to; an older one keeps
a region write queued with the reason. **0.10.0 has not been compiled anywhere
yet** (no Paratext on the machine it was written on); the members it adds
(`IUSFMMarkerToken.Marker/Type/Data/EndMarker/Attributes`, `MarkerType.Verse/
Paragraph`, `ConvertToUSFMTokens(string, int, int, int)`) are exactly those the
reference plugin's `ChangedMarkerToken` and `ApplyMarkerRename` compiled against
2.0.100.0.

## Live verification

The v0.7.4 connector was already installed and working on the development
machine. On 2026-08-26 Bridge verified its `get_state` response and successfully
created a real Project Note. The matching source, previously held in the older
local Bridge repository, is now maintained here.

Only one connector may be installed: every version uses the same named pipe.
The earlier navigation-only v1.0 experiment is retained outside Paratext under
`disabled-TranslationCoreAIBridgePlugin-v1/` for recovery and is git-ignored.

## Installing it for a translator (#282)

A translator never needs the steps below. Bridge carries this source and
installs the connector itself, in two places:

- **Bridge's installer** offers it after Bridge is installed, when Paratext 9 is
  registered on the PC (`src-tauri/windows/hooks.nsh`).
- **Settings › Connections** shows **Install Paratext connector** (or **Update
  …**) when Paratext 9 is found and the connector is missing or older than the
  one this Bridge carries.

Either way, `engine/tc_ai_bridge/paratext_install.py`:
1. finds Paratext 9 through its registry entry;
2. compiles these three files with the Windows .NET Framework `csc.exe` against
   that PC's own `PluginInterfaces.dll`, as `build.ps1` does;
3. copies the result in as `translationCoreAIBridge.ptxplg`, with a
   `connector-version.txt` beside it, through one Windows administrator prompt.

It refuses while Paratext is running. The frozen engine ships the three `.cs`
files as data (`engine/bridge-engine.spec`). Bump `PluginVersion` in
`AiBridgeConnectorPlugin.cs` whenever the connector changes: Bridge offers
**Update** when the installed version is lower.

## Build and deploy by hand (developers)

The build uses the .NET Framework C# compiler bundled with Windows and the
plugin-interface DLLs from the installed Paratext 9 directory.

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
powershell -ExecutionPolicy Bypass -File build.ps1 -Deploy
```

Close Paratext before `-Deploy` and run the shell as Administrator because the
destination is `C:\Program Files\Paratext 9\plugins\translationCoreAIBridge`.
The script refuses deployment while Paratext is running.

After deployment, restart Paratext, open the intended Scripture project, and
verify connector state before testing a disposable Project Note. Bridge queues a
note it could not send and retries it without duplicating the message identity
(the `[Bridge ref ...]` footer is checked against the notes index first).

## Remaining integration boundary

The C# assembly compiles against the locally installed Paratext interfaces, but
automated CI cannot launch Paratext. Release acceptance therefore still needs a
manual live check for connection, project-identity refusal, exact/repeated text
anchoring, and one disposable note creation.
