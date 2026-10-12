# Language QA rule packs

Language QA rules that are specific to a language or a translation are data, not
Python. They live in a **rule pack**: a directory of JSON files under
`engine/tc_ai_bridge/language_packs/<pack>/`. The engine loads a pack once per
process, on first use, and tests it before using it. The loader is
`engine/tc_ai_bridge/language_packs/loader.py`, and it is the authority when this
page and the code disagree.

The only pack today is **`ta-irv`**, the Tamil IRV pack. Its rules come from the
layered-rules brief's Phase 3: the B1/B2 வல்லினம் rules, migrated and split, plus
IRV defect shapes taken from the review reports. Language-neutral checks, such as
Unicode, spacing and repeated punctuation, stay in `language_qa.py` as `common/*`
rules.

Related:

- `docs/LANGUAGE_QA_BENCHMARK.md` explains how each rule's precision is measured.
- `docs/DECISIONS.md` records why rules are data, why overrides only narrow, and
  why inline is decided by human-labelled precision (2026-09-28).
- `docs/LANGUAGE_QA_TAMIL_SPECIFICATION.md` maps the 56 proofreading items to
  pack ids.

## Layout

```
language_packs/ta-irv/
  pack.json                       pack metadata + ordered list of rule files
  rules/<rule id>.json            one rule per file
  lexicon.json                    the corpus lexicon (Phase 5; scripts/build_tamil_lexicon.py).
                                  Not a rule file: language_packs/lexicon.py reads it for the
                                  lexicon.* rules, lazily. A pack without one falls back to the
                                  within-book wordlist audit.
```

`pack.json` holds `pack`, `version` (semver), `language`, `script`, `description`
and `rules`. `rules` is an ordered list of paths relative to the pack directory.
The pack version appears in every finding as
`ruleVersion = "<pack>@<version>#<rule version>"`, for example
`ta-irv@1.0.0#1`. An ignore recorded under a different `ruleVersion` expires: the
finding comes back flagged `previouslyIgnored` (see DECISIONS.md). So bumping the
pack version sends every ignore of every pack rule back for re-check. Bump a
single rule's `version` when only that rule changed.

The pack is **bundled data**. `engine/bridge-engine.spec` lists the directory
explicitly, because PyInstaller's import analysis cannot see JSON read from
beside a module.

## A rule

| Key | Required | Meaning |
|---|---|---|
| `id` | yes | Lowercase and dotted: `<category>.<family>.<shape>`. The finding's `ruleId` is `<pack>/<id>`. |
| `version` | yes | Positive integer. Bump it when the rule's behaviour changes. |
| `legacyId` | no | The pre-pack rule name, for example `tamil.vallinam-missing`. The finding's `rule` field and its **finding id** are derived from `legacyId` when it is present, so decisions made before the migration keep matching. |
| `enabled` | no (true) | `false` ships the rule switched off. Its examples are not run. |
| `category` | yes | Drives the default layer and the benchmark bucket. Values: `sandhi`, `word-joining`, `typo` (layer `pattern`); `punctuation`, `spacing`, `unicode` (layer `integrity`); `termbase`, `name` (layer `housestyle`). |
| `layer` | no | Overrides the category's default layer. |
| `severity`, `confidence` | yes | `high`, `medium` or `low`. |
| `inline` | no (false) | Draw the finding as a mark in the verse editor, with the right-click menu. |
| `title` | no | `{ta, en}`, used for display. |
| `message` | yes | `{en: "..."}`. A `str.format` template (see "Placeholders"). |
| `rationale` | no | A template, shown in the finding's "why". |
| `match` | yes | A `token-context` or `regex` match (below). |
| `abstain` | no | Conditions under which the rule stays silent (below). |
| `fix` | no | How the suggested replacement is built (below). No `fix` means no suggestion. |
| `examples` | no | `{incorrect: [...], correct: [...]}`. These run as tests every time the pack loads. |
| `provenance` | no | Free text: where the rule and its numbers came from. |

An unknown key is an error. That is deliberate: a misspelled `abstian` must not
be ignored silently.

