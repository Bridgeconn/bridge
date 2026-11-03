# Paratext round trip: native-function parity and the write contract (#424, #425)

The findings of the #424 spike and the contract every Paratext write in Bridge
follows, written down so nothing has to be taken on trust. Host facts come from
Benz's walk on Paratext **9.5.110.1** / plugin interfaces **2.0.100.0** (2026-11-02,
`PARATEXT_HOST_ACCEPTANCE_CHECKLIST.md`) and from `selvabenz/Paratext-sug-in-context-menu`,
the reference plugin compiled and run on that host (reuse permitted by its
owner, Benz, DECISIONS 2026-11-02; the repository carries no licence file).
Everything not listed as observed on the host is a source-level claim.

## 1. Native-note parity inventory

What Bridge can do with a Paratext Project Note through the connector
(`paratext_plugin/AiBridgeConnectorPlugin.cs`, 0.10.0), and what it cannot.

| Native function | Bridge | How / limitation |
| --- | --- | --- |
| Create a thread on a verse, anchored on a selection | **Supported** (observed) | `create_note`: project by Guid, verse reference, selected text unique in the verse (the note's before/after context tells repeats apart). Refused when the selection occurs more than once. |
| Read threads, comments, status, assignment, tags | **Supported** (observed) | Bridge reads every `Notes_<User>.xml` of the linked folder (#357); the plugin's `list_notes` is used only to find a thread's key. |
| Reply | **Supported** (observed) | `add_comment` on a thread found by its anchor and first comment; the plugin API gives a note no id, so author + created is its identity. |
| Resolve | **Supported** (observed) | `resolve_note`; Bridge-origin resolves write "Resolved in Bridge." first. |
| Reopen a resolved thread | **Not supported, policy** | Not exposed by the plugin API we use; a reopen is a separate policy question (#424). A Bridge record closed by an external resolve stays closed if the thread is reopened. |
| Delete a note or a comment | **Not supported, policy** | Never. |
| Edit a comment's text | **Not supported** | The API appends; Bridge never rewrites what someone wrote. |
| Assign / reassign | **Not supported** | `assignee` is accepted by `create_note`/`add_comment` and passed to the host unchanged; Bridge's UI never sets it. Reassignment is not offered. |
| Native tags | **Read only** | Tags and their names are shown; none are written. |
| Rich content (links, images) | **Not supported** | Plain text only, as the plugin API writes it. |
| Visibility / hidden notes | **Read only** | `hidden` is shown; never changed. |
| Identity: who wrote it | **Host-defined** | Paratext records its logged-in user as the author of everything the plugin writes. The Bridge user is named on the first line (`[Name (id) via Bridge]`) and in Bridge's evidence; never impersonated. |
| Permissions | **Host-enforced** | `CanEdit` is asked before every Scripture write; a note write fails with the host's own error when the user may not write notes. |
| Scripture: verse body text | **Supported** (observed) | `put_verse_text`, region `body`. |
| Deleting text between two spaces | **Supported** (source) | #442: the deletion takes the space after it, so one space remains. Paratext 9.5.110.1 collapses a double space on save, which left the bare deletion unverifiable and its reverse unlocatable. The decision's `original`, the Paratext write and the reverse all carry that space. Not widened at the start of the text, before punctuation, or across markup. |
| Scripture: footnote / cross-reference text | **Supported** (source) | `put_verse_text`, region `footnote` / `crossReference`: the verse's note tokens only. NOT RUN on the host. |
| Scripture: heading text | **Supported** (source) | region `heading`: the heading tokens the verse introduces (Paratext anchors them on the verse before). NOT RUN on the host. |
| Scripture: book introduction | **Supported** (source) | region `introduction`: chapter 0 to the token API. Bridge keeps no copy; Paratext-only. NOT RUN on the host. |
| Heading-marker rename (\s1 → \s2 …) | **Supported** (source) | `rename_marker`: ms/ms1–3, s/s1–4, cl, cd only, label unchanged, unique at the anchor, round-tripped through Paratext's parser first. NOT RUN on the host. |
| Verse/chapter renumbering, note movement, attributes, any other restructuring | **Not supported, policy** | Review-only in Bridge; the proposal is shown, nothing is written. |
| Scroll groups A–E | **Partly** | `set_reference` moves the **active** window's group; the plugin refuses when that window is in no group. Choosing a group from Bridge is not in the API we use. |

Operations that need Paratext running: every write (notes and Scripture) and
`set_reference`. Reading notes, parsing proposals, the review queue and every
Bridge-side apply work with Paratext closed; writes wait in the outbox.

## 2. Ownership of the text

- **Bridge's copy is what Bridge edits.** A correction is applied to Bridge's
  verse map (or heading file) first, through the one Scripture writer, and
  verified by read-back. Only then, and only when the reviewer ticked "Also
  write to Paratext", is the same exact replacement sent to Paratext.
- **Paratext's copy is written by Paratext.** The plugin locates the exact
  original in the region's tokens under the host's chapter write lock, replaces
  one token's text, writes with `PutUSFMTokens`, and reads the chapter back;
  `verified` is true only when the saved USFM equals what was expected.
- **Two regions exist only in Paratext**: the book introduction (Bridge keeps no
  copy) and a marker rename (Bridge's heading file follows the tag). They are
  applied with "Also write to Paratext" and verified by Paratext's read-back
  alone; the decision says `bridgeCopy: none` / `heading`.
- **Stale-baseline detection.** Bridge refuses a write unless the verse still
  reads exactly as when the reviewer looked (`expected_old_text`). Paratext
  refuses when the original is absent or repeated. Neither side ever
  last-writer-wins; the refusal is final for Scripture (never retried blind)
  and shown with its reason.
- **Two-sided refresh.** After a Paratext write Bridge re-reads nothing from
  Paratext's Scripture (Bridge's copy was written first); the notes index is
  re-read on refresh. Bridge's verse is read back after its own write.

## 3. Recovery contract

| Situation | What Bridge records | What the reviewer does |
| --- | --- | --- |
| Bridge apply succeeded, Paratext not reachable | decision `applied`, verified; `paratext.status = queued` | Nothing; the outbox sends when Paratext answers. The thread cannot be resolved from Bridge until the write is verified there. |
| Bridge apply succeeded, Paratext refused (text moved) | `paratext.status = refused`, reason | Looks in Paratext; the refusal is final; a manual completion or a rejection closes the item. |
| Bridge write happened but verification did not run (crash) | `applied`, `verified: false` | Reports / recovery classifies it against the current text: **verified** (post-image), **notApplied** (pre-image, back to the queue), **conflict** (neither; blocks applies on the verse until decided manually). |
| Paratext wrote but could not read back | `paratext.sent`, `verified: false` | "Checked in Paratext" records the look; the thread stays unresolved until then. |
| Revert | `reverted`, both copies checked against their post-image; Paratext reverse write queued with the exact reverse replacement; a comment on the thread | A reverse that cannot be built exactly (no neighbouring words) is reported "manual"; nothing is approximated. |
| Resolve saved, Paratext away | outbox `resolve` queued | Retry sends the resolve only; a correction is never reapplied by a retry. |
| External resolve seen more than once (repeated delivery, re-reads) | one closure per link, one `resolved_from_paratext` event | Nothing. Idempotent by link row. |
| Thread deleted or not readable | link kept, no closure | Nothing is closed by guess. |
| Record resolved in Bridge, then its echo returns resolved from Paratext | closure origin `bridge`, "resolved in Bridge" | Nothing. |
| Proposal's comment edited in Paratext | new proposal id; old draft dropped and reported | Decides the new proposal; the old decision stays in history. |

## 4. Attribution

Every Bridge note write names the Bridge user (`[Name (id) via Bridge]`), the
outbox row carries `bridgeUser`, and every decision, CSV row and HTML report
carries the Bridge user's id and display name, Paratext's own editor of
record (`author`, from the host), the save verification and where the thread
was resolved (`resolved in Bridge` / `resolved in Paratext`, with the actor).

## 5. Licensing

The reference plugin has no licence file; its owner permits use and
redistribution for Bridge (DECISIONS 2026-11-02). Bridge's connector reuses
its token-API shapes and its region mapping; nothing of it is vendored.
