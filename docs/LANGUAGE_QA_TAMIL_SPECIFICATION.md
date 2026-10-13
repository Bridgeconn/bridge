# Tamil publication QA: the 56-item framework, owned

This is Bridge's working standard for **publication-worthy Tamil Scripture** (the
IRV project first). It lays out 56 proofreading items in six gates. For each item
it says whether Bridge checks it, and with which rule, and who owns the item when
Bridge does not.

The framework began as an outside methodology review of the IRV proofreading
workflow (the Joel Round 2 master workflow, Paratext's publication guidance,
USFM, Unicode and W3C Tamil material, and Tamil Virtual Academy grammar). That
review was pasted here verbatim in #169. This version replaces it:

- the six gates and 56 items are kept;
- each item gains a Status and an Owner;
- Bridge's pack ids are added;
- the prose is condensed;
- the tracking links are removed. The sources are listed once, at the end.

**Maintainer of this page:** @RevantCI. Change a Status only in the commit that
changes the behaviour, and cite the rule id.

Related:

- `docs/LANGUAGE_QA_RULE_PACK.md`: the rules and their schema.
- `docs/LANGUAGE_QA_BENCHMARK.md`: how well each rule does against the IRV
  reviews.
- `docs/LANGUAGE_QA_PLAN.md`: the phase table.

## Status and Owner

**Status**

| Value | Meaning |
|---|---|
| **Checked** | A Bridge rule finds this and reports it as a finding. The pack id is given. The rule may still miss cases; see the benchmark for recall. |
| **Partial** | A Bridge rule covers one named shape of this item and nothing else. The rest is the Owner's. |
| **Assisted** | Bridge shows the evidence (alignment, source coverage, terms) but does not judge the item. A person decides. |
| **Planned (Pn)** | Scheduled in phase *n* of the layered-rules plan. Not built yet. |
| **Not checked** | Outside what an offline text checker can decide. Owned by a person, and listed so that the boundary is explicit (Phase 7 shows it in the panel). |

**Owner** is who answers for the item at publication. That is Bridge only where
the Status is Checked, and even then a person acts on each finding. The owners
are: *Translator* (the translation team), *Proofreader* (Round 2 linguistic
proofreading), *Consultant* (exegetical and consultant check), *Typesetter*,
*Publisher* (release master and final acceptance), and *Bridge*.

Rule ids:

- `ta-irv/…` ids are pack rules (`engine/language_packs/ta-irv/`).
- `common/…` ids are language-neutral rules in `language_qa.py`.
- `wildebeest.*`, `usfm.*` and `names.*` are the Greek Room adapters.
- Stage 6B–8 are the semantic pipeline.

## Gate 1: Tamil language correctness

A verse does not move on while obvious Tamil errors remain.