### `token-context` match

A token-context match looks at **one pair of adjacent words separated only by
whitespace**. Punctuation, digits and markup between the words make the rule
abstain. `gap` must be `"whitespace"`.

The previous word is split into a base and an optional linking consonant:
`அந்தக்` is base `அந்த` plus link `க`. The split happens only when the word
ends in a hard consonant (க ச த ப) followed by pulli and has more than two code
points.

```json
"match": {
  "type": "token-context",
  "prev": { "lexical": ["அந்த", "இந்த", "எந்த"] },
  "gap": "whitespace",
  "next": { "initial": ["க", "ச", "த", "ப"] },
  "link": "none"
}
```

- `prev` conditions test the **base** of the previous word.
- `next` conditions test the following word.
- `link` sets which shape of the pair the rule is about:
  - `none`: the pair is bare, so the linking consonant is missing (`அந்த காகம்`).
  - `mismatch`: the pair is linked with the wrong consonant (`அந்தச் காகம்`).
  - `any`: the pair is bare or correctly linked. Used by the clitic-fusion rule.

The finding span runs from the start of the previous word to the end of the
next word, in raw code points.

### `regex` match

```json
"match": { "type": "regex", "on": "visible", "pattern": "…(?<span>…)…" }
```

- `on: "visible"` (the default) matches the lifted verse text that the reader
  sees.
- `on: "raw"` matches the raw text, markup included. Only rules whose layer is
  `integrity` may use it. `integrity.space-before-note-end` uses it to see
  `\f … \f*`.
- The finding span is the named group `span` if there is one, otherwise the whole
  match. An empty match is skipped.
- Patterns are compiled with the `regex` module after NFC normalisation, so
  `\p{L}`, `\p{M}` and similar classes work. Use `[\p{L}\p{M}]+` for a Tamil
  word: vowel signs and pulli are marks (`\p{M}`), not letters.

### Conditions

A condition is an object. Every key in it must hold for the condition to match.

| Key | Test |
|---|---|
| `lexical` | The token is one of these (compared after NFC). |
| `notLexical` | The token is none of these. |
| `suffix` | A regex searched at the token's end; `$` is added if missing. |
| `regex` | A regex searched anywhere in the token. |
| `minLength` | The token has at least this many code points. |
| `initial` | The token's first code point is in the set. |
| `prefix` | The token starts with one of these stems. |
| `notPrefix` | The token starts with none of these (with `prefix`: தேவ- but not தேவை "need"). |
| `notSuffix` | The token ends with none of these literal endings. |
| `notSuffixLexical` | The token is none of these words and does not end with one: a compound-final noun (`முறை` also excludes `ஒருமுறை`). |
| `listRef` | The token is in a named list supplied at scan time (`housestyle.properNouns`). A missing list is empty. The bundled pack no longer uses it (a name does not block doubling, 2026-09-28 review); a project override may. |

`notSuffix` and `notSuffixLexical` are both "ends with" tests. They are kept
apart because they document different things: an ending, or a whole noun that
ends a compound. Neither may be an ending that a real case form also has: `-மை`
also ends உம்மை and எருசலேமை, and `-தரை` also ends கர்த்தரை, all accusatives. So
`ta-irv` uses exact words for those roots (DECISIONS.md, 2026-09-28).

This is a closed set on purpose: it is not a grammar engine (DECISIONS.md).

### Abstains

```json
"abstain": [
  { "next": { "prefix": ["தேவ"], "notPrefix": ["தேவை"] },
    "origin": "House style (reviewer 2026-09-28): no doubling before தேவன்/தேவ- forms …" }
]
```

An abstain has a `prev` condition, a `next` condition, or both, plus an `origin`.
If a pair matches the rule and any one of its abstains, there is no finding. For
`regex` rules only `next` is meaningful. Every abstain in `ta-irv` states the
evidence behind it in its `origin`.

