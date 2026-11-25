# Meaning and theology checklist (applied to every verse against the chosen reference Bible)

The reference Bible is a comparison text, not necessarily the translation's source. Every meaning finding is a question for the team.

## Accuracy
- Sense reversed (negation lost or added), speaker or addressee changed, subject and object swapped.
- Clause missing, added, duplicated, or copied from a neighbouring verse; text in the wrong verse; verses swapped or bridged.
- **Search nearby before calling anything missing.** Run `nearby.py BOOK C:V` and read the verses around it for the *meaning*: translators move clauses across verse boundaries, merge verses, use a pronoun for a name or a paraphrase for an idiom. Report "missing" only when the meaning is not_found in the window; when it is in another verse, it is at most a verse-boundary question.
- Numbers, names, measures, money, dates and units against the reference (`numchk.py`); conversions in footnotes.
- Textual basis: wording that follows a manuscript reading the reference does not (e.g. longer endings, added verses) — flag for decision, not as error.

## Key terms and consistency
- One rendering per key term (covenant, righteousness, atonement, Spirit, Lord/LORD, Christ, saints…) unless context requires otherwise; the team's Biblical Terms list rules (`terms.py`).
- Divine names and titles (YHWH, Adonai, El Shaddai, LORD of hosts, Most High) kept distinct.
- Parallel passages (Gospels, Kings/Chronicles, OT quotations in the NT) — consistent where the reference is the same; not over-harmonized where it differs.

## Figures of speech
| Figure | What to check |
|---|---|
| Idiom | Rendered word for word where the target language needs the meaning (gird up the loins; heap coals of fire; stiff-necked). |
| Simile vs metaphor | A simile ("like a lion") kept as comparison; a metaphor not made literal; neither swapped without reason. |
| Rhetorical question | The expected answer is clear in the target language; not read as a real question or turned into a statement that loses force. |
| Euphemism | Kept polite but understandable (knew = had relations; slept with his fathers = died; covered his feet). |
| Metonymy / synecdoche | Sense kept (the cup = suffering; flesh = humanity; the house of David = dynasty). |
| Personification / anthropomorphism | Clear that it is figurative (the trees clap their hands; the arm of the LORD). |
| Hyperbole and litotes | Not weakened or turned literal ("not a few" = many). |
| Merism and hendiadys | Totality kept (heaven and earth = everything; grace and truth). |
| Divine passive | The actor stays clear where the reference implies God ("it was given"). |
| Chiasm, parallelism, acrostic | Poetic structure visible in layout (\q levels, stanza breaks); parallel lines not merged. |
| Kinship and honorific terms | Brother, son of, father not narrowed or widened; honorific forms for God and Christ used consistently. |
| Cultural items | Weights, coins, crops, animals not replaced by anachronisms (chilli for emmer, maize for grain). |

## Theological consistency
- Doctrine-bearing verses (e.g. Jn 1:14, Rom 3:24-26, Phil 2:6-8, Heb 1:3) checked word by word.
- Introductions and headings state no interpretation the text does not (commentary headings).
