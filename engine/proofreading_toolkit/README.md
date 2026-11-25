# Bible proofreading QA toolkit — any language, any reference Bible

A copy of the Telugu IRV Round 2 skill, rebuilt so that it works for any translation language and any reference Bible. The original Telugu skill and the Telugu results are unchanged. This folder holds everything: the skill, the tools, the language profiles, the guides and the templates.

```
bible-qa-universal/
  SKILL.md                 the skill (also proposed for saving in the app)
  README.md                this file
  templates/config.example.json   copy to config.json and fill in
  templates/rows_template.py      the findings file Claude writes for each book
  tools/
    project.py             shared core: config, book discovery by \id, USFM parser, language detection, profiles
    detect_language.py     shows language, script, books found, profile used
    make_profile.py        drafts a profile for a new language from the translation's own text
    approve_candidates.py  turns approved candidate spellings into automatic checks
    corpus.py, q.py        whole-Bible counts and searches in the translation
    dump.py                prints chapters, the introduction, reference verses, side by side
    sweep.py               universal + language-specific + Paratext + reference checks (leads)
    numchk.py              numbers against the reference
    nearby.py              finds a verse's meaning in the neighbouring verses before anything is called missing
    terms.py               the team's Biblical Terms renderings
    build.py               verifies and locates every finding; adds automatic rows
    deliver.py             per-book workbook, CSV, Paratext notes
    merge_notes.py         cumulative Paratext notes file (keeps replies and resolutions)
    queue.py               scope selection, run queue, pause / stop / resume
    report.py              live run report (by book, chapter, verse, issue type) with cost
    cost.py                token and dollar estimate per book and for any scope
  profiles/
    te/                    Telugu — built from the 66-book check (rules, 32 lead patterns, 46 automatic minority-spelling checks)
    generic/               any language: universal checks only, until a profile is made
  guides/
    how-language-rules-are-built.md
    checklist-meaning-and-theology.md
```

## Answers to your questions

**1. Any target language, with checks specific to it?** Yes. The language is detected from the Paratext `Settings.xml`, or from the script of the text itself. The universal checks (Unicode, USFM, punctuation, verse structure, reference comparison, Paratext data) run for every language. The language-specific checks come from `profiles/<language>/`. Telugu has a full profile. For a new language, `make_profile.py` drafts one from the text, Claude writes that language's rules into it, and a native linguist approves it before a publishing run.

**2. Any reference Bible?** Yes. Point `reference_dir` at any Bible in USFM/SFM files and set `reference_name`. Books are matched by their `\id` line, so the file names do not matter. The number check reads English number words only when the reference is in English; digits work for any reference.

**3. Select the scope, run without stopping, pause or stop?** Yes. `queue.py start all | OT | NT | GEN-DEU,PSA` sets the scope and shows the estimated cost. The skill then runs book after book without asking. To pause or stop, type "pause" or "stop", or put an empty file named `PAUSE` or `STOP` in the output folder. The book in progress finishes and is saved first. "resume" carries on. The Stop button in the app halts at once; the unfinished book is redone. The run state is kept in a file, so it survives a closed laptop or a new session.

**4. Report after every book, by verse, chapter and book, with cost?** Yes. After each book the cumulative Paratext notes file, `QA_Run_Report.xlsx` and `RUN_REPORT.md` are rebuilt and copied to your folder. The report has these sheets:

- Overview
- By book (findings, High/Medium/Low, cost, time)
- By chapter
- By verse
- By issue type
- High & Medium

Cost is an estimate unless you enter the actual usage figures (see the limits below).

**5. Where do each language's rules come from?** They are built in five layers, and each finding shows which layer it came from (see `guides/how-language-rules-are-built.md`):

1. Universal Unicode and USFM rules.
2. The team's own Paratext data: wrong-word list, key-term renderings, book names.
3. The translation's own usage. Rare variants of common spellings are measured across all books and approved by the checker.
4. Grammar, spelling and style rules for the language, drafted by Claude and approved by a native linguist.
5. Meaning and theology: comparison with the reference Bible using a fixed checklist (`guides/checklist-meaning-and-theology.md`). The checklist covers figures of speech (idioms, similes and metaphors, rhetorical questions, euphemisms, metonymy, divine passive, parallelism) and key terms.

**6. All the tools and scripts in one folder:** this folder.

**7. Is it possible?** Yes. The tools were tested end to end:

- on the Telugu IRV against the ESV (Daniel, Obadiah, Jonah reproduce the earlier results exactly), including pause and resume;
- on the ESV as target with the Telugu as reference, to prove that the language-independent path works for a language with no profile.

## Honest limits

- **Cost** is an estimate during the run. Claude cannot read its own token meter. The estimate is calibrated on the measured Telugu run (about $0.15 per 1,000 characters of verse text, about $570 for a whole Bible at the assumed Opus prices). The prices in `config.json` are assumptions; check them. For exact figures, use the app's usage view, or run through the API, where every response reports its tokens, and enter them with `queue.py done BOOK --usage …`.
- **Unattended means while the session is running.** A whole Bible takes many hours. If the session is closed, the run waits and continues from the saved state when you say "resume".
- **New languages:** the quality of the language-specific checks depends on the profile. Until a native linguist has reviewed it, findings that rest on draft rules are marked for review.
- **Not checkable from text:** print layout (line breaks, hyphenation, fonts) and connotation.
