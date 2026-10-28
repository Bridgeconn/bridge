"""A genuinely fresh project for the cold-start alignment tests (#214).

`tests/fixtures/51PHPIRVTam.SFM` is the Tamil IRV Philippians with no alignment
markup at all, so importing it against the bundled UGNT gives exactly what a
translator's first open of a new book gives: every source token in a blank group,
every target word in the word bank, nothing completed, nothing for the corpus
scorer to learn from.

The IRV itself redistributes Philippians 1:3-6 across verse boundaries -- Tamil
1:6 carries the Greek 1:3 clause "I thank my God", Tamil 1:3 carries Greek 1:5
"your fellowship in the gospel from the first day until now" -- so the untouched
text is already a real cross-verse case (`natural`). Two synthetic variants add a
known answer on top:

- `swap34`: the Tamil text of verses 3 and 4 trade places, so every Greek word of
  verse 3 is now realized in Tamil verse 4 and vice versa. Measures recall.
- `spill34`: only the last words of Tamil verse 3 move to the front of verse 4,
  which is what real paraphrase usually looks like. Checks that the moved words
  go cross-verse while the rest stays same-verse.

Shared here rather than in a test module so the protocol tests, the module tests
and the key-gated live test build the same project (CLAUDE.md: never import from
another test module).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tc_ai_bridge.usfm_verse import tokens
from tests.support.paths import FIXTURES_DIR

PHP_IRV_TAMIL = FIXTURES_DIR / "51PHPIRVTam.SFM"

VARIANTS = ("natural", "swap34", "spill34")

#: How many trailing words of Tamil 1:3 the `spill34` variant moves into 1:4.
SPILL_WORDS = 3

TAMIL_METADATA: dict[str, str] = {
    "languageId": "tam",
    "languageName": "Tamil",
    "languageDirection": "ltr",
    "projectName": "Philippians cold start",
    "bibleName": "IRV Tamil",
}

_VERSE_LINE = re.compile(r"^\\v (\d+[a-z]?(?:-\d+)?)[ \t]+(.*)$")


def chapter_one_verse_lines(text: str) -> dict[str, tuple[int, str]]:
    """`{verse: (line index, verse text)}` for chapter 1 of an SFM book whose
    verses each sit on their own `\\v` line (true of the IRV files)."""
    lines = text.split("\n")
    found: dict[str, tuple[int, str]] = {}
    in_chapter_one = False
    for index, line in enumerate(lines):
        if line.startswith("\\c "):
            in_chapter_one = line.split()[1] == "1"
            continue
        if not in_chapter_one:
            continue
        match = _VERSE_LINE.match(line)
        if match:
            found[match.group(1)] = (index, match.group(2))
    return found


def variant_text(source_text: str, variant: str) -> str:
    """Apply one variant to the SFM text. `natural` returns it unchanged."""
    if variant not in VARIANTS:
        raise ValueError(f"Unknown cold-start variant {variant!r}; expected one of {VARIANTS}.")
    if variant == "natural":
        return source_text
    lines = source_text.split("\n")
    verses = chapter_one_verse_lines(source_text)
    index3, text3 = verses["3"]
    index4, text4 = verses["4"]
    if variant == "swap34":
        lines[index3] = f"\\v 3 {text4}"
        lines[index4] = f"\\v 4 {text3}"
    else:  # spill34
        words3 = text3.split()
        moved, kept = words3[-SPILL_WORDS:], words3[:-SPILL_WORDS]
        lines[index3] = f"\\v 3 {' '.join(kept)}"
        lines[index4] = f"\\v 4 {' '.join(moved + text4.split())}"
    return "\n".join(lines)


def moved_words(variant: str) -> dict[str, list[str]]:
    """The Tamil words each variant moved, keyed by the verse they now sit in.

    This is the answer key for the live measurement: a correct model links a
    moved word to a source token of the verse it came *from*.
    """
    text = PHP_IRV_TAMIL.read_text(encoding="utf-8-sig")
    verses = chapter_one_verse_lines(text)
    _, text3 = verses["3"]
    _, text4 = verses["4"]
    # The project's own tokeniser, so the answer key matches the word bank
    # (punctuation trimmed, exactly as every tC `occurrence` is counted).
    if variant == "swap34":
        return {"3": tokens(text4), "4": tokens(text3)}
    if variant == "spill34":
        return {"4": tokens(" ".join(text3.split()[-SPILL_WORDS:]))}
    return {}


def write_variant(destination_dir: Path, variant: str) -> Path:
    """Write the variant SFM into `destination_dir` and return its path. The file
    keeps the fixture's name so the import preview identifies the book the same
    way it would for the real file."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    text = PHP_IRV_TAMIL.read_text(encoding="utf-8-sig")
    target = destination_dir / PHP_IRV_TAMIL.name
    target.write_text(variant_text(text, variant), encoding="utf-8")
    return target


def import_cold_project(call: Any, engine: Any, sfm_path: Path, destination_root: Path) -> dict[str, Any]:
    """Import the SFM through the protocol and return the import result (its
    `path` is the project root). `call(engine, method, params)` is the protocol
    helper the caller already uses, injected so this module imports no test
    module and no dispatcher."""
    response = call(engine, "project.import", {
        "path": str(sfm_path),
        "metadata": dict(TAMIL_METADATA),
        "destinationRoot": str(destination_root),
    })
    assert response["success"] is True, response
    return response["result"]


def alignment_chapter_bytes(project_root: Path, chapter: str = "1") -> bytes:
    """The raw tC alignment file for one chapter, for byte-for-byte "wrote
    nothing" assertions."""
    return (project_root / ".apps" / "translationCore" / "alignmentData" / "php" / f"{chapter}.json").read_bytes()


def target_chapter_bytes(project_root: Path, chapter: str = "1") -> bytes:
    return (project_root / "php" / f"{chapter}.json").read_bytes()


def source_words(project_root: Path, chapter: str, verse: str) -> list[str]:
    """Source token words of one verse as the project stores them."""
    data = json.loads(alignment_chapter_bytes(project_root, chapter).decode("utf-8"))
    return [
        top["word"]
        for group in data[verse]["alignments"]
        for top in group.get("topWords", [])
    ]
