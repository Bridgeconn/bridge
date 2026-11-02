"""Build/check the seven offline spelling packs from pinned LibreOffice data.

This is build-time network access only. Runtime never downloads dictionaries.
Existing hi/ml/or/pa/ta packs are deliberately outside this allow-list (#414).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1] / "engine" / "language_packs"
COMMIT = "4f1df64b2e8e14751aa7c2205d170ca016071315"
SOURCE = "https://github.com/LibreOffice/dictionaries"
# code: name, Unicode script, source locale, upstream notice, licence, accepted examples
LANGUAGES = {
    "as": ("Assamese", "Beng", "as_IN", "README_as_IN.txt", "GPL-3.0-only", ["মানুহ", "ঈশ্বৰ", "আৰু"]),
    "bn": ("Bengali", "Beng", "bn_BD", "COPYING", "GPL-2.0-only", ["মানুষ", "ঈশ্বর", "এবং"]),
    "gu": ("Gujarati", "Gujr", "gu_IN", "README_gu_IN.txt", "GPL", ["માણસ", "ઈશ્વર", "અને"]),
    "kn": ("Kannada", "Knda", "kn_IN", "README-kn_IN.txt", "GPL-2.0-or-later", ["ಮನುಷ್ಯ", "ದೇವರು", "ಮತ್ತು"]),
    "mr": ("Marathi", "Deva", "mr_IN", "COPYING", "GPL-2.0-only", ["माणूस", "देव", "आणि"]),
    "ne": ("Nepali", "Deva", "ne_NP", "README_ne_NP.txt", "LGPL-2.1-only", ["मानिस", "श्री", "श्रीमती"]),
    "te": ("Telugu", "Telu", "te_IN", "README_te_IN.txt", "GPL-2.0-or-later", ["మనిషి", "దేవుడు", "మరియు"]),
}
ALIASES = {"asm": "as", "ben": "bn", "guj": "gu", "kan": "kn", "mar": "mr", "nep": "ne", "npi": "ne", "tel": "te"}
LICENSE_FILES = ("GPL-2.0-only.txt", "GPL-3.0-only.txt", "LGPL-2.1-only.txt", "MPL-2.0.txt")
LICENSE_SOURCE = "https://raw.githubusercontent.com/spdx/license-list-data/v3.26.0/text"


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")


def sync(cache: Path | None = None) -> None:
    licenses = ROOT / "LICENSES"
    licenses.mkdir(exist_ok=True)
    license_files = {}
    for name in LICENSE_FILES:
        if cache:
            data = (cache / "LICENSES" / name).read_bytes()
        else:
            with urllib.request.urlopen(f"{LICENSE_SOURCE}/{name}", timeout=60) as response:
                data = response.read()
        (licenses / name).write_bytes(data)
        license_files[name] = hashlib.sha256(data).hexdigest()
    write_json(licenses / "MANIFEST.json", {"source": LICENSE_SOURCE, "files": license_files})
    for code, (name, script, locale, notice, license_id, words) in LANGUAGES.items():
        folder = ROOT / f"{code}-irv"
        dictionary = folder / "dictionary"
        dictionary.mkdir(parents=True, exist_ok=True)
        files = {}
        for filename in (f"{locale}.aff", f"{locale}.dic", notice):
            if cache:
                data = (cache / code / filename).read_bytes()
            else:
                url = f"https://raw.githubusercontent.com/LibreOffice/dictionaries/{COMMIT}/{locale}/{filename}"
                with urllib.request.urlopen(url, timeout=60) as response:
                    data = response.read()
            (dictionary / filename).write_bytes(data)
            files[filename] = hashlib.sha256(data).hexdigest()
        manifest = {
            "source": SOURCE, "commit": COMMIT, "directory": locale, "license": license_id,
            "files": files,
            "normalizations": ["bengali-affix-header-counts"] if code == "bn" else [],
        }
        write_json(dictionary / "MANIFEST.json", manifest)
        write_json(folder / "pack.json", {
            "pack": f"{code}-irv", "version": "1.0.0", "language": code, "script": script,
            "description": f"{name} offline dictionary spelling candidates from LibreOffice/Hunspell. "
                           "An absent word is not proof of an error. No clause grammar or meaning assessment.",
            "spellingDictionary": {"path": f"dictionary/{locale}", "manifest": "dictionary/MANIFEST.json"},
            "rules": ["rules/spelling.dictionary-miss.json"],
        })
        (folder / "rules").mkdir(exist_ok=True)
        # These examples establish dictionary behaviour, not linguistic precision.
        # The synthetic concatenation is an absent form, not a native review label.
        unknown = words[0] * 4
        write_json(folder / "rules" / "spelling.dictionary-miss.json", {
            "id": "spelling.dictionary-miss", "version": 1, "enabled": True,
            "category": "typo", "layer": "lexicon", "severity": "low", "confidence": "low", "inline": False,
            "message": {"en": f"Not recognised by the bundled {name} spelling dictionary; review this word."},
            "rationale": "Dictionary coverage is incomplete. Names, inflections, dialect and Bible-specific "
                         "vocabulary may be valid. No replacement is inferred. Use the project dictionary or Ignore "
                         "for accepted forms. This is not a grammar judgement.",
            "match": {"type": "dictionary-lookup", "script": script},
            "examples": {
                "correct": [{"text": w, "origin": "Accepted by the pinned dictionary; not a human precision label"} for w in words],
                "incorrect": [{"text": unknown, "span": unknown, "fix": None,
                               "origin": "Synthetic out-of-dictionary concatenation; tests lookup only"}],
            },
            "provenance": f"{SOURCE}/tree/{COMMIT}/{locale}; affix-aware Spylls 0.1.7 lookup. "
                          "No human-labelled precision measurement yet. See dictionary/MANIFEST.json.",
        })
        (folder / "NOTICE.md").write_text(
            f"# {name} spelling dictionary\n\n"
            f"Source: {SOURCE}/tree/{COMMIT}/{locale}\n\n"
            f"Licence as stated upstream: **{license_id}**. The upstream notice is preserved "
            f"verbatim in `dictionary/{notice}`. Dictionary and affix files are also byte-exact; "
            "`dictionary/MANIFEST.json` records their SHA-256 digests. These data keep their upstream "
            "licences; they are not relicensed under Bridge's code licence.\n\n"
            "The full GPL/LGPL texts ship in `../LICENSES/`. Gujarati's original notice says "
            "GPL without naming a version; that notice is retained without inventing a version.\n\n"
            "Runtime reads UTF-8 with BOM removal and canonical NFC lookup. Bengali's six malformed "
            "affix-table counts ending in `$` are normalized in memory only; no affix condition or "
            "dictionary entry is rewritten on disk.\n\n"
            "This pack checks dictionary membership with affixes. Dictionary misses are low-confidence "
            "review candidates, not certified spelling errors. It does not judge clause grammar, meaning, "
            "or publication readiness, and never rewrites Scripture automatically. Nepali's upstream data "
            "omits common vocabulary including र and परमेश्वर; a clean or noisy scan is not an accuracy measure. "
            "Native-language review and a labelled benchmark remain required.\n",
            encoding="utf-8", newline="\n")
        print(f"{code}: {len(files)} upstream files")
    index_path = ROOT / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    for code, (name, *_) in LANGUAGES.items():
        index["languages"][code] = {"pack": f"{code}-irv", "name": name}
    index["languages"] = dict(sorted(index["languages"].items()))
    index["aliases"].update(ALIASES)
    index["aliases"] = dict(sorted(index["aliases"].items()))
    write_json(index_path, index)


def check() -> int:
    problems = []
    for code in LANGUAGES:
        folder = ROOT / f"{code}-irv" / "dictionary"
        try:
            manifest = json.loads((folder / "MANIFEST.json").read_text(encoding="utf-8"))
            for file, digest in manifest["files"].items():
                if hashlib.sha256((folder / file).read_bytes()).hexdigest() != digest:
                    problems.append(f"{code}/{file}: hash differs")
        except (OSError, ValueError) as exc:
            problems.append(f"{code}: {exc}")
    folder = ROOT / "LICENSES"
    try:
        manifest = json.loads((folder / "MANIFEST.json").read_text(encoding="utf-8"))
        for file, digest in manifest["files"].items():
            if hashlib.sha256((folder / file).read_bytes()).hexdigest() != digest:
                problems.append(f"LICENSES/{file}: hash differs")
    except (OSError, ValueError) as exc:
        problems.append(f"LICENSES: {exc}")
    print("\n".join(problems) if problems else "Seven dictionary manifests and licence texts verified")
    return bool(problems)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--cache", type=Path, help="Previously fetched exact files; avoids network")
    args = parser.parse_args()
    if args.check:
        raise SystemExit(check())
    sync(args.cache)