A pair that straddles a poetry line (`\q`) or lifted inline markup is not one
piece of raw text, so the finding cannot cover it. It is raised on the **first
word** instead, with the fix confined to that word (`யெகோவாவுக்கு` →
`யெகோவாவுக்குச்`). Only when the first word is itself split by markup is it dropped
and counted as a limitation.

### Contexts

```json
"contexts": [
  { "next": { "lexical": ["தான்"] }, "confidence": "medium",
    "message": { "en": "தான்: பிரதிப்பெயர் என்றால் பிரித்து ஒற்றுடன்; … \"{fix}\" … \"{alternative}\" …" },
    "rationale": "pronoun: separate, doubled",
    "alternatives": [ { "fix": "fuse-link", "rationale": "clitic: fused" } ] }
]
```

A token-context rule may say that, before a given next word, its finding reads
differently:
- **Confidence and wording.** It carries the context's own confidence, message and
  rationale.
- **Ranked alternatives.** Further alternatives follow the rule's own fix. Each
  alternative is a fix type, and `{alternative}` names the first one in the message.
- **Alternatives need the whole pair.** A finding confined to its first word, a pair
  across a poetry line, carries no alternatives.

`ta-irv` uses this for தான் after a case form (DECISIONS.md, 2026-09-29).

### Fixes

| `fix.type` | Match type | Replacement |
|---|---|---|
| `insert-link` | token-context | Previous word + next word's initial + pulli + the original gap + next word (`அந்த காகம்` → `அந்தக் காகம்`). |
| `replace-link` | token-context | Wrong link swapped for the right one (`அந்தச் காகம்` → `அந்தக் காகம்`). |
| `fuse-link` | token-context | Base + link + next word, with the space removed (clitic fusion). |
| `replace` | regex | `fix.text`, literally. |
| `expand` | regex | `match.expand(fix.template)`, so `\g<name>` back-references work. |

The replacement preserves the raw spelling of everything it does not change. It
is offered as a suggestion. Nothing is applied without the translator choosing
"Use".

### Placeholders

`message` and `rationale` are formatted with:

- token-context: `{prev}` (base), `{word}` (whole previous word), `{next}`,
  `{initial}`, `{link}`, `{fix}`;
- regex: `{span}`, `{fix}`.

### Examples are tests

```json
"examples": {
  "incorrect": [ { "text": "…", "span": "அந்த பெண்", "fix": "அந்தப் பெண்", "origin": "EXO 2:2" } ],
  "correct":   [ { "text": "…", "origin": "GEN 4:14 (house form)" } ]
}
```

At load, each example runs through the real `scan_text`:

- An `incorrect` example must produce a finding of **this rule** exactly on
  `span`. If `fix` is given, the finding's suggestion must equal it.
- A `correct` example must produce no finding of this rule.
- An example may carry `lists` (for example
  `{"housestyle.properNouns": ["…"]}`) to exercise a `listRef`.

If any example fails, the pack is refused with a `PackError` naming the rule, the
example and its origin. The pack's tests (`engine/tests/service/test_language_pack.py`)
load it, and so does every Tamil scan. A pack with a failing example therefore
cannot reach a translator.

In `ta-irv`, examples are real IRV verses. Where there are enough of them, they
are chosen from places the review reports also flagged. Where a shape has fewer
than twelve real occurrences, the builder derives an example from a real verse
and says so in `origin` ("derived from …").

## Project overrides

A project may narrow a bundled pack with
`<project>/.apps/translationCoreAI/language-packs/<pack>/overrides.json`:

```json
{ "rules": {
    "sandhi.vallinam.manner-adverb": { "inline": false },
    "sandhi.clitic.fused": { "enabled": false },
    "sandhi.vallinam.accusative": { "abstain": [ { "next": { "lexical": ["…"] }, "origin": "team decision" } ] }
} }
```

- Accepted: `enabled: false`, `inline: false`, and extra `abstain` entries.
- Refused and reported: anything that widens a rule. That means enabling a
  disabled rule, drawing a rule inline, or changing a pattern, severity,
  message or fix. Unknown rule ids and malformed abstains are refused the same
  way.
