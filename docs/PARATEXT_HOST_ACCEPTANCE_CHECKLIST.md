# Paratext host acceptance checklist (#423, #436)

The real-host walk for the Paratext notes round trip and the reviewer-confirmed
Scripture write. Everything below is **NOT RUN** until the person who walks it
records the result here (or on #423) with the Paratext and connector versions
seen. Source and frozen-sidecar evidence is in `BUILD_LOG.md` (2026-11-02) and
`QA_TEST_MATRIX.md` A35–A38; none of it proves what this page checks.

Decided by Benz on 2026-11-02 (`DECISIONS.md`): Bridge may write one confirmed
verse replacement into Paratext; a verified Paratext resolve closes the linked
Bridge record; every Bridge write names its Bridge user; Benz runs this walk.

## Set-up (disposable only)

- [ ] A **disposable** Paratext 9.5 project (a copy of a real one is fine; never
      a live team project). Note its short name and Guid (Settings.xml).
- [ ] Paratext closed; Bridge Settings › Connections shows **Update Paratext
      connector** to 0.9.0 (or run `paratext_plugin/build.ps1 -Deploy` as admin).
      Record: did `build.ps1` compile 0.9.0 cleanly? (First compile anywhere.)
- [ ] Paratext started; Bridge `paratext.getState` (Settings › Connections) shows
      plugin 0.9.0 and the capability list includes `put_verse_text`.
- [ ] Bridge: import the disposable project (Paratext folder import), open a book,
      Paratext notes panel shows its threads; verse badges show counts.
- [ ] A Bridge user is chosen at startup (the name that will be attributed).

## A. Notes round trip, Bridge-origin

- [ ] Notes panel › **New note…** on a verse, with "Attach to text" set to a word
      that occurs once. Send. Expect: "Note sent"; the panel lists it as pending.
- [ ] In Paratext: the note exists on that verse, anchored on that word, author =
      Paratext's logged-in user, first line `[<Bridge user> (<id>) via Bridge]`,
      last line `[Bridge ref …]`.
- [ ] Reply in Paratext. Bridge › Refresh: the reply shows in the thread.
- [ ] Bridge › **Reply**: Paratext shows the reply with the attribution line.
- [ ] Bridge › **Resolve in Paratext**: Paratext shows a comment "Resolved in
      Bridge." then the thread resolved. Bridge › Refresh: the thread shows
      "resolved in Bridge".
- [ ] Close Paratext. Bridge › New note. Expect "Queued for Paratext". Reopen
      Paratext, wait ≤10 s (the navigation probe flush) or press Refresh/retry.
      Expect: sent once; Paratext holds exactly one such note.

## B. Notes round trip, Paratext-origin, and automatic closure

- [ ] In Bridge, open a tN/tW finding › Resolve / Paratext › save a resolution and
      send it. Paratext shows the thread.
- [ ] In Paratext: reply, then **resolve** the thread.
- [ ] Bridge › Refresh (or just open the card). Expect, with **no click**: the
      resolution card shows status Resolved, the thread panel shows "resolved in
      Paratext · <Paratext user> · <date>", and the record history has one
      `resolved_from_paratext` event naming that user.
- [ ] Refresh again. Expect: nothing changes; still one event.
- [ ] Reopen the thread in Paratext (if the UI allows). Expect: Bridge's record stays
      resolved (reopen is not mirrored: a known, decided gap).

## C. The Scripture write (review queue)

- [ ] Create a QA note in Paratext on a verse with the structured shape
      (`[AI-QA R2] Check — Grammar`, `Original: <exact word>`, `Suggested: <new>`,
      `Reason: …`, `Confidence: 0.9 · Reviewer decision needed: No`).
- [ ] Bridge › Refresh › **Review queue…**. The proposal lists as "Literal
      correction"; the current text shows the word highlighted; After reads right.
- [ ] Tick **Also write to Paratext**, **Apply and next**. Expect: notice
      "Applied and verified. Written to Paratext and read back."; Bridge's verse
      changed; the list row shows "Paratext: written".
- [ ] In Paratext: the verse shows the replacement; nothing else in the chapter
      changed (compare the chapter's USFM before/after; footnotes intact).
- [ ] Export USFM from Paratext (and from Bridge): both carry the change.
- [ ] Repeat with Paratext closed: Bridge applies, "Queued for Paratext". Change
      the same word in Paratext by hand, reopen Paratext, let the flush run.
      Expect: "Paratext refused the write: … was not found …"; Bridge's text keeps
      its apply; Paratext keeps the hand edit; no second attempt on later flushes.
- [ ] A word that repeats in the verse: expect refusal "occurs N times"; nothing
      written on either side.
- [ ] A proposal with `Suggested: (delete)`: expect the confirmation dialog naming
      the exact text; after confirming, exactly that span is gone in both.
- [ ] Reports / recovery › **Revert latest verified correction…**: Bridge's verse is
      restored. (Connector 0.9.0: Paratext is not reverted. Connector 0.10.0,
      2026-11-03: the exact reverse is written there too; see section F.)
- [ ] Reports / recovery › Save session report; open the file in a browser.
      Export CSV; open in a spreadsheet: Tamil text intact, no formula executes.

## D. Limits to record

- [ ] Send/Receive after the walk, on the disposable project only: does the
      written verse survive a merge? (Paratext's own concern; record what happened.)
- [ ] Two reviewers resolving the same thread on two PCs linked to one hub: one
      closure on the record, not two.
- [ ] 1366×768: the review queue dialog fits; Apply and navigation stay visible with
      a long Tamil discussion.

## E. Connector 0.10.0: regions (2026-11-03, NOT RUN)

Install 0.10.0 (Bridge Settings › Connections › Update, Paratext closed). Record:
did `build.ps1` compile 0.10.0? `get_state` lists `text_regions` and `rename_marker`.

- [ ] A QA note with `Location: footnote` whose Original is a word in the verse's
      footnote. Review queue: the current text shows the footnote (`\f …\f*`),
      Apply with "Also write to Paratext". Expect both copies changed inside the
      footnote only; the same word in the verse body untouched.
- [ ] The same with `Location: cross-reference` (`\x …\x*`).
- [ ] `Location: heading` on the verse a `\s1` heading introduces. Expect Bridge's
      `<chapter>.headings.json` changed (the verse map not), Paratext's heading
      changed, the verse before it untouched.
- [ ] `Location: book introduction`. Expect Apply disabled until "Also write to
      Paratext" is ticked; then Paratext's `\ip` text changed; Bridge shows
      "Written in Paratext only" and verified.
- [ ] A heading proposal whose Original repeats in two headings at the verse:
      refused on both sides, nothing changed.
- [ ] Each of the four with connector 0.9.0 still installed: Bridge applies its
      copy, Paratext "queued … needs connector 0.10.0".

## F. Connector 0.10.0: marker rename and the two-sided revert (NOT RUN)

- [ ] A note with category `USFM marker`, `Original: \s1 <exact heading>`,
      `Suggested: \s2 <same heading>`. Review queue: "Rename marker and next"
      with "Also write to Paratext". Expect Paratext's marker changed, text
      unchanged, Bridge's heading tag `s2`; chapter USFM otherwise byte-identical.
- [ ] `Suggested: \q1 <same heading>` (outside the allowlist): refused, nothing changed.
- [ ] A rename whose heading text appears twice in the chapter: refused.
- [ ] Apply a body correction with "Also write to Paratext", then Reports /
      recovery › **Revert latest verified correction…**. Expect Bridge's verse
      restored, Paratext's verse restored ("Paratext reversed and read back"),
      and a comment "Correction … reverted in Bridge" on the thread.
- [ ] The same for a deletion (`Suggested: (delete)`): the reverse restores the
      deleted word in Paratext too.
- [ ] Change the verse by hand in Paratext after the apply, then Revert. Expect
      Bridge reverts its copy and Paratext refuses the reverse ("was not found");
      the notice says so; nothing in Paratext changed.
- [ ] Lock revocation: hold the chapter in Paratext's own editor mid-edit (or
      another plugin's lock) and Apply. Expect "WRITE_LOCK failed" / "withdrawn",
      Bridge's copy applied and verified, Paratext queued/refused, no partial write.

## G. Interrupted applies, queue scope, two devices, Send/Receive (NOT RUN)

- [ ] Kill Bridge (Task Manager) right after "Apply and next" on a verse. Reopen.
      Reports / recovery lists the verse under Uncertain edits with its class;
      "Mark verified" when the text reads right; the next apply on that verse is
      blocked until then.
- [ ] Books…: tick two books, start at the second. Expect the list begins with
      it and shows "After <last> the queue wraps around to <first>"; a proposal
      of the other book shows "not open"; **Open <book>** switches books and the
      queue keeps its place and drafts; Bridge restarted keeps the scope.
- [ ] **Show in Paratext** with the active Paratext window in group A: Paratext
      moves; with no group: the plugin's message is shown, nothing else.
- [ ] Reports / recovery › Save session report › **Open in browser**: the default
      browser shows the report; **Save report as…** to another folder works;
      a report of the project folder made read-only reports the write error.
- [ ] Two PCs on one hub, both linked to the same disposable Paratext project:
      resolve a linked thread in Paratext on PC 1; after sync, PC 2 shows the
      record closed once (one closure, one event), and resolving the same
      thread from PC 2 is refused as already resolved.
- [ ] Send/Receive after a region write and a rename, disposable project only:
      record whether the chapter survives the merge byte-for-byte.
- [ ] Window placement: move/resize Bridge, close, reopen: same place; unplug the
      second monitor it was on, reopen: the window is on screen.
- [ ] Startup visibility regression (#315, #435, fixed in daf1e3f): with an
      existing saved visible main window, restart and confirm only the small
      480×220 splash appears until startup completes. Check normal readiness,
      failure/Retry and closing the splash; the main window remains usable
      with remembered geometry. Rust checks pass; installed visual acceptance
      of this fix remains pending.

## Result

| Date | Who | Paratext | Connector | Sections passed | Failures / notes |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

### 2026-11-02: observed local connector and source-RPC acceptance (#438)

Paratext **9.5.110.1**, interfaces **2.0.100.0**, connector **0.9.0**.
Native writes used only **NSTest / Note Suggestions Disposable Test**;
Bridge processes used isolated settings and synthetic/imported projects.
The observations below do not check off UI actions that were not exercised.

| Check | Observed result |
| --- | --- |
| Compile against the actual installed interfaces | PASS after adapting both GetUSFMTokens reads to IEnumerable and materializing their sequences; the merged list assumptions produced CS0266. |
| Install and load | PASS through Bridge's existing elevated installer with Paratext closed; old connector backed up, native get_state reports 0.9.0 and put_verse_text. |
| Native Scripture write/readback | PASS: exact verse-body correction, wrong-project/stale-original/repeated-original refusal, other verses and footnote preserved. |
| Bridge review queue to both copies | PASS through actual source RPCs: native QA note parsed, preview, reviewer decision, Bridge save, Paratext save and verified readback. |
| Restoration and restart persistence | PASS: original native Scripture restored byte-for-byte through the supported API; the original hash still matched after restarting Paratext. |
| CSV and HTML report generation | PASS from the live review decision; UTF-8 BOM and passage evidence present. Browser/desktop report viewing was not exercised. |
| Checked revert | PASS on Bridge's copy; confirmed that Paratext remains changed until a separate supported native restoration. This remains a round-trip limitation. |
| External resolution of an issue-resolution record | PASS: real native reply/resolve automatically set the isolated Bridge record to resolved with one resolved_from_paratext event. |
| External resolution of finding/proposal links | PASS for synthetic record references with real native threads: persisted resolved-in-Paratext link closures and no duplicate on repeated refresh. No Stage 9B semantic proposal was generated by this test. |
| Offline queue and restart | PASS: note queued visibly while Paratext was closed, survived a new Bridge process, delivered once after reopening despite repeated flush, then resolved. A cleanup comment hit a busy-pipe timeout before sending; native resolution was retried separately without replaying note creation. |
| Focused automated tests | 87 passed (parser, notes panel, decided policy, review queue, record links and connector client). |
| Multi-chapter preservation | PASS on new synthetic BQAT090: chapter 2 remained byte-identical while chapter 1 changed; the other verse and footnote were preserved. The fixture's initial line endings were normalized by Paratext; a second apply/restore matched the native-format baseline byte-for-byte. |
| Frontend and frozen verification | Svelte check 0 errors/warnings, all 1,095 frontend tests, both production frontend builds and the rebuilt frozen-pair smoke passed. |
| Rust verification | cargo check passed; cargo test: 15 passed. |
| Internal desktop app | Built debug/no-bundle executable from isolated merged source plus the connector fix. Startup and the isolated one-project list were visually observed. Native picker/input automation was unreliable and concurrent desktop input was detected; the full notes/queue screen walk was not claimed. |

**Still unverified:** installed Bridge UI/layout at 1366x768, report viewing,
live lock revocation,
export/Send-Receive, and two-device synchronization. Headings, introductions,
footnote/cross-reference edits and marker changes remain review-only in this
implementation; this walk tested body-text correction only.

Local synthetic receipts and backup are under ignored
`engine/build/paratext-live-090/` and
`engine/build/paratext-walk-20261102/`. No working translation was edited.

The compatibility fix is published at **23497c0**; its GitHub CI run
**41445384036** passed. The ordinary installed Bridge application was not
replaced, and no public release or installer was produced by this walk.

### 2026-11-03: connector 0.10.0 host follow-up, with two blockers

Tested source **b9a43a1**, Paratext **9.5.110.1**, connector **0.10.0**.
This table records actual native/API observations, not an unchecked desktop
walk. Only the existing disposable **BQAT090** and **NSTest** were edited.

| Check | Observed result |
| --- | --- |
| Compile/install/load 0.10.0 | PASS against the installed interfaces. Bridge's elevated installer succeeded; native state reports `text_regions` and `rename_marker`. |
| Body and Tamil footnote edits | PASS through the real connector, with verified readback and complete native book restored byte-for-byte. BQAT090's other verse, footnote and chapter 2 were preserved. |
| Bridge queue footnote apply and two-sided revert | PASS through real source RPCs and the native connector: both copies verified, then restored; native book matched its baseline bytes. |
| Refusals | PASS: stale original, repeated original, body text requested as footnote, and a marker outside the rename allowlist changed no Scripture. |
| Confirmed deletion | FAIL, [#442](https://github.com/Bridgeconn/bridge/issues/442): Bridge leaves `Alpha  body.`; Paratext saves `Alpha body.`. Native readback correctly stays unverified and the completion gate blocks closure. |
| Deletion reverse | FAIL, #442: Bridge's checked revert restores its copy; Paratext refuses the reverse's double-space window. A separate exact supported native replacement restored the complete original book byte-for-byte. |
| Reports | PASS: HTML generation, explicit report destination, CSV export and UTF-8 BOM. In-app/browser opening and destination-error UI were not verified. |
| Automated/frozen gates | PASS: 249 Paratext-focused tests; Svelte check 0 errors/warnings; 1,108 Vitest tests in 108 files; both Vite production builds; cargo check and 18 Rust tests; both sidecars rebuilt and frozen smoke passed. |
| Current desktop build | BLOCKED, [#441](https://github.com/Bridgeconn/bridge/issues/441): Tauri CLI refuses Rust `tauri 2.12.5` versus the locked JavaScript API `2.11.1`. No compatibility check was bypassed. |

The two native QA threads created by this run were resolved after restoring the
Scripture. Local synthetic scripts, baselines and receipts are under ignored
`engine/build/joel-20261103/`; working translation data is not committed.
Results were posted on [#423](https://github.com/Bridgeconn/bridge/issues/423#issuecomment-6586494290).

The optional broader engine run was stopped at 26%; it is incomplete and is not
counted as a full-suite pass. The completed focused engine result is 249 tests.

**Still not verified:** positive cross-reference/heading/introduction writes or
marker rename; live lock revocation and interrupted apply; two PCs/hub and
Send/Receive; current Bridge desktop layout, keyboard/font/accessibility and
monitor changes; the in-app report-opening/error flows; release-build alignment
pointer-to-paint timing. The source and frozen passes do not close those rows.

### 2026-11-03: no-installer desktop follow-up (#444)

At Benz's request, built an isolated archive of origin/main **b1ffd40**
(0.24.3) with locked npm dependencies and an ordinary Tauri debug/no-bundle
build. Version compatibility checks passed; both Vite builds and the desktop
build completed. The existing frozen workers from the earlier b9a43a1
acceptance were reused; the engine displays **0.23.0**. This is development
desktop evidence, not acceptance of an exact 0.24.3 release package or installer.
The window config requested 1366x768; the actual desktop was visually inspected.

Paratext was launched and its local connector state read: **9.5.110.1 /
0.10.0**, with `text_regions` and `rename_marker`. No native Scripture or notes
were written. Desktop actions used a new isolated UIQA100 synthetic two-book
import/profile under ignored `engine/build/walkthrough-0243-data/`.

| Check actually walked | Result |
| --- | --- |
| Long Tamil reason, review dialog | PASS: reason scrolls inside its field; action buttons remain visible at the inspected size. Other text-size/scaling steps were not tested. |
| Keyboard next | PASS: Alt+N moves from body proposal to footnote proposal. This is not complete keyboard/screen-reader acceptance. |
| Footnote region preview | PASS: current footnote and after preview use the footnote text. No native footnote write in this run. |
| Two-book scope and starting book | PASS: TIT + PHM, start PHM; three proposals, PHM first, explicit wrap back to TIT, unopened book marked read-only. |
| Open sibling with queue retained | PASS: Open PHM materializes/opens the sibling; queue, scope and selected proposal stay present. Restart/draft persistence not tested. |
| Preset and confirmed local apply | PASS: Accepted fills comment without deciding; explicit Apply and next on PHM changes `second` to `other`, displays Applied and verified, and advances. Also write to Paratext was unchecked. |
| Reports | PASS: no-decision session reports no output; after apply, session HTML saves and renders in-app with before/after, reviewer and comment; Open in browser launches Chrome on that report. Destination/error/recovery paths not tested. |
| Desktop checked revert | FAIL: confirmation exists in accessibility tree but is hidden behind the queue; filed [#444](https://github.com/Bridgeconn/bridge/issues/444). No hidden confirmation was clicked. |
| Cleanup | PASS through existing source RPC after normal app exit: checked revert restores PHM 1:1 to `A second book.` and reports revertVerified. This is cleanup, not a desktop revert pass. |

The earlier #441 mismatch no longer blocks this isolated latest-source build.
#442 deletion normalization remains untested/unresolved here. Other outstanding
native regions, marker rename, locks/interruption, two-PC/hub, Send/Receive,
installer behavior, monitor/scaling/accessibility and release timing remain open.
No release/installer was created, no application logic was modified, and no
acceptance issue was closed.

### 2026-11-03: editor cache regression follow-up (#445)

Frontend-only fix: queue apply/revert now re-reads the saved affected chapter
and refreshes the editor's text/display or heading, edit count and alignment
readers, guarded against a project/book switch. The component regression failed
before this change and passed after it. Check 0 errors/warnings; full Vitest
1,115 passed in 109 files; both Vite builds and debug/no-bundle desktop build
passed in the isolated 0.24.3 acceptance copy, using the existing frozen workers
(engine reports 0.23.0).

On-screen, fresh disposable UIQA100: queue Apply `beta` -> `BETA` reports
Applied and verified; closing only the queue immediately shows `alpha BETA …
gamma` in the editor, edit count 1 and invalid alignment. No book reload or
restart was needed. Also write to Paratext was unchecked. A second footnote
apply/readback passed in the queue, but its editor popup was not walked after
concurrent user input was detected. Both test corrections were restored and
verified using the source checked-revert API. No native Scripture/notes were
written, and no working translation was edited.

Automated coverage also verifies refresh after revert, heading-only changes,
verse bridges, stale project responses and a read failure after successful
apply. #444 still prevents claiming desktop Revert acceptance; this run does
not repeat or complete the native two-application round trip or release gate.
