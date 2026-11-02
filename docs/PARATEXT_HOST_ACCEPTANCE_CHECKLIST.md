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
      restored; Paratext is **not** reverted (the revert is Bridge-side only, by
      design); record this limitation.
- [ ] Reports / recovery › Save session report; open the file in a browser.
      Export CSV; open in a spreadsheet: Tamil text intact, no formula executes.

## D. Limits to record

- [ ] Send/Receive after the walk, on the disposable project only: does the
      written verse survive a merge? (Paratext's own concern; record what happened.)
- [ ] Two reviewers resolving the same thread on two PCs linked to one hub: one
      closure on the record, not two.
- [ ] 1366×768: the review queue dialog fits; Apply and navigation stay visible with
      a long Tamil discussion.

## Result

| Date | Who | Paratext | Connector | Sections passed | Failures / notes |
| --- | --- | --- | --- | --- | --- |
| | | | | | |