| # | Item | What it covers | Status | Bridge rule / evidence | Owner |
|---|---|---|---|---|---|
| 1 | Spelling (எழுத்துப்பிழை) | Missing, extra or transposed letters. Wrong consonant or vowel sign, குறில்/நெடில், புள்ளி. Confusable pairs ர/ற, ல/ள/ழ, ந/ன/ண. Grantha use. | Checked | `ta-irv/lexicon.known-misspelling` (curated corrections; inline; 72 of 79 human-confirmed over three rounds); the IRV defect shapes `ta-irv/typo.divine-name.vowel-drop` and `.dative-stem` (whole populations labelled, 11 of 11 and 13 of 13), `ta-irv/typo.suffix.dropped-tha`, `ta-irv/typo.participle.sentence-final`; the indic-qa layer's `indicqa.lex.near-miss` (vowel length, confusable consonants, pulli, transposition; panel only, 8 of 38 right on 2026-10-13) and `indicqa.lex.unknown` (words outside the OV dictionary; 9 of 42). `ta-irv/lexicon.rare-near-common` and `ta-irv/tamil.repeated-word` stay **disabled** (0 of 21, 0 of 20). Grantha use has no rule of its own. Checked on Benz's decision of 2026-10-13 (#258); the gaps are named here | Proofreader |
| 2 | Word form and morphology | Noun and verb inflection, tense, finite/non-finite forms, participles, negative and honorific forms. | Not checked | The corpus lexicon flags a rare form near a common one. It does not judge grammar, and an unusual but correct inflection is a false positive to ignore. | Proofreader |
| 3 | சந்தி / புணர்ச்சி | Where வல்லினம் doubles (மிகும்) and where it does not (மிகா). Joining and splitting; suffix and case-marker joining. | Partial | `ta-irv/sandhi.vallinam.demonstrative`, `.manner-adverb`, `.accusative`, `.dative` (-க்கு and -ற்கு; missing link), `ta-irv/sandhi.vallinam.wrong-consonant`, `ta-irv/sandhi.compound.direction` (கிழக்குக் காற்று). Inline on human-labelled precision (2026-09-28 review): dative 100% and accusative 94.6%; the others are panel-only until a sample of 20 exists. No doubling before தேவ- forms (house style); a proper noun does not block doubling. Unnecessary வல்லினம் (மிகா இடம்) is **not checked**. | Proofreader |
| 4 | Word division | Wrongly split or wrongly joined units: compounds, postpositions, clitics, name + suffix. | Checked | Split words: `ta-irv/lexicon.known-split` (curated pairs such as சு வரை → சுவரை; inline, 10 of 10 labelled, 11 of 11 in the collection). Joined words: `indicqa.lex.compound` (two known words written as one; panel only, 12 of 26 right on 2026-10-13). Clitics: the வல்லினம் rules apply the reviewer's house style (தான் and ஆவது fused; கூட, மட்டும், போல, என்று, என, எனும் apart without doubling); `ta-irv/sandhi.clitic.fused` is **disabled** (it caught the pronoun தான், round 2). Postposition and name + suffix division have no rule of their own. Checked on Benz's decision of 2026-10-13 (#259); the gaps are named here | Proofreader |
| 5 | வேற்றுமை / case suffixes | Missing, unnecessary or wrong case. Inconsistent case across coordinated nouns. | Not checked | The accusative and dative rules check only the sandhi after a case form, not the choice of case. | Proofreader |
| 6 | Number, person and gender agreement | Subject and verb, honorific singular, pronoun and antecedent, singular and plural against the source. | Not checked | | Proofreader, Consultant |
| 7 | Tamil syntax | Clause relationships, modifier attachment, subject and object reversal. | Not checked | | Proofreader |
| 8 | Sentence completeness | Incomplete sentences, unfinished quotations, clauses split across verses, duplicated clauses. | Assisted | Stage 8 source coverage shows omitted source content. It does not judge Tamil completeness. | Proofreader |
| 9 | Tamil punctuation | Duplicate punctuation, spacing around punctuation, unbalanced pairs, punctuation near notes and markers. | Checked | Duplicates: `common/punctuation.repeated`, `indicqa.punct.repeated`. Spacing: `common/punctuation.space-before`, `indicqa.punct.no-space-after`. Unbalanced pairs: `common/punctuation.unbalanced-pair` (brackets, per verse) and `common/punctuation.unbalanced-quote` (curly quotes, per chapter, since a quotation may run over verses) (#264). Near notes and markers: `ta-irv/integrity.space-before-note-end`, `common/note.space-before-caller`. Punctuation policy (comma versus full stop) is house style, the Proofreader's | Proofreader |
| 10 | Register and written Tamil | Deliberate, consistent register; accidental colloquial, regional or English-influenced forms. | Not checked | The house-style learner (`housestyle.py`) records what this project has decided is not a problem. It does not judge register. | Translator |

## Gate 2: Meaning and translation quality

| # | Item | What it covers | Status | Bridge rule / evidence | Owner |
|---|---|---|---|---|---|
| 11 | Verse-by-verse source fidelity | Omissions, additions, meaning shifts against the source. | Assisted | Stage 6B location, Stage 7 meaning preservation and Stage 8 bidirectional coverage, reviewed in the 9A queue. The confidence values are uncalibrated. | Consultant |
| 12 | Negation | A lost, added or reversed negative. | Assisted | Stage 7 POLARITY. **Known limitation on Tamil:** Tamil negatives are split by the comparator, and the check reports false contradictions. This is pinned by `test_tamil_negation_polarity_limit_is_pinned_not_worked_around` and is scheduled work. | Consultant |
| 13 | Pronoun and reference tracking | Who does what to whom; divine and human referents. | Assisted | 4,741 tN notes are about this: `writing-pronouns`, `figs-123person`, `figs-you`, `figs-youdual`, `figs-exclusive`, `writing-participants`. The tN check (translationNotes, unfoldingWord v90, bundled for 56 books; NUM, 1CH, 2CH, ECC, ISA, JER, EZK, DAN, AMO and ZEC have none) presents each note on its verse for the Consultant to decide. Assisted on Benz's decision of 2026-10-13 (#266) | Consultant |
| 14 | Logical relationships | Cause, result, purpose, contrast, condition. | Assisted | 4,590 tN notes are about this: `grammar-connect-logic-result`, `-goal`, `-contrast`, the `grammar-connect-condition-*` notes, `grammar-connect-time-sequential`, `grammar-connect-words-phrases`. The tN check (translationNotes, unfoldingWord v90, bundled for 56 books; NUM, 1CH, 2CH, ECC, ISA, JER, EZK, DAN, AMO and ZEC have none) presents each note on its verse for the Consultant to decide. Assisted on Benz's decision of 2026-10-13 (#267) | Consultant |
| 15 | Figures of speech | Idioms, metaphors, and whether a figure is kept or explained. | Not checked | tN notes are shown as resources. | Consultant |
| 16 | Implicit information | What is made explicit, and whether it is justified. | Not checked | | Consultant |
| 17 | Accuracy, clarity, naturalness, acceptability | The four translation-quality criteria. | Not checked | | Consultant, Translator |
| 18 | Comprehension testing | Community testing with target readers. | Not checked | | Translator |
| 19 | Read-aloud check | Reading aloud for flow, ambiguity and unintended sound. | Not checked | | Translator |

## Gate 3: Biblical consistency and consultant QA

| # | Item | What it covers | Status | Bridge rule / evidence | Owner |
|---|---|---|---|---|---|
| 20 | Biblical key terms | One rendering per key term, or deliberate variation. | Checked | `terminology.deprecated-form` against the project's termbase (termbase v3: listed inflected forms, and case endings in prefix mode at medium confidence); tW resources shown. It checks what the team has put in the termbase: an empty termbase checks nothing. Checked on Benz's decision of 2026-10-13 (#260); the gaps are named here | Consultant |
| 21 | Proper names | Consistent spelling of names across books; names with suffixes. | Partial | `names.spelling_similarity` (names adapter); `project/name.minority-spelling` against the approved `housestyle.properNouns` list. The vallinam rules no longer abstain on it: after a case form a name needed doubling in 17 of 25 reviewed cases | Translator |
| 22 | Parallel passages | Synoptic and quoted passages rendered consistently. | Not checked | | Consultant |
| 23 | Textual-basis review | Which source text and which variants the translation follows. | Not checked | | Consultant |
| 24 | Numbers, money, weights and measures | Consistent numerals and units, and the numeral policy. | Not checked | `ta-irv/integrity.digits-in-text` exists but is **disabled**: digits are an IRV house form (Pass 3 §5). | Translator |

## Gate 4: USFM and digital-text integrity

| # | Item | What it covers | Status | Bridge rule / evidence | Owner |
|---|---|---|---|---|---|
| 25 | Chapter and verse structure | Missing, duplicated or out-of-order verses; versification. | Checked | USFM structural checker (`usfm.*`); versification support | Bridge |
| 26 | USFM markers | Valid and closed markers, correct nesting. | Checked | USFM structural checker | Bridge |
| 27 | Footnotes | Note markup and the text inside notes. | Checked | Markup: USFM checker for structure; `common/footnote.missing-ft` (note text with no `\ft` after the `\fr` reference, with the fix that inserts it; 3 of 3 confirmed 2026-10-13, #245); `ta-irv/integrity.space-before-note-end` (a space before `\f*`/`\x*`). Text: the indic-qa layer reads footnote text (spelling, sandhi; `context: footnote`). Whether a note says the right thing is the Proofreader's | Proofreader |
| 28 | Cross-references | Reference markup and targets. | Checked | Markup: USFM checker. Targets: `common/xref.target-missing` (a reference in `\xt` whose chapter or verse exists in none of the six standard versifications; book names from every collection book's `\toc3`/`\toc2`/`\h`; an unknown name only in a whole Bible). Origin: `common/xref.origin-mismatch` (`\xo` not this verse; fix offered). IRV: 5,973 references checked, all exist (#249) | Proofreader |
| 29 | Words of Jesus | `\wj` coverage and boundaries. | Partial | Boundaries: `common/wj.glued` (a word right after `\wj*`, MRK 2:14) and `common/wj.space-inside` (`… \wj*word`, LUK 24:26), each with its fix; `common/wj.outside-speech` (`\wj` outside the Gospels, Acts, Revelation, 1 Corinthians 11 and 2 Corinthians 12, 1TI 5:18; fix removes the markers). 3 of 3 confirmed 2026-10-13 (#248). An unbalanced `\wj` stops the verse being scanned and is reported as a limitation. Coverage, whether every word of Jesus is marked, is **not checked** | Proofreader |
| 30 | OT/NT quotation markup | Quotation markers and their extent. | Not checked | | Proofreader |
| 31 | Headings and section titles | Presence, wording, consistency. | Checked | Consistency: `common/heading.trailing-punctuation` (a `\s`/`\ms` title ending in . , ; or :; 25 of 25 confirmed 2026-10-13) and `common/heading.marker-mixed` (`\s` and `\s1` mixed in a book; 4 of 4). Presence: `common/heading.missing` (a chapter with no heading where four in five have one; none in the IRV). Wording: the indic-qa layer reads the headings (spelling, sandhi). All panel only, `context: heading` (#244) | Translator |
| 32 | Paragraphing and discourse formatting | Paragraph breaks, discourse markers. | Not checked | | Typesetter |
| 33 | Poetry | Poetry markers and indentation levels. | Checked | Markers: the USFM checker. Indentation: `common/poetry.q2-without-q1` (an indented line with no first-level line before it in its stanza; MAT 4:6 in the IRV) (#265). The level right after `\c` or a heading is not in the stored verse text, so a poem opening at `\q2` there is not caught. Line breaks inside poetry are treated as whitespace, not as control characters. | Typesetter |
| 34 | Special textual structures | Lists, genealogies, acrostics, letters. | Not checked | | Typesetter |
| 35 | File encoding | UTF-8 with no mixed or legacy encodings. | Checked | UTF-8 on every read and write; `common/unicode.corruption` (U+FFFD) | Bridge |
| 36 | Unicode normalization | NFC; canonical Tamil sequences. | Checked | `common/unicode.nfc`, `wildebeest.non_canonical` | Bridge |
| 37 | Grapheme integrity | Dependent signs with no base, malformed sequences, mixed scripts in a word. | Checked | `ta-irv/tamil.dependent-sign`, `ta-irv/tamil.mixed-word`, `wildebeest.script.mixed`, `common/unicode.private-use` | Bridge |
| 38 | Invisible characters and spaces | ZWJ/ZWNJ, NBSP, unusual or doubled spaces. | Checked | `common/unicode.invisible`, `common/spacing.unusual`, `common/spacing.extra`, `wildebeest.zero_width` | Bridge |

## Gate 5: Typesetting and visual publishing proof

Bridge has no typesetting engine. Every item in this gate is proofed on the PDF.

| # | Item | What it covers | Status | Owner |
|---|---|---|---|---|
| 39 | Tamil font rendering | Conjuncts, vowel signs and pulli render correctly in the chosen font. | Not checked | Typesetter |
| 40 | Line breaking | No breaks inside a grapheme cluster; acceptable break points. | Partial | Typesetter |
| 41 | Hyphenation | Tamil hyphenation policy. | Partial | Typesetter |
| 42 | Page-level composition | Widows, orphans, column balance, spacing. | Not checked | Typesetter |
| 43 | Running heads and page numbers | Correct book/chapter heads. | Checked | Typesetter |
| 44 | Footnote composition | Note placement and callers. | Checked | Typesetter |
| 45 | Cross-column reading order | Text flows in the right order across columns. | Not checked | Typesetter |
| 46 | Maps, captions and illustrations | Tamil labels, name spellings consistent with the text. | Not checked | Typesetter |
| 47 | Front and back matter | Title page, contents, glossary, maps index. | Partial | Publisher |

Item 44 is checked in the USFM, before typesetting: `common/note.caller-mixed` flags a `\f`/`\x` caller unlike the book's others (IRV: `\x -` at JOL 2:28 and RUT 2:1, 2 of 2 confirmed 2026-10-13) and `common/note.space-before-caller` a space between a word and its note's caller (53 footnotes; Benz, 2026-10-13), each with its fix (#246). Where the note text falls on the page is still proofed on the PDF.

Item 47 is checked in the book header and introduction (context `introduction`, #253): `common/header.missing` (no or empty `\toc1`, `\toc2`, `\toc3` or `\mt`: the title page and the contents), `common/intro.ior-space` (a space inside `\ior … \ior*`; MAT, 3 of 3 confirmed 2026-10-13) and `common/intro.ior-target` (an outline reference to a chapter that does not exist). The glossary and the maps index are separate books the IRV does not have, and are **not checked**.

Item 43 is checked in the USFM: `common/header.running-head` flags a running head `\h` that differs from the book title `\mt` (Benz, 2026-10-13: the running head repeats the title; in the IRV, LAM and ACT), and `common/header.missing` a missing `\h` (#254). Chapter heads come from `\c`; page numbers are proofed on the PDF.

Item 41 is checked in the text: a soft hyphen (U+00AD) typed into a word is reported by `common/unicode.invisible` (#257). The hyphenation policy itself is the Typesetter's, proofed on the PDF.

Item 40 is checked in the text: a line break or a space inside a Tamil grapheme cluster leaves a vowel sign or pulli with no base, and `ta-irv/tamil.dependent-sign` reports it (#256). Where lines break on the page is proofed on the PDF.

## Gate 6: Final publication acceptance

| # | Item | What it covers | Status | Bridge rule / evidence | Owner |
|---|---|---|---|---|---|
| 48 | Run every automated check | All checks run and clean, or every finding decided. | Planned (P4) | Language QA as a check-framework stage, the collection runner and the publication gate | Publisher |
| 49 | Whole-Bible wordlist audit | Every word form reviewed across the Bible. | Assisted | The Language QA panel's **Book words** tab (`languageQa.bookWords`): every word of the book outside the pack's dictionary, most frequent first, with its count in the book, in the whole IRV and in the OV, its status and its first place; the reviewer adds a word to the project's dictionary there. A person reviews it book by book. `ta-irv/lexicon.rare-near-common`, the automatic version, stays disabled (2026-09-28 review, 0 of 21) (#255) | Proofreader |
| 50 | Whole-Bible glossary audit | Glossary terms used consistently. | Checked | Termbase v3 on every verse; the collection QA run's termbase coverage report (approved renderings never used, rejected ones still present, per book). Checked on Benz's decision of 2026-10-13 (#261); the gaps are named here | Consultant |
| 51 | Whole-Bible proper-name audit | One spelling per name across all books. | Checked | `names.spelling_similarity`; the collection run's cross-book names stage; `project/name.minority-spelling` against the approved names list. Both compare whole words, so a name with a case suffix is only caught when it is close enough (see item 21). Checked on Benz's decision of 2026-10-13 (#262); the gaps are named here | Translator |
| 52 | Final blind proofread | A fresh reader who has not seen earlier rounds. | Not checked | | Proofreader |
| 53 | Final consultant sign-off | The consultant's approval. | Not checked | | Consultant |
| 54 | Final community read-through | A community reading before release. | Not checked | | Translator |
| 55 | Regression check after every late correction | A late fix introduces no new error. | Checked | Language QA re-checks an edited verse at once. Stage 9B.3 re-runs affected analysis after a correction. The exception queue lists open high findings, and the export ledger lists every Language QA change. Checked on Benz's decision of 2026-10-13 (#263); the gaps are named here | Publisher |
| 56 | Source and version provenance | Which source files and which version were published. | Checked | `.bridge/import.json` SHA-256 provenance; `ruleVersion`/`packVersion` on every finding; the export ledger (`<book>.language-qa-changes.csv`) | Publisher |

## Finding fields

The framework asks for each finding to carry the following fields. This table
shows where Bridge keeps each one.

| Framework field | Bridge |
|---|---|
| Issue type | `category` (sandhi, word-joining, typo, punctuation, spacing, unicode, termbase, name) and `layer` (integrity, pattern, lexicon, housestyle) |
| Severity | `severity`: high, medium or low. The framework's **Critical** (missing verse, reversed meaning, wrong negation, wrong referent, corrupted Unicode, major USFM corruption) is not a Language QA severity. Most of those items are owned by the semantic pipeline, the USFM checker or a person. |
| Confidence | `confidence`: high, medium or low. The values are uncalibrated. |
| Action | A `suggestions` list: a suggestion is offered, never applied until "Use" is clicked. |
| Reviewer decision needed | Every finding needs a decision: Use, Edit, Ignore or False positive. |
| Scope | Verse. Book and collection scope arrive with the collection runner (P4). |
| Status | The decision history (`languageQa.history`). An ignore expires when its rule changes. |

## Publication sequence

The order the framework recommends for the IRV project:

1. Translation team revision (Round 1)
2. Strict Tamil linguistic proofreading (Round 2)
3. Source-fidelity check
4. Glossary, names and parallel passages
5. Consultant and exegetical check
6. Community and comprehension testing
7. Whole-book consistency
8. Whole-Bible terms, names and wordlist
9. USFM and Unicode technical QA
10. Typesetting
11. Tamil visual proof on the PDF
12. Final blind read-through
13. Regression checks
14. Consultant final approval
15. Release master

Proofreading uses the project's supplied Tamil and reference texts and its
approved resources as the textual basis. The outside sources below informed the
method only, not the text.

## Sources

- Paratext Manual, *24. Finalising for Publication*: manual.paratext.org/24.FFP/
- Paratext Manual, *12. Basic Checks 2* and *13. Formatting checks*: manual.paratext.org/12.BC2/, manual.paratext.org/13.FC/
- Paratext, *Translation checking tools* and the SIL, BI, PBT and TSC base plans: paratext.org
- USFM 3.0 documentation (identification, characters, cross references, syntax notes): ubsicap.github.io/usfm/
- Unicode, *Normalization FAQ*: unicode.org/faq/normalization.html
- W3C, *Tamil Script Resources*, *Tamil Layout Requirements*, *Tamil Gap Analysis*, *Approaches to line breaking*: w3.org
- Tamil Virtual Academy, grammar courses on எழுத்து, புணர்ச்சி and வல்லினம் மிகும்/மிகா இடங்கள்: tamilvu.org
