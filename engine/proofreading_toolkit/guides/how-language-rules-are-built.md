# Where the publish-worthy rules for each language come from

No single file holds "the rules" for every language. The toolkit builds them in layers, from the most certain to the least, and records which layer every finding came from.

| Layer | Source | Who decides | Certain enough to report as an error? |
|---|---|---|---|
| 1. Universal text rules | Unicode (scripts, combining marks, normalisation) and the USFM standard | Fixed in `sweep.py` | Yes |
| 2. The project's own Paratext data | `SpellingStatus.xml` (words the team marked wrong), `ProjectBiblicalTerms.xml` / `TermRenderings.xml` (approved key-term renderings), `BookNames.xml`, `Settings.xml` (language, versification) | The translation team | Yes — the team already decided |
| 3. The translation's own usage | `make_profile.py` counts every word in all 66 books. A rare spelling one letter away from a common one is a *candidate*; the quotation marks, punctuation and digits actually used become the expected style | Statistics, then the checker approves (`candidates.tsv` → `approve_candidates.py`) | Only after approval |
| 4. The language's grammar, spelling and style rules | Claude drafts them into `profiles/<code>/profile.json` (`rules`, `lead_patterns`, optional `minority.py`) from its knowledge of the language, plus any style guide, orthography standard or past checking report the team uploads | A native linguist approves; the profile's `status` line records who and when | Yes once approved; before that, rows are marked Confidence: Medium and Decision: Review |
| 5. Meaning and theology | Verse-by-verse comparison with the reference Bible the checker chose, using `guides/checklist-meaning-and-theology.md` (figures of speech, key terms, names, numbers, parallel passages) | Claude proposes; the exegetical checker decides | Proposals only — every meaning row asks for review |

## Practical steps for a new language
1. Put the Paratext project folder (or any folder of USFM files) and the reference Bible folder in the session.
2. `detect_language.py` names the language and script (from `Settings.xml`, else from the letters themselves).
3. If no `profiles/<code>/` exists: `make_profile.py` drafts it from the text; Claude writes the rules section for that language; the checker or a linguist reviews it before the first publishing run. Until then the generic profile still runs every universal, Paratext and reference check.
4. After each run, new house-style decisions (rejected leads) and new typo families go back into the profile, so the next book and the next project start stronger. The Telugu profile in `profiles/te/` was built exactly this way during the 66-book Telugu IRV check.

## Limits
- Claude's knowledge of a language is strong for major languages and weaker for low-resource ones; for those, layers 2–3 and the linguist's review carry more weight.
- Nothing about print layout (line breaks, hyphenation, fonts) can be checked from text files.
- Connotation, register and naturalness need a native reader; the toolkit raises candidates only.
