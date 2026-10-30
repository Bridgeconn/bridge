"""Shared offline Hunspell lookup for data-only packs (#414).

Existing indic-qa/Tamil checkers never enter this path. An unknown spelling is
only a review candidate: no grammatical assertion or replacement is inferred.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import io
import json
from pathlib import Path
import re
import unicodedata
from typing import Any

from .candidate import Candidate
from .tokens import WORD


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _inside(directory: Path, relative: str) -> Path:
    path = (directory / relative).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError("Spelling dictionary path leaves its pack")
    return path


def fingerprint(pack: Any) -> str:
    """Manifest and file signatures invalidate cached scans and resident data."""
    config = pack.meta.get("spellingDictionary")
    if not config:
        return ""
    if pack.directory is None:
        raise ValueError("Spelling dictionary has no pack directory")
    manifest = _inside(pack.directory, config["manifest"])
    base = _inside(pack.directory, config["path"])
    # Do not load the dictionary in a status request. Missing data is part of
    # the fingerprint, so a later pass retries and reports unavailable coverage.
    signatures = []
    for path in (base.with_suffix(".aff"), base.with_suffix(".dic")):
        try:
            stat = path.stat()
            signatures.append((stat.st_size, stat.st_mtime_ns))
        except OSError:
            signatures.append(None)
    data = manifest.read_bytes()
    return hashlib.sha256(data + repr(signatures).encode("ascii")).hexdigest()


class SpellingDictionary:
    def __init__(self, dictionary: Any) -> None:
        self.dictionary = dictionary
        # Bounded per-resident memo; a repeated word is looked up once.
        self.accepts = lru_cache(maxsize=20_000)(self._accepts)

    def _accepts(self, word: str) -> bool:
        return bool(self.dictionary.lookup(_nfc(word)))


@lru_cache(maxsize=1)
def _load(directory: Path, base_name: str, manifest_name: str, stamp: str) -> SpellingDictionary:
    from spylls.hunspell import Dictionary, readers
    from spylls.hunspell.readers.file_reader import BaseReader

    class Utf8Reader(BaseReader):
        def __init__(self, text: str) -> None:
            super().__init__(io.StringIO(text))

        def reset_encoding(self, encoding: str) -> None:
            if encoding.lower().replace("-", "") not in {"utf8", "utf8sig"}:
                raise ValueError(f"Spelling dictionary must be UTF-8, got {encoding}")

    manifest = json.loads(_inside(directory, manifest_name).read_text(encoding="utf-8"))
    base = _inside(directory, base_name)
    texts = []
    for suffix in (".aff", ".dic"):
        path = base.with_suffix(suffix)
        raw = path.read_bytes()
        expected = manifest["files"].get(path.name)
        if not expected or hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"Spelling dictionary integrity check failed: {path.name}")
        texts.append(_nfc(raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")))
    normalizations = manifest.get("normalizations", [])
    if set(normalizations) - {"bengali-affix-header-counts"}:
        raise ValueError("Unknown spelling dictionary normalization")
    if "bengali-affix-header-counts" in normalizations:
        # Upstream bn_BD has six table headers with an extraneous '$'.
        # Strip only that count suffix, never a suffix rule's regex condition.
        texts[0], count = re.subn(r"^(SFX\s+\S+\s+[YN]\s+\d+)\$$", r"\1", texts[0], flags=re.MULTILINE)
        if count != 6:
            raise ValueError("Bengali affix header normalization expected six pinned headers")
    aff, context = readers.read_aff(Utf8Reader(texts[0]))
    dic = readers.read_dic(Utf8Reader(texts[1]), aff=aff, context=context)
    return SpellingDictionary(Dictionary(aff, dic))


def dictionary(pack: Any) -> SpellingDictionary:
    config = pack.meta.get("spellingDictionary")
    if not isinstance(config, dict) or pack.directory is None:
        raise ValueError("dictionary-lookup requires pack.json spellingDictionary data")
    return _load(pack.directory.resolve(), config["path"], config["manifest"], fingerprint(pack))


def candidates(rule: Any, pack: Any, visible: str) -> list[Candidate]:
    backend = dictionary(pack)
    out = []
    # Use the shared word tokenizer. Preserve a joiner-linked word as one
    # spelling unit; testing each side would invent errors in legal conjuncts.
    spans: list[tuple[int, int]] = []
    for match in WORD.finditer(visible):
        if spans and visible[spans[-1][1]:match.start()] and set(visible[spans[-1][1]:match.start()]) <= {"\u200c", "\u200d"}:
            spans[-1] = (spans[-1][0], match.end())
        else:
            spans.append(match.span())
    for start, end in spans:
        word = visible[start:end]
        if not rule.params["script"].fullmatch(word):
            continue  # Foreign/mixed-script words are not this dictionary's evidence.
        if backend.accepts(_nfc(word)):
            continue
        values = {"span": word, "fix": ""}
        out.append(Candidate(rule, start, end, None, rule.message.format(**values),
                             rule.rationale.format(**values), source="lexicon"))
    return out
