---
name: bible-proofreading-qa-any-language
description: Publishing-level proofreading QA of a Bible translation in any language against any reference Bible the checker chooses; runs a selected scope of books unattended with pause/stop, writes Paratext notes and a live report with cost after every book.
---

# Bible proofreading QA — any language, any reference Bible

Generalised from the Telugu IRV Round 2 check (66 books, 15,451 findings). Every finding is an AI
proposal for human review.

**Hard rule: never change, delete, rename, move or overwrite any Scripture file, or anything in the
translation project folder or the reference folder. They are read-only. Work on staged copies; write
outputs only to the output folder. Corrections are proposed in notes and workbooks, never applied.**

The toolkit lives in one folder (`bible-qa-universal`): `tools/`, `profiles/`, `guides/`, `templates/`.
On the checker's computer it is normally `D:\Claude Lab\Claude outputs\bible-qa-universal`. Stage the
whole folder into the session (or copy it from the outputs) and run tools with `python3 -I tools/<tool>.py`.

## 0. Set-up (once per project)

1. Stage the translation folder (all book files plus `Settings.xml`, `BookNames.xml`, `SpellingStatus.xml`,
   `ProjectBiblicalTerms.xml`, `TermRenderings.xml` if present — stage large files alone) and the reference
   Bible folder. The reference can be any Bible in USFM/SFM (ESV, NIV, a source-language-based version,
   another national version). Books are found by their `\id` line, so file names do not matter.
2. Copy `templates/config.example.json` to `config.json` and fill: `target_dir`, `reference_dir`,
   `reference_name`, `notes_user` (the Paratext user the notes belong to), `notes_language_tag`,
   `output_dir`, `device_output_dir`, `model`, prices. Ask the checker only for what cannot be found.
3. `tools/detect_language.py` — language, script, books found, profile in use.
4. If `profiles/<code>/` does not exist: run `tools/make_profile.py`, then write the language's rules into
   the profile (see `guides/how-language-rules-are-built.md`): spelling, grammar/agreement, case or
   particles, word division, register, punctuation and quotation, numbers, names; `lead_patterns`
   (regexes that find each problem); figures-of-speech notes. Tell the checker the profile is a DRAFT
   until a native linguist approves it; until then mark rows that rest only on draft rules Confidence
   Medium, decision Review. Review `candidates.tsv` with the checker; `approve_candidates.py` adds the
   approved ones.

## 1. Start a run

1. Ask the scope with AskUserQuestion unless already given: All 66 books / Old Testament / New Testament /
   a list or range (e.g. `GEN-DEU,PSA`, `MAT-JHN`).
2. `tools/queue.py start <scope>` — prints the estimated cost of the whole scope before work starts.
   Report it and begin; do not wait for approval unless the checker asked to approve the estimate.
3. Tell the checker how to control the run (section 3).

## 2. The loop — run every selected book without stopping

Repeat until `queue.py next` prints FINISHED, PAUSED or STOPPED:

1. Check control: list the device output folder; if a file named `PAUSE` or `STOP` is there, run
   `queue.py pause` / `queue.py stop`. Then `queue.py next` → `NEXT <BOOK> <offset>`.
2. Leads: `sweep.py BOOK`, `numchk.py BOOK`, `terms.py BOOK`. Leads are not findings.
3. Read the whole book against the reference: `dump.py BOOK intro`, `dump.py BOOK <from> <to>` (about three
   chapters at a time) and `dump.py BOOK ref C:V …` for every doubtful verse (`dump.py BOOK both C` shows a
   chapter side by side). Apply the profile's rules and `guides/checklist-meaning-and-theology.md`.
   Before reporting a spelling or word-division lead, count both forms with `q.py c`; a form common across
   the whole translation is house style — record it in REJECTED, do not report it.
   **Before reporting anything as missing** (Possible missed source word, Omission, a missing clause or
   name, Verse boundary), search the neighbouring verses for the meaning first: `nearby.py BOOK C:V
   [--window 3] [--find '<target word>' …]`. It shows the reference and the target for the verses around
   it with their relative lengths, where the team's key-term renderings, the numbers and the names actually
   stand, and where any word you suspect is missing occurs. Read the window for the sense, not only the
   words: a paraphrase, a pronoun, a merged or re-ordered clause carries the meaning too. Then decide:
   - **in-verse** (the meaning is there in other words) → no finding;
   - **found_another_verse / split_across_verses** → not an omission; report a Verse boundary row only
     when the move changes the sense or breaks the verse-numbering (a quotation's speaker, a promise's
     condition), Low or Medium, with a row at each verse involved; otherwise nothing;
   - **not_found** in the window or the chapter → report it as missing, and say in the Explanation which
     verses were searched (e.g. "not found in 4:18-24").
   A short verse next to a long one (x0.7 / x1.4 in `nearby.py`) means content moved, not lost.
