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

It deliberately contains no Scripture-writing (`PutUSFM`/`PutUSX`) operation and
never deletes a note. The logged-in Paratext user is the author of every note
and comment; ambiguous repeated-text anchors are refused.

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
