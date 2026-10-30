# Nepali spelling dictionary

Source: https://github.com/LibreOffice/dictionaries/tree/4f1df64b2e8e14751aa7c2205d170ca016071315/ne_NP

Licence as stated upstream: **LGPL-2.1-only**. The upstream notice is preserved verbatim in `dictionary/README_ne_NP.txt`. Dictionary and affix files are also byte-exact; `dictionary/MANIFEST.json` records their SHA-256 digests. These data keep their upstream licences; they are not relicensed under Bridge's code licence.

The full GPL/LGPL texts ship in `../LICENSES/`. Gujarati's original notice says GPL without naming a version; that notice is retained without inventing a version.

Runtime reads UTF-8 with BOM removal and canonical NFC lookup. Bengali's six malformed affix-table counts ending in `$` are normalized in memory only; no affix condition or dictionary entry is rewritten on disk.

This pack checks dictionary membership with affixes. Dictionary misses are low-confidence review candidates, not certified spelling errors. It does not judge clause grammar, meaning, or publication readiness, and never rewrites Scripture automatically. Nepali's upstream data omits common vocabulary including र and परमेश्वर; a clean or noisy scan is not an accuracy measure. Native-language review and a labelled benchmark remain required.
