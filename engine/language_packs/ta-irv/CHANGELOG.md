# ta-irv changelog

The Tamil IRV rule pack. Rule schema and inline gate: `docs/LANGUAGE_QA_RULE_PACK.md`.

**A new pack version expires ignores.** Every finding of a pack rule carries
`ruleVersion = "ta-irv@<version>#<rule version>"`. An ignore or rejection
recorded under a different one is not re-applied: the finding comes back
flagged `previouslyIgnored` for re-checking (DECISIONS 2026-09-24). So a
version bump sends back every ignore of the pack-native rules and the
`indicqa.*` layer. The seven rules that moved out of the engine's code carry
`legacyVersion: "language-qa-7"` and keep that stamp, so their ignores stay.
Bump a single rule's `version` when only that rule changed.

Every change to the pack's rules, inline flags or layers ships as a new
version with an entry here, in the same commit (DECISIONS 2026-10-12).
A wording-only change (a title, a message, a rationale, a grammar rule's
name) changes no finding and no stamp, so it gets an entry here and no new
version (DECISIONS 2026-10-12, the later entry).

## 1.3.0 — 2026-10-12 (from the #235 review)

**No grammar verdict after கூட, சொந்த, கள்ள** (indic-qa 2a36f19, synced). The
reviewer read `no_clitic` and `particle_dbl` as contradicting on கூட / போல; they do
not (`no_clitic` is about the word before them, `particle_dbl` the word after).
Measured in the IRV: after கூட the next word is doubled or fused 52 times and
bare 31 times ("with" and "even" are both கூட), so it moves to a new `amb_kooda`
row; after போல it is doubled 28 of 29, so போல stays a "double". Without கூட,
`particle_dbl` agreed with the OV 119/14 (89.5%), under indic-qa's 90% guard, so
its two weakest words, சொந்த (OV 15/3) and கள்ள (5/1), move to
`amb_sontha_kalla`; `particle_dbl` is now போல, மற்ற, கிட்ட (99/10). `no_clitic` is
unchanged.

Effect on the IRV chapters with these words: "missing ஒற்று" findings after கூட
32 → 7 (the 7 are before a ப-word, where the OV writes கூடப் nearly always and its
habit still leads), after சொந்த 20 → 0, after கள்ள 0 → 0; nothing new is flagged.
`indicqa.sandhi.missing`, `.extra` and `.conflict` go to revision 2.

**Ignores.** A new pack version: every ignore of the 31 pack-stamped rules comes
back once as `previouslyIgnored`.

## 1.2.0 — 2026-10-12 (#234)

Records everything that shipped under 1.1.0 after 2026-09-28. Nothing in the
rules changes in this release; the version now names the rule set below.

