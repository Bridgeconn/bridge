# translationCore AI Bridge - Paratext companion plugin

This directory contains the source for the connector verified with Paratext
9.5.110.1. It serves protocol-1 newline-delimited JSON on the local-only named
pipe `\\.\pipe\translationCoreAIBridge`.

The connector supports:

- active user, project, reference, selection, and sync-group state;
- two-way Scripture navigation; and
- safe Project Note creation through Paratext's own write-lock and `AddNote`
  APIs.

It deliberately contains no Scripture-writing (`PutUSFM`/`PutUSX`) operation.
Bridge verifies the active Paratext project ID before sending, uses the logged-in
Paratext user as author, and refuses ambiguous repeated-text anchors.

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
verify connector state before testing a disposable Project Note. Bridge keeps a
Notes 1.1 outbox copy and retries failed live handoffs without duplicating the
resolution or message identity.

## Remaining integration boundary

The C# assembly compiles against the locally installed Paratext interfaces, but
automated CI cannot launch Paratext. Release acceptance therefore still needs a
manual live check for connection, project-identity refusal, exact/repeated text
anchoring, and one disposable note creation.
