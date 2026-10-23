# Hub and dashboard architecture review (#227)

2026-10-15. The review SRS §14 requires before `FUTURE-002` (optional team hub
synchronisation using the local change log) and `FUTURE-003` (hub-served team
dashboard) are built. It reads `TEAM_ARCHITECTURE.md` §5 to §8 (written 2026-09-11
against the v2 workbench) against the code on `main` today (workbench v8, workspace
v5, 193 protocol methods, `authorize()` in place), and ends in the decisions below,
the list of tables that sync, and the order #79 → #80 → #81 confirmed. Each
decision that changes the 2026-09-11 design is also a `DECISIONS.md` entry of this
date.

## 1. What stands from 2026-09-11

- The hub is an optional sync peer, never the primary store and never on a path a
  translator hits in normal work. The desktop's own databases stay authoritative;
  the hub merges events with the same `expected_revision` check every local write
  uses (`WorkbenchRepository.import_events`, shipped in #77 and tested in
  `test_workbench_sync.py`).
- Scripture text never travels. Stage 9B.3b stays the only Scripture writer; the
  hub carries review state, not the text it is about.
- Identity is a chosen name plus a device. The hub issues a device token against a
  join code; no password, no account, no internet (DECISIONS 2026-09-11).
- The engine stamps every write with the identity it holds for the caller; a
  request never names its actor (#183, 2026-10-12). On the hub that identity is the
  user bound to the device token.

## 2. What sync carries: the table list

`MUTABLE_TABLES` has 26 entries today (v8). The design said "decisions, findings,
progress and assignments" and predates nine of them. Classified for the first slice:

| Sync | Table | Why |
|---|---|---|
| yes | `human_decisions` | the product: check, QA, verse-status, terminology and house-style decisions |
| yes | `issue_resolutions` | human-owned, with their lifecycle events as domain rows |
| yes | `alignment_cross_verse_links`, `alignment_null_decisions` | human alignment state tC files cannot hold; the ✓ depends on them (#228) |
| yes | `alignment_history` | the record of alignment writes; `backup_path` is device-local and is carried but never resolved on another device |
| yes | `team_assignments`, `team_members` | assignments (#240) are exactly what a team shares |
| yes | `language_qa_batches`, `language_qa_flags` | a reviewer's correction batches and flags are decisions in another shape |
| yes | `language_qa_learned_fixes` | a learned fix is a reviewer's house style; it carries old→new wording of a *token*, not verse text, which keeps "Scripture never travels" (see §4) |
| yes | `project_state` | `import.json` and `project.json` mirrors, needed to link the project (§3) |
| yes | `ai_review_results` | an AI review is evidence a reviewer acted on; small, and its `input_fingerprint` makes a stale copy visibly stale |
| no | `progress_chapters`, `progress_findings`, `progress_totals` | derived; every device recomputes them from its own check jobs and decisions. The hub dashboard needs a rollup, so the hub keeps **its own** `project_progress_cache` from the events it receives, the way the desktop workspace does |
| no | `check_findings`, `check_cache`, `triage_verdicts` | derived from checks that each device runs itself; a snapshot is large (tens of thousands of rows per book) and reproducible |
| no | `metrics_events`, `metrics_counters`, `file_backups` | device-local by meaning |
| no | `semantic_mappings`, `semantic_validation_runs`, `alignment_diagnostics` | analysis artefacts tied to the per-device semantic database (v16); `alignment_diagnostics` is append-only noise |
| no | `alignment_verdicts` | the per-verse cache of the last automatic pass; rebuilt by the next pass |
| no | `language_qa_cache` | the persisted scan, rebuilt by the next pass |

Two things outside the tables:

- **`language-packs/<pack>/overrides.json`** (a project's narrowing of a pack and
  the indic-qa checker settings, per collection, written to every materialised book)
  is a human decision on disk, not in the change log. It is **not** in the first
  slice: it is small, rarely changed, and already copied to every book of the
  collection; a team shares it by sharing the project folder, as today. Logged as a
  follow-up for the second slice: a `project_state` row mirroring it, so a change
  reaches other devices through the log. Not a schema change now.
- **The reference-panel folder** (`%LOCALAPPDATA%\Bridge\data\reference-cache\`)
  is an app-level derived cache of a reference Bible the user chose; it never syncs.

The `sync` column is a frozen tuple in `workbench_repository.py` (`SYNCED_TABLES`,
#80), with a test that every `MUTABLE_TABLES` entry is classified one way or the
other, the way `authorization.METHOD_ACTIONS` is pinned against `Methods`.

## 3. Project linking across devices

The design links a project by `.bridge/project.json` `projectId` plus the
`import.json` source `sha256`. Checked against collections and lazy siblings:

- A multi-book import mints one `projectId` per book and one `collectionId` on
  every sibling (`project_import.py`, `collection.json` schema 2). Two devices that
  import the same Paratext folder mint **different** ids. So the id alone cannot
  link, and the sha256 alone cannot either (the same book imported twice on one
  device gets the same sha256 and must stay two projects, #91's duplicate rule).
- **Rule:** a hub project is identified by the **hub project id** the first device
  registers it under; a second device joins it by choosing it from the hub's list,
  and its local project is linked by writing `hubProjectId` into
  `.bridge/project.json`, provided the book id matches and the source sha256 matches
  (same text) or the admin confirms a different source. Per book, not per
  collection: the collection is a client-side grouping (`collectionId`), and a
  device may hold a subset of books. A lazy sibling (never opened) has no workbench
  and nothing to sync; it links when it is first opened.
- The `projectId` in every change-log row stays the **local** one; the hub maps
  local id → hub project id per device at push time, so existing rows need no
  rewrite and `natural_row_id` (built from the local id) stays stable per device.
  Consequence: the same logical row has a different `row_key` on two devices.
  Row matching on the hub is therefore by **natural key**, not by id: the lifted
  columns the tables already carry (`chapter, verse, key` on decisions; the
  signature pair on links; `chapter` on assignments). This is why v3 to v8 lifted
  them. `natural_row_id` is extended in #80 to take the hub project id when one is
  set, so a project linked from the start gets identical ids everywhere and the
  natural-key path is only the fallback for projects linked after use.

## 4. Conflict semantics

`import_events` already refuses an event whose `base_revision` is not the local
row's revision and hands the conflict back (`sync_conflicts` in the design). Two
cases the design did not cover:

- **N:M alignment groups.** A tC alignment group lives in `alignmentData/`, a
  translationCore file, and does not sync at all in this slice (Scripture-adjacent,
  tC-owned, and the hub never writes tC files). What syncs is the Bridge-private
  layer on top: cross-verse links and null decisions, both keyed per token
  signature, one row each. Two users linking the same source token to different
  targets produce two rows with different natural keys and **no** conflict; the
  gap scan sees both and the verse shows as needing review, which is the right
  visible state. Two users changing the same link row conflict on revision, as any
  row does. Group-level N:M merging is therefore not needed in the first slice.
- **Batch corrections.** A Language QA batch is one `language_qa_batches` row plus
  many ordinary journalled verse edits. The edits are Scripture and do not travel;
  the batch row travels as a record of what was done. A device receiving a batch
  row whose verses it has not edited shows it as "applied elsewhere"; it does not
  replay the edits (that would be a second Scripture writer). The stop-and-ask in
  CLAUDE.md holds: the hub is not a path for applying corrections to text.
- **Decisions.** Two users deciding the same finding: last writer wins only when
  the second writer's base revision is current; otherwise it is a conflict shown
  to the second writer with both decisions, resolved by a fresh decision. This is
  the requirement's "two users changing the same decision produce a visible
  conflict", and `import_events` already produces it.

## 5. Where authorize() runs

`authorize(user, project, action)` (#236) runs in the engine dispatcher before every
method. On the hub it runs in the same place: the HTTP transport (#79) resolves the
device token to a user and hands the request to `BridgeEngine.handle_request` with
that user bound for the session, so the hub and the desktop share one rule with no
second path. Roles stay per installation in this slice (`workspace.users.role`); the
hub's users table is the team's, and a device's local role does not carry across.
`team_members` gains a `role` column when per-project roles arrive (the `project`
argument `authorize()` already takes), not before.

## 6. Engine process model (#79)

Confirmed as designed, with one narrowing: `BridgeEngine` splits into `Workspace`
(settings, registry, users, job managers) and `ProjectSession` (project, semantic
runtime, per-book caches), requests gain an optional `projectId`, and the stdio
desktop path keeps a current-session default so the frontend does not change. The
HTTP transport is a thin FastAPI wrapper over `handle_request` with the same
envelope (`http_transport.py` is the 35-line stub of exactly that). Threaded
request handling applies to the hub only; the desktop stdio loop stays
single-threaded, which today's job managers (#231, #242, #210) already assume.

## 7. Packaging and the hub machine

> 2026-10-23 (Benz, #46): the first bullet's packaging is superseded. The desktop sidecar
> now carries the server, and Settings > Team can start a hub that lives while Bridge is
> open (`docs/DECISIONS.md` 2026-10-23). The Task Scheduler route below is still how a
> permanent hub runs.

- **A pip-installed `[server]` extra, not a second PyInstaller exe.** The hub is
  installed once by whoever administers the LAN machine; a frozen exe would double
  the release gate (two smokes, two binaries) for one install. `bridge-engine
  --serve --data-dir <hub>` behind `[server] = fastapi, uvicorn`, excluded from
  `bridge-engine.spec` so the desktop sidecar never carries it (DECISIONS
  2026-09-11 unchanged).
- **Windows service via Task Scheduler** (run at startup as a service account,
  restart on failure), not NSSM: nothing to download, nothing to license, and the
  field machine has no internet. A `scripts/install-hub-task.ps1` writes the task.
- **Backup:** the hub's data dir is one SQLite file per project plus its own
  workspace; a nightly `sqlite3 .backup` into `backups/<date>/` by the same task,
  seven kept. The hub is a copy of what every device holds, so a lost hub costs a
  re-sync, not data.
- **Hardware named by the requirement:** one LAN machine, 2 cores, 4 GB, a fixed
  hostname, one open port, no internet. Enough: a push is an `INSERT` per event
  under one `BEGIN IMMEDIATE`; the dashboard is static files plus one JSON per
  screen.

## 8. Acceptance, restated as tests for #80

- A day's work (about 500 decisions) syncs in under 30 s on LAN: `export_events`
  of 500 rows is one SELECT; `import_events` is one transaction; the budget is
  network and the hub's fsync, measured in #80 with a 500-event batch over
  loopback and a 100 Mbit link.
- Two users changing the same decision produce a visible conflict: the existing
  `test_a_divergent_local_row_is_a_conflict_not_an_overwrite`, lifted to the
  protocol (`sync.pull` returns `conflicts`, the UI lists them).
- Desktop fully offline, sync never blocks: sync runs on its own thread with a
  short HTTP timeout and a slow poll; every path a translator hits is unchanged
  (the smoke's offline run stays the gate).

## 9. Order and scope confirmed

#79 (session model, HTTP transport, `--serve`) → #80 (join codes, push/pull,
conflicts, the `SYNCED_TABLES` pin, hub-side progress cache) → #81 (dashboard:
projects and progress, assignments for admins, reports for reporters, users and
join codes for admins; Option A only, 2026-10-12). Nothing here widens the
stop-and-ask list: the hub is the one agreed network peer, and no new account,
login or hosted service appears.

## 10. Follow-ups filed from this review (proposed, not filed)

- `overrides.json` as a `project_state` row (second slice).
- `natural_row_id` taking the hub project id (#80's first commit).
- `team_members.role` for per-project roles (after #81).