**Wording, 2026-10-12 (#235, no version change).** A native reviewer's
corrections: six rule titles (`integrity.digits-in-text`,
`integrity.space-before-note-end`, `sandhi.clitic.fused`,
`sandhi.vallinam.manner-adverb`, `typo.divine-name.dative-stem`,
`typo.participle.sentence-final`); the தான் context message of the five
வல்லினம் rules now says இடைச்சொல் for the clitic, the term every other string
uses, instead of ஒட்டுச்சொல்; and 18 names in the indic-qa sandhi grammar
(`dictionary/sandhi_rules.tsv`, indic-qa 282d033: செயவெனெச்சம் as one word,
இறந்தகாலப் / நிகழ்காலப் பெயரெச்சம்). No match, abstain, fix or inline flag
changed. `irv_state.json.gz` was rebuilt for the new dictionary hash, from the
IRV folder as it now is (JHN was edited there on 2026-10-10).

**Inline promotions (2026-09-29, human labels over both review rounds).**
- `sandhi.vallinam.demonstrative` (24/24), `sandhi.vallinam.manner-adverb`
  (21/21) and `sandhi.compound.direction` (25/25): inline under rule (a),
  at least 0.90 on at least 20 labels.
- `sandhi.vallinam.wrong-consonant` (1/1) and `typo.suffix.dropped-tha` (2/2):
  inline under rule (b), every finding in the whole Bible labelled and none
  wrong (`benchmark/human/population.json`).

**தான் after a case form (2026-09-29, rule revision 3; direction revision 2).**
- The வல்லினம் rules no longer abstain before தான். A bare "X தான்" is
  flagged at medium confidence with two ranked fixes: "Xத் தான்" (the
  pronoun) first, "Xத்தான்" (the clitic) second, and the reviewer's Tamil
  message. This is the new rule field `contexts`.
- `sandhi.clitic.fused` (revision 3) is disabled: all six round-2 findings
  were the pronoun.

**Rules moved out of the engine's code (2026-09-30).** The Tamil code rules
became pack rules on generic kinds, with `legacyVersion` keeping their
findings' stamp: `lexicon.known-misspelling` (inline, 47/47),
`lexicon.known-split` (new 2026-09-29, curated pairs only, inline under
rule (b), 10/10), `tamil.dependent-sign`, `tamil.mixed-word`,
`tamil.wordlist-variant`, and the disabled `tamil.repeated-word` (0/20,
அடுக்குத்தொடர்) and `lexicon.rare-near-common` (0/21). The pack gained
`lexicon` and `confusion` (the Tamil confusion-set distance). The lexicon
went from ta-irv-lexicon@2 to @4: misspelling pairs split by provenance
(human pairs inline at high confidence, AI-review pairs medium and
panel-only), four rejected pairs removed and protected, and the split map.

**The indic-qa Tamil layer (2026-10-07).** `pack.json` `indicQa` runs the
vendored indic-qa Tamil profile once per book over the BSI 1957 OV
dictionary (`dictionary/`, synced by `scripts/sync_indic_qa.py`). Its 18
`indicqa.*` rules (`indic_qa_rules.json`) are panel-only, none high/high:
OV near misses and compounds, unknown words (low confidence), malformed or
impossible spellings, the 71-row sandhi grammar with OV/IRV counts
(missing, extra, wrong-class, dangling, conflicting ஒற்று), no space after
punctuation, and, in headings and footnotes only, the checks the pack runs
on verse text. A layer finding that overlaps a pack or common finding of the
same category is dropped.

**New rule (2026-10-09).** `typo.participle.sentence-final`: a -ந்து
participle that ends the sentence, fixed to its finite -ந்தது form. Low
severity, medium confidence, panel-only, no human labels yet. Revised the
same day to exclude nouns (மருந்து, பருந்து, விருந்து) and numeral endings.

**General corpus (2026-10-09, #246).** `generalCorpus` (IndicCorp v2 and the
Kaniyam word counts) accepts unknown words that the web attests, which cuts
`indicqa.lex.unknown`. The rule it adds, `indicqa.lex.irv-consistent-slip`,
ships disabled.

## 1.1.0 — 2026-09-28 (#169, step 3)

Rebuilt from `D:\Claude Lab\IRV Tamil` and the 2026-09-28 human review
(598 labelled findings on GEN, PSA and JHN).
- Every வல்லினம் rule abstains before தேவ- forms (not தேவை "need"). The
  proper-noun abstain is gone: names needed doubling in 17 of 25 cases.
- `notLexical` is the corpus root nouns plus the reviewer's roots, minus the
  reviewer's confirmed case forms. The bare-majority criterion is gone.
- `sandhi.vallinam.dative` also matches -ற்கு (17/17). The demonstrative and
  manner-adverb house-form stems are gone (9/9 were errors).
- New `sandhi.compound.direction` (கிழக்குக் காற்று), panel-only.
- `sandhi.clitic.fused` matches தான் only.
- `integrity.space-before-note-end` moves to the new `usfm` category,
  severity low (0/15 as a text error: markup hygiene).
- A pair across a `\q` line or lifted markup is flagged on its first word.
- Every reviewer-confirmed finding and false alarm is a pack example, so each
  load re-checks the review.
- Inline: `sandhi.vallinam.dative` (46/46) and `sandhi.vallinam.accusative`
  (35/37). The others are panel-only. The five வல்லினம் rules,
  `clitic.fused` and `space-before-note-end` went to revision 2.

## 1.0.0 — 2026-09-24 (layered-rules Phase 3)

The first pack: Tamil rules moved out of Python into JSON, generated by
`scripts/build_ta_irv_pack.py` from the IRV corpus and the review reports.
- The old B1–B4 checks became four வல்லினம் shape rules (demonstrative,
  manner adverb, accusative, dative) and `sandhi.vallinam.wrong-consonant`.
  They abstain on house forms, root nouns, clitics and names in -க்கு.
  `legacyId` kept the old finding ids, so existing decisions still matched.
- `sandhi.clitic.fused`, panel-only.
- Five IRV defect shapes: `typo.divine-name.vowel-drop`,
  `typo.divine-name.dative-stem`, `typo.suffix.dropped-tha`,
  `integrity.space-before-note-end`, and `integrity.digits-in-text`,
  disabled because digits are an IRV house form.
- Every வல்லினம் rule was drawn inline on the maintainer's sign-off. On
  2026-09-28 human labels replaced the sign-off; only the dative rule stayed
  inline (93.9%), still under 1.0.0.