- A refusal does not discard the whole file. The acceptable parts still apply,
  and each refusal appears as a `Rule pack: …` entry in the status
  `limitations` (the panel's coverage notes).
- A no-op is not a refusal. For example, `inline: true` on a rule that is
  already inline changes nothing.

The overrides change the pack's fingerprint, which is part of the scan's
per-chapter cache key, so saving an override causes the affected chapters to be
rescanned.

## Inline and the gate

A rule is drawn inline only on human labels (DECISIONS.md 2026-09-28 and
2026-09-29): either (a) at least **0.90** on at least **20** labelled findings,
combined over the review rounds, or (b) every finding it makes in the whole
collection is labelled and none is wrong (`benchmark/human/population.json`).
For (a), the labelled findings are ones a Tamil reviewer labelled
(`scripts/language_qa_benchmark.py --human-labels … --gate`, run in CI; see
`docs/LANGUAGE_QA_BENCHMARK.md`). AI-agreement precision is a lower bound and is
diagnostic only. There is no sign-off waiver: the 2026-09-24 sign-off that drew
every வல்லினம் rule inline on AI-agreement numbers was superseded on 2026-09-28
(DECISIONS.md), and a rule file carrying `inlineSignOff` no longer loads. The
builder's `INLINE` table records the human number behind each inline rule.

## `ta-irv@1.3.0`

What changed in each version, and which ignores a bump expires, is in
`engine/language_packs/ta-irv/CHANGELOG.md`. Every change to the pack's rules,
inline flags or layers bumps `version` with an entry there; a wording-only
change (title, message, rationale, grammar rule name) gets an entry and no
new version (DECISIONS.md 2026-10-12, both entries). The human column is combined precision over the 2026-09-28 and
2026-09-29 rounds (`benchmark/human/baseline.json`); "population" is rule (b)'s
whole-Bible coverage from `benchmark/human/population.json`.

| Rule | v | Inline | Shape | Human precision |
|---|---|---|---|---|
| `sandhi.vallinam.dative` | 3 | **yes** (a) | -க்கு / -ற்கு dative + bare; root nouns, house names, directions abstain | 100% (87/87) |
| `sandhi.vallinam.accusative` | 3 | **yes** (a) | -ஐ accusative + bare; root nouns and compound-final nouns abstain | 97.4% (74/76) |
| `sandhi.vallinam.demonstrative` | 3 | **yes** (a) | அந்த/இந்த/எந்த + bare hard consonant | 100% (24/24) |
| `sandhi.vallinam.manner-adverb` | 3 | **yes** (a) | அப்படி/இப்படி/எப்படி + bare | 100% (21/21) |
| `sandhi.vallinam.wrong-consonant` | 3 | **yes** (b) | linked with the wrong hard consonant | 100% (1/1; population 1 of 1) |
| `sandhi.compound.direction` | 2 | **yes** (a) | கிழக்கு/மேற்கு/வடக்கு/தெற்கு + bare (compound doubling) | 100% (25/25) |
| `sandhi.clitic.fused` | 3 | disabled | -ஐ, -க்கு or -ற்கு + தான் written apart; the வல்லினம் rules' தான் context replaces it | — |
| `typo.divine-name.vowel-drop` | 1 | no | யெகோவவ for யெகோவாவ | 100% (5/5; population 5 of 11) |
| `typo.divine-name.dative-stem` | 1 | no | யெகோவாக்க (the dative is யெகோவாவுக்கு) | 100% (4/4; population 4 of 13) |
| `typo.suffix.dropped-tha` | 1 | **yes** (b) | -வற்கு for -வதற்கு | 100% (2/2; population 2 of 2) |
| `typo.participle.sentence-final` | 1 | no | a -ந்து participle before `.` `!` `?`; fix -ந்தது | not labelled |
| `integrity.space-before-note-end` | 2 | no | space before `\f*` / `\x*` (raw); category `usfm`, severity low | 0% as a text error (0/15): markup hygiene |
| `integrity.digits-in-text` | 1 | disabled | digits in verse text: an IRV house form (Pass 3 §5) | — |

The rules that moved out of the engine's code keep `legacyVersion:
"language-qa-7"`, so their findings' stamp, and their ignores, do not change
with the pack version:

| Rule | Inline | Shape | Human precision |
|---|---|---|---|
| `lexicon.known-misspelling` | **yes** (a) | the lexicon's misspelling map; human pairs high, AI-review pairs medium and panel-only | 100% (47/47) |
| `lexicon.known-split` | **yes** (b) | the lexicon's curated split pairs (சு வரை → சுவரை) | 100% (10/10; population 11 of 11) |
| `tamil.dependent-sign` | no | a vowel sign or pulli with no base | not labelled |
| `tamil.mixed-word` | no | Tamil and Latin letters in one word | not labelled |
| `tamil.wordlist-variant` | no | a rare spelling variant within the book | not labelled |
| `tamil.repeated-word` | disabled | a repeated word: Tamil அடுக்குத்தொடர் | 0/20 (2026-09-28) |
| `lexicon.rare-near-common` | disabled | a rare word close to a common one | 0/21 (2026-09-28) |

The indic-qa layer (`pack.json` `indicQa`, `indic_qa_rules.json`) adds 18
`indicqa.*` rules, all panel-only and none high/high (revision 1; `sandhi.missing`,
`sandhi.extra` and `sandhi.conflict` revision 2 since 1.3.0);
`indicqa.lex.irv-consistent-slip` is disabled. They carry the pack's stamp,
so a pack bump expires their ignores too. See `docs/LANGUAGE_QA_PACKS.md`.

Every வல்லினம் rule abstains before a spaced clitic or quotative (கூட,
மட்டும், போல, என்று, என, எனும்) and before தேவ- (not தேவை). Before தான் it
flags instead, with the pronoun and clitic fixes ranked (`contexts`). None
abstains on a proper noun.

B1 and B2 share `legacyId: "tamil.vallinam-missing"`. Their finding ids, and so
their existing decisions, carry over across versions; their `ruleVersion` does
not, so an existing ignore comes back once for re-check after each bump. That is
intended (DECISIONS.md, "An ignore expires…").

## Rebuilding `ta-irv`

The pack is generated from the corpus, and the generated JSON is committed:

```powershell
engine\.venv\Scripts\python.exe scripts\build_ta_irv_pack.py `
  --irv-dir "D:\Claude Lab\IRV Tamil" `
  --reviews "D:\Claude Lab\Revant work\Claude outputs" "…\Philippians_Round2_QA_Issues.csv"
```

`--human-labels` defaults to `benchmark/human/2026-09-28/human_labels.jsonl`.
The builder computes:

- the root nouns, from the corpus: a ை-word whose +யை form is attested; a
  க்கு- or ற்கு-word whose -க்கில் / -ற்கில் or -க்குக்கு form is attested. A
  corpus that mostly writes a case form bare is no longer a reason to exclude
  it: that is the defect the rules exist to find;
- the reviewer's word verdicts, from the labels: root nouns and house forms
  (sheet 3 `ROOT_KEEP`/`HOUSE`, and `FP_ROOT` findings) are added to
  `notLexical`; confirmed case forms (`CASE_FORM_FLAG`) are removed from it,
  whatever the corpus says;
- the examples: corpus ones, plus every reviewer-confirmed finding as an
  incorrect example and every reviewer false alarm its rule no longer raises
  as a correct one. So each pack load re-checks the review. A confirmed finding
  no rule finds fails the build; a still-raised false alarm is printed as a
  residual (the accusative's two before a name);
- `inline`, from the builder's `INLINE` table of human-measured rules.

After a rebuild, run `pytest tests/service/test_language_pack.py` and the
benchmark with `--gate` in both modes (AI agreement and `--human-labels`), and record the before and after numbers in
`docs/BUILD_LOG.md`. Editing a rule JSON by hand is allowed for a one-off fix, but
the next rebuild overwrites it. Put lasting changes in the builder.