4. Write `<work_dir>/rows/rows_<book>.py` from `templates/rows_template.py` (row rules below).
5. `build.py BOOK` until it prints `fail: 0`; resolve every OVERLAP line by narrowing or removing the
   hand-written row (automatic rows win). Re-read every High row against the reference.
6. `PT_BASE_OFFSET=<offset> deliver.py BOOK`; `merge_notes.py [live notes file from the project, if staged]`;
   `queue.py done BOOK`; `report.py`.
7. Copy to the checker's folder (device output folder): the book's three files, the cumulative notes file
   (SendUserFile it first, then commit by file id), `QA_Run_Report.xlsx`, `RUN_REPORT.md`, `run_state.json`.
8. SendUserMessage, 3–6 lines: book, findings (H/M/L), the main Medium/High items, cost of the book and
   total so far, next book. Then go straight on to step 1 — do not wait for "continue".

If the conversation is summarised, carry on from `queue.py next`; the state file remembers everything.

## 3. Pause, stop, resume (tell the checker)
- **Pause:** type "pause", or create an empty file named `PAUSE` in the output folder. The book in
  progress is finished and saved, then the run waits. **Stop** (`STOP` file or "stop") ends the run.
- **Immediate halt:** the Stop button in the app; the unfinished book is redone on resume.
- **Resume:** type "resume" (`queue.py resume`, which removes the PAUSE/STOP file), and the loop continues.
- **Change scope:** `queue.py start <new scope> --new`.

## 4. Checks
Universal (every language): Unicode normalisation; combining marks with no base, typed twice, virama +
vowel sign; mixed scripts in a word; Latin letters in a non-Latin text; ZWJ/ZWNJ, zero-width and no-break
spaces; double spaces; space before / doubled punctuation; straight quotes; quote pairs; verse-final
punctuation; marker pairs; verse bridges, order, empty and missing verses; verse length against the
reference; heading, poetry and footnote counts against the reference; digits against the reference;
repeated words and phrases; team's wrong-word list; book names against BookNames.xml; introduction
references and outline; key terms against the team's renderings.
Language-specific: everything in the profile (`rules`, `lead_patterns`, minority forms).
Meaning and theology: `guides/checklist-meaning-and-theology.md`.
Issue types (use these strings): Sandhi / word-joining; Source comparison; Punctuation; Textual-basis
review; Grammar; Footnote / cross-reference; USFM marker; Name consistency; Possible missed source word;
Confirmed typo; Possible typo; Plural agreement; Case/object marker; Theological consistency; Reviewer
decision; Addition - not in source; Harmonization; Heading; Numbers; Verse boundary; Factual; Style.

## 5. Row rules
- One finding = one row = one verse; a finding in several verses gets a row at each.
- Original must occur character for character in the verse, the heading before it, the footnote, or the
  introduction (chapter "Intro"). Headings: Original starts with `\s `.
- Suggested Correction is clean target-language text only — no English, no markers except in marker
  rows; empty when the item is a decision.
- Explanation in plain English with evidence (counts, verse references) and the effect; reference note
  = short phrase from the reference Bible with its verse.
- Severity: High = wrong or missing Scripture text that changes meaning; Medium = clear error a reader
  notices (wrong name or number, missing clause, team-marked misspelling); Low = spelling, spacing,
  punctuation, style, layout. Keep the same scale across the whole run.
- Report every finding, Low included. Notes are pinned on the exact words (build.py does this).

## 6. Cost
Claude cannot read its own token meter during the run. `cost.py` estimates tokens and dollars per book
from the book's size, calibrated on a measured run; prices are in config.json and must be checked against
the current price list. When actual figures are available (the Usage view, the API response `usage`
fields, or the Anthropic Console), record them: `queue.py done BOOK --usage in,cache_write,cache_read,out`.
The report always shows which books are estimate and which actual.

## 7. Final report
When FINISHED: totals by book, chapter, verse and issue type (QA_Run_Report.xlsx), High findings in
prose, checks that found nothing, notes total, time taken, cost (estimate/actual), and what still needs a
human: draft-profile rules, connotation, print layout.
