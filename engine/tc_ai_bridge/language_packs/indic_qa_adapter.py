"""Profile packs: Language QA findings from indic-qa's checker (pa, ml, hi, or).

A *profile pack* is a pack whose `pack.json` says `"engine": "indic-qa"`. Its
rules are not compiled from JSON: they are indic-qa's own catalogue (the
profile module's `RULES`), each given a Bridge category, layer, severity,
confidence, revision and enabled flag by the pack's `rule_versions.json`.
It is an ordinary `RulePack`, so overrides, version stamps, ignore expiry,
inline lists and house style treat it like any other pack. None of its rules
runs in the per-verse scan: they are `stage="book"` with
`match_type="indic-qa"`, which no pair, verse or book kind dispatches. The
findings come from `profile_findings`, which the pass calls once per book,
next to the lexicon audit.

How a book is checked:
- Bridge's chapter JSON is turned into indic-qa `Line`/`Book` objects
  (`build_book`): one line per physical line of each verse's visible text
  (`lift_inline_usfm`), so adjacency never crosses a poetry line. indic-qa's
  own USFM parser is never called (CLAUDE.md gotcha 14).
- The checker needs whole-IRV word counts, which indic-qa gets by indexing 66
  books at start-up. The pack ships that state instead (`irv_state.json.gz`,
  built by scripts/build_indic_qa_irv_state.py through this same path). On
  load it is restored, and each pass re-indexes the open book from its live
  text, which replaces that book's share exactly (`Checker.index_book`
  subtracts a book's previous counts).
- Every item the checker reports is mapped to a Bridge finding: a token with
  a rule, a lead (`sandhi` list: consistency, agreement, grammar), or a
  warning. Spans are offsets in the visible line, translated back to raw code
  points; one that would cross lifted markup is dropped and counted.

Findings are recomputed on every pass and never written to
`language_qa_cache`: they depend on the whole book, not one verse. The
dictionaries are read only. Nothing here writes Scripture.

The same machinery runs indic-qa's Tamil profile as a *layer* of the ta-irv
pack (pack.json `indicQa`, indic_qa_tamil.py): the pack keeps its own JSON
rules and gains book-stage `indicqa.*` rules from indic_qa_rules.json. Only a
layer reads section headings (`<chapter>.headings.json`) and footnote text;
a profile pack's book is built exactly as before.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import pickle
import sys
import threading
from collections import Counter
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from typing import Any, Callable

from . import general_corpus, indic_qa_tamil, indic_qa_vendor, ov_reference
from .. import check_timing
from ..usfm_verse import lift_verse
from .loader import PackError, RulePack, Rule

ENGINE = "indic-qa"
RULE_VERSIONS = "rule_versions.json"
IRV_STATE = "irv_state.json.gz"
IRV_STATE_FORMAT = 2  # 1: one JSON document (still read). 2: JSON lines in pieces (read_state).
# Token statuses that are findings. Every other status (ok, irv_ok,
# inflected_ok, compound, sandhi_ok, ignored, learned) is a word the checker
# accepted.
FINDING_STATUSES = frozenset({"malformed", "suspect", "archaic", "rare_near_common", "unknown"})
# "sandhi": the Tamil layer only (indic_qa_tamil.py).
CATEGORIES = ("typo", "word-joining", "punctuation", "unicode", "spacing", "consistency", "grammar", "sandhi")
LAYERS = ("pattern", "lexicon", "integrity")
SEVERITIES = ("high", "medium", "low")
CONFIDENCES = ("high", "medium", "low")
ENTRY_KEYS = {"revision", "category", "layer", "severity", "confidence", "enabled", "inline", "note"}


def is_profile_pack(meta: dict[str, Any]) -> bool:
    return meta.get("engine") == ENGINE


def indic_config(meta: dict[str, Any]) -> dict[str, str] | None:
    """{profile, dictionary, layer} when the pack runs indic-qa's checker over
    a book: as the whole pack (a profile pack) or as a layer (`indicQa`).
    None otherwise."""
    if is_profile_pack(meta):
        return {"profile": str(meta.get("profile") or ""), "dictionary": str(meta.get("dictionary") or "dictionary"),
                "layer": ""}
    block = meta.get(indic_qa_tamil.LAYER_KEY)
    if isinstance(block, dict) and block.get("profile"):
        return {"profile": str(block["profile"]), "dictionary": str(block.get("dictionary") or "dictionary"),
                "layer": str(block.get("rules") or indic_qa_tamil.RULES_FILE)}
    return None


def runs_checker(pack: RulePack | None) -> bool:
    """Whether a Language QA pass runs this pack's indic-qa checker after the
    chapter loop: a profile pack, or a pack whose layer loaded."""
    if pack is None or indic_config(pack.meta) is None:
        return False
    return is_profile_pack(pack.meta) or any(r.match_type == ENGINE for r in pack.rules)


# -- the rule catalogue --------------------------------------------------------

def default_entry(rule_id: str, group: str, on_by_default: bool) -> dict[str, Any]:
    """The first rule_versions.json entry for an indic-qa rule, from its
    group. Written once by scripts/build_indic_qa_rule_versions.py; the file,
    not this function, is what the pack runs on, so a reviewed entry is never
    regenerated. Phase 1: nothing is inline (the human gate needs labels), and
    nothing is high severity with high confidence (that blocks export)."""
    tail = rule_id.split(".", 1)[1]
    category, layer, severity, confidence = {
        "Encoding": ("unicode", "integrity", "medium", "medium"),
        "Shape": ("unicode", "integrity", "medium", "medium"),
        "Punctuation": ("punctuation", "integrity", "medium", "medium"),
        "Lexicon": ("typo", "lexicon", "medium", "low"),
        "Consistency": ("consistency", "lexicon", "low", "low"),
        "Grammar": ("grammar", "pattern", "low", "low"),
        "Style": ("typo", "pattern", "low", "low"),
    }.get(group, ("typo", "pattern", "low", "low"))
    # First match wins.
    if any(k in tail for k in ("reduplication", "repeated-word", "postposition-joining")):
        category = "word-joining"
    elif "space" in tail:
        category = "spacing"
    elif group == "Shape" and tail.endswith(("single-letter", "long-token")):
        category, layer = "typo", "pattern"
    elif any(k in tail for k in ("hyphen", "dash", "quote", "ellipsis")):
        category = "punctuation"
    if tail in {"lex.known-misspelling", "style.divine-names", "style.rejected-names"}:
        confidence = "high"
    if tail == general_corpus.RULE_TAIL:
        severity, confidence = general_corpus.DEFAULT_ENTRY["severity"], general_corpus.DEFAULT_ENTRY["confidence"]
    if tail == "lex.unknown":
        # Not verifiable is not an error (the Hindi review found 22 of 25 such
        # words correct), but it is the web app's main mark, and a word with no
        # mark has no menu: no suggestions, no "Add". So it is on as upstream
        # has it, at the lowest severity and confidence, which the Settings
        # slider's confidence floor hides (DECISIONS 2026-10-08).
        severity, confidence = "low", "low"
    entry = {"revision": 1, "category": category, "layer": layer, "severity": severity,
             "confidence": confidence, "enabled": bool(on_by_default), "inline": False}
    if tail == "lex.unknown":
        entry["note"] = "not verifiable from the dictionary; drawn under the Settings slider (confidence low)"
    if tail == general_corpus.RULE_TAIL:
        entry["note"] = general_corpus.DEFAULT_ENTRY["note"]
    return entry


def catalogue(profile: Any, code: str) -> dict[str, tuple[str, str, bool, bool]]:
    """A profile pack's rule catalogue: the profile's RULES, then Bridge's own
    rule over the general corpus (#246), in that order."""
    return {**profile.RULES, **general_corpus.RULES.get(code, {})}


def catalogue_provenance(code: str) -> str:
    module = indic_qa_vendor.modules().langs.MODULE.get(code, code)
    return f"indic-qa qa_app/langs/{module}.py RULES; Bridge general_corpus.py over the general corpus"


def _rules(catalogue: Any, entries: dict[str, Any], pack_name: str, *,
           file: str = RULE_VERSIONS, provenance: str = "") -> list[Rule]:
    """Rules from an indic-qa catalogue -- a profile module (its RULES), or a
    catalogue dict such as indic_qa_tamil.RULES -- and the pack's Bridge view
    of each."""
    if hasattr(catalogue, "RULES"):
        provenance = provenance or f"indic-qa qa_app/langs/{catalogue.__name__.rsplit('.', 1)[-1]}.py RULES"
        catalogue = catalogue.RULES
    missing = sorted(set(catalogue) - set(entries))
    extra = sorted(set(entries) - set(catalogue))
    if missing or extra:
        raise PackError(f"{pack_name}/{file}: does not match the profile's RULES "
                        f"(missing {missing}, unknown {extra}); run scripts/build_indic_qa_packs.py")
    rules = []
    for rule_id, (group, label, _inline_upstream, _on) in catalogue.items():
        entry = entries[rule_id]
        where = f"{pack_name}/{file}: {rule_id}"
        if set(entry) - ENTRY_KEYS:
            raise PackError(f"{where}: unknown keys {sorted(set(entry) - ENTRY_KEYS)}")
        for key, allowed in (("category", CATEGORIES), ("layer", LAYERS), ("severity", SEVERITIES),
                             ("confidence", CONFIDENCES)):
            if entry.get(key) not in allowed:
                raise PackError(f"{where}: {key} must be one of {allowed}")
        if not isinstance(entry.get("revision"), int) or entry["revision"] < 1:
            raise PackError(f"{where}: revision must be a positive integer")
        if entry["severity"] == "high" and entry["confidence"] == "high":
            raise PackError(f"{where}: high severity with high confidence blocks export; not for an "
                            f"indic-qa rule without a DECISIONS entry")
        rules.append(Rule(
            id=rule_id, version=entry["revision"], legacy_id=None, enabled=bool(entry.get("enabled", True)),
            category=entry["category"], layer=entry["layer"], severity=entry["severity"],
            confidence=entry["confidence"], inline=bool(entry.get("inline", False)), message=label,
            rationale=f"indic-qa {group.lower()} rule", match_type=ENGINE, stage="book",
            params={"group": group},
            source={"provenance": provenance
                                  + (f"; {entry['note']}" if entry.get("note") else "")
                                  + ("" if entry.get("enabled", True) else "; DISABLED in Bridge")},
        ))
    return rules


def build_pack(meta: dict[str, Any], directory: Path) -> RulePack:
    """The RulePack for a profile pack directory (pack.json already read)."""
    name = str(meta.get("pack") or directory.name)
    code = str(meta.get("profile") or "")
    if code not in indic_qa_vendor.PROFILES:
        raise PackError(f"{name}/pack.json: profile must be one of {indic_qa_vendor.PROFILES}")
    if not (directory / str(meta.get("dictionary") or "dictionary") / "wordlist.txt").is_file():
        raise PackError(f"{name}: dictionary not found in {directory}")
    try:
        profile = indic_qa_vendor.profile(code)
    except ImportError as exc:
        raise PackError(f"{name}: the vendored indic-qa checker is unavailable: {exc}") from exc
    entries = json.loads((directory / RULE_VERSIONS).read_text(encoding="utf-8")).get("rules") or {}
    rules = _rules(catalogue(profile, code), entries, name, provenance=catalogue_provenance(code))
    return RulePack(name, str(meta.get("version") or "0"), str(meta.get("language") or code), rules,
                    str(meta.get("description") or ""), directory=directory, meta=meta)


def layer_rules(meta: dict[str, Any], directory: Path) -> tuple[list[Rule], list[str]]:
    """(rules, problems) for a pack's indic-qa layer (pack.json `indicQa`).
    A layer that cannot run (no dictionary, no vendored checker) adds no rules
    and one problem: the pack's own rules still run, never a load failure. A
    rule file that does not match the catalogue is a pack error, as for a
    profile pack."""
    config = indic_config(meta)
    name = str(meta.get("pack") or directory.name)
    if config is None or not config["layer"]:
        return [], []
    if config["profile"] not in indic_qa_vendor.LAYER_PROFILES:
        raise PackError(f"{name}/pack.json: {indic_qa_tamil.LAYER_KEY}.profile must be one of "
                        f"{indic_qa_vendor.LAYER_PROFILES}")
    if not (directory / config["dictionary"] / "wordlist.txt").is_file():
        return [], [f"{name}: the indic-qa dictionary is missing from {directory / config['dictionary']}; "
                    f"OV dictionary checks skipped"]
    try:
        indic_qa_vendor.profile(config["profile"])
    except ImportError as exc:
        return [], [f"{name}: the vendored indic-qa checker is unavailable ({exc}); OV dictionary checks skipped"]
    path = directory / config["layer"]
    try:
        entries = json.loads(path.read_text(encoding="utf-8")).get("rules") or {}
    except (OSError, ValueError) as exc:
        raise PackError(f"{name}: cannot read {config['layer']}: {exc}") from exc
    rules = _rules(indic_qa_tamil.RULES, entries, name, file=config["layer"],
                   provenance="indic-qa Tamil profile (qa_app/langs/ta.py, tamil_grammar.py) over the OV "
                              "dictionary; catalogue in indic_qa_tamil.py")
    return rules, []


def default_layer_entry(rule_id: str) -> dict[str, Any]:
    """The first indic_qa_rules.json entry for a Tamil layer rule."""
    _group, _label, _inline, on = indic_qa_tamil.RULES[rule_id]
    entry = {"revision": 1, **indic_qa_tamil.DEFAULT_ENTRIES[rule_id], "inline": False}
    entry.setdefault("enabled", bool(on))
    return {k: entry[k] for k in ("revision", "category", "layer", "severity", "confidence", "enabled", "inline",
                                  "note") if k in entry}


# -- the IRV state snapshot ------------------------------------------------------

def encode_state(value: Any) -> Any:
    """JSON for the checker's index state, keeping the types its code relies
    on: Counter (it calls subtract/update on them), dict, set, tuple (keys of
    join_split are word pairs). Keys are sorted, so the file is deterministic."""
    if isinstance(value, Counter):
        return {"C": sorted(([encode_state(k), n] for k, n in value.items()), key=_sort_key)}
    if isinstance(value, dict):
        return {"D": sorted(([encode_state(k), encode_state(v)] for k, v in value.items()), key=_sort_key)}
    if isinstance(value, tuple):
        return {"T": [encode_state(v) for v in value]}
    if isinstance(value, (set, frozenset)):
        return {"S": sorted((encode_state(v) for v in value), key=_sort_key)}
    if isinstance(value, list):
        return [encode_state(v) for v in value]
    return value


def _sort_key(item: Any) -> str:
    return json.dumps(item, ensure_ascii=False, sort_keys=True)


def decode_state(value: Any) -> Any:
    if isinstance(value, list):
        return [decode_state(v) for v in value]
    if isinstance(value, dict):
        if "C" in value:
            return Counter({_key(k): n for k, n in value["C"]})
        if "D" in value:
            return {_key(k): decode_state(v) for k, v in value["D"]}
        if "T" in value:
            return tuple(decode_state(v) for v in value["T"])
        if "S" in value:
            return {_key(v) for v in value["S"]}
    return value


def _key(value: Any) -> Any:
    decoded = decode_state(value)
    return tuple(decoded) if isinstance(decoded, list) else decoded


def snapshot(checker: Any) -> dict[str, Any]:
    """What `index_book` wrote, for every book indexed so far, encoded
    (encode_state). A profile with sandhi (Tamil) also keeps each book's ஒற்று
    pair and form counts, which index_book holds outside `data` (the IRV veto
    and the dangling check read their IRV-wide sums)."""
    out = {"bookCount": encode_state(checker.book_count), "data": encode_state(checker.data)}
    if checker.lang.sandhi:
        out["bookPairs"] = encode_state(checker.book_pairs)
        out["bookFormUse"] = encode_state(checker.book_form_use)
    return out


# The snapshot is restored on the Language QA thread while the dispatcher
# answers the UI, and one json.loads (or pickle.loads) of a whole 10-27 MB state
# holds the GIL for hundreds of milliseconds: ping waited that long. So the
# file (format 2) is JSON lines: a header {"format", "provenance"}, then one
# line per *piece*, at most STATE_PIECE entries of one container, as
# [id, entries]. Container 0 is the root ({bookCount, data, ...}); a value that
# is itself a dict, Counter or set is written {"@": [kind, id]} where it sits,
# created empty there, and filled by the later pieces of that id. A dict's
# entries are a JSON object when every key is a string and every value a
# plain string or int (dict.update takes it as it is), else [key, value] pairs
# in encode_state's encoding; a set's are its encoded elements. Entries keep
# format 1's order, so a restore builds what format 1 built, in the same
# insertion order. Format 1 (one document) is still read.
STATE_PIECE = 2048
_FORMAT_2_HEAD = b'{"format":2,'
_KINDS = {"C": Counter, "D": dict, "S": set}
_PLAIN = (str, int)


class _Ref:
    """In a piece: an empty container of `kind`, created in its parent's place
    and filled by the pieces of id `ident`."""
    __slots__ = ("kind", "ident")

    def __init__(self, kind: str, ident: int):
        self.kind, self.ident = kind, ident

    def __reduce__(self):
        return _Ref, (self.kind, self.ident)


def _encoded_pieces(fields: dict[str, Any]) -> Any:
    """The [id, entries] lines of encoded fields (snapshot()'s, or a format-1
    file's), breadth first."""
    queue: list[tuple[str, list]] = [("D", [[k, fields[k]] for k in sorted(fields)])]
    for ident, (kind, entries) in enumerate(queue):
        for start in range(0, len(entries), STATE_PIECE):
            chunk = entries[start:start + STATE_PIECE]
            if kind == "S":
                yield [ident, chunk]
                continue
            pairs, plain = [], True
            for key, value in chunk:
                child = next(iter(value)) if isinstance(value, dict) and len(value) == 1 else None
                if child in _KINDS:
                    queue.append((child, value[child]))
                    value = {"@": [child, len(queue) - 1]}
                    plain = False
                else:
                    plain = plain and type(key) is str and type(value) in _PLAIN
                pairs.append([key, value])
            yield [ident, dict(pairs) if plain else pairs]


def _native_pieces(fields: dict[str, Any]) -> Any:
    """The (id, plain, entries) pieces of a live state, in its own iteration
    order: what the in-memory cache keeps (_restore_cached). A dict's entries
    are a dict, a set's a list: no per-entry objects to allocate and free."""
    queue: list[Any] = [fields]
    for ident, container in enumerate(queue):
        if isinstance(container, (set, frozenset)):
            items = iter(container)
            while chunk := list(islice(items, STATE_PIECE)):
                yield ident, True, chunk
            continue
        items = iter(container.items())
        while chunk := dict(islice(items, STATE_PIECE)):
            plain = True
            for key, value in chunk.items():
                kind = ("C" if isinstance(value, Counter) else "D" if isinstance(value, dict)
                        else "S" if isinstance(value, (set, frozenset)) else None)
                if kind is not None:
                    queue.append(value)
                    chunk[key] = _Ref(kind, len(queue) - 1)
                    plain = False
                elif plain and not (type(key) in _PLAIN and type(value) in _PLAIN):
                    plain = False
            yield ident, plain, chunk


def _fill(containers: dict[int, Any], ident: int, plain: bool, entries: Any) -> None:
    """Apply one piece; each call is bounded by STATE_PIECE entries."""
    target = containers[ident]
    if isinstance(target, set):
        target.update(entries)
    elif plain:
        dict.update(target, entries)  # Counter.update would add; the target is fresh
    else:
        for key, value in entries.items():
            if type(value) is _Ref:
                ref, value = value, _KINDS[value.kind]()
                containers[ref.ident] = value
            target[key] = value


def _decode_line(containers: dict[int, Any], line: list) -> tuple[int, bool, Any]:
    """A format-2 line as a native piece of the container it fills."""
    ident, entries = line
    if isinstance(entries, dict):
        return ident, True, entries
    if isinstance(containers[ident], set):
        return ident, True, [_key(v) for v in entries]
    out = {}
    for key, value in entries:
        if isinstance(value, dict) and "@" in value:
            out[_key(key)] = _Ref(*value["@"])
        else:
            out[_key(key)] = decode_state(value)
    return ident, False, out


def encode_state_file(fields: dict[str, Any], provenance: dict[str, Any]) -> bytes:
    """Format-2 text (uncompressed) of encoded fields: snapshot()'s, or a
    format-1 file's (scripts/convert_pack_pieces.py). Pieces keep their own
    order (no sort_keys: format 1's order is by encoded pair, not by key)."""
    lines = [json.dumps({"format": IRV_STATE_FORMAT, "provenance": provenance}, ensure_ascii=False,
                        separators=(",", ":"), sort_keys=True)]
    lines.extend(json.dumps(line, ensure_ascii=False, separators=(",", ":")) for line in _encoded_pieces(fields))
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_state(path: Path, checker: Any, provenance: dict[str, Any]) -> None:
    """The snapshot file, format 2; deterministic (gzip mtime 0)."""
    path.write_bytes(gzip.compress(encode_state_file(snapshot(checker), provenance), 9, mtime=0))


def read_state(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """(fields, provenance) of a snapshot file, decoded. The fields are
    bookCount, data and, for Tamil, bookPairs and bookFormUse. Format 2 is
    read a line at a time; format 1 in one call."""
    with gzip.open(path, "rb") as stream:
        head = stream.read(len(_FORMAT_2_HEAD))
        if head != _FORMAT_2_HEAD:
            raw = json.loads(head + stream.read())
            if raw.get("format") != 1:
                raise PackError(f"{path}: snapshot format {raw.get('format')} is not {IRV_STATE_FORMAT}")
            fields = {k: decode_state(raw[k]) for k in ("bookCount", "data", "bookPairs", "bookFormUse") if k in raw}
            return fields, raw.get("provenance") or {}
        header = json.loads(head + stream.readline())
        containers: dict[int, Any] = {0: {}}
        for line in stream:
            if line.strip():
                _fill(containers, *_decode_line(containers, json.loads(line)))
    return containers[0], header.get("provenance") or {}


def restore_state(checker: Any, path: Path) -> dict[str, Any]:
    """Load a snapshot into a fresh checker; returns its provenance."""
    fields, provenance = read_state(path)
    _assign(checker, fields)
    return provenance


def _assign(checker: Any, fields: dict[str, Any]) -> None:
    """A snapshot's fields onto a checker, with the IRV-wide sums derived."""
    checker.book_count = fields["bookCount"]
    checker.irv_count = Counter()
    for counts in checker.book_count.values():
        checker.irv_count.update(counts)
    checker.data = fields["data"]
    if "bookPairs" in fields:
        # The IRV-wide sums are derived, exactly as _index_pairs builds them.
        checker.book_pairs = fields["bookPairs"]
        checker.book_form_use = fields["bookFormUse"]
        checker.irv_pairs, checker.irv_form_use = {}, {}
        for pairs in checker.book_pairs.values():
            for (bare, cls, has), n in pairs.items():
                checker.irv_pairs.setdefault((bare, cls), [0, 0])[1 - has] += n
        for forms in checker.book_form_use.values():
            for (word, index), n in forms.items():
                checker.irv_form_use.setdefault(word, [0, 0])[index] += n


# -- one resident checker ------------------------------------------------------------

@dataclass
class LoadedChecker:
    key: tuple
    checker: Any
    lang: Any
    profile: Any
    provenance: dict[str, Any] = field(default_factory=dict)
    # The open book's token counts at the last build_index, per book code.
    built_for: dict[str, Counter] = field(default_factory=dict)
    # The one book whose live text replaced its snapshot share, if any.
    live_book: str | None = None
    # (lexicon generation, settings generation) at the last full build_index.
    index_state: tuple[int, int] | None = None


def _same_index(loaded: LoadedChecker, previous: Counter, counts: Counter) -> bool:
    """Whether build_index would rebuild the index the checker already holds,
    after the open book's counts moved from `previous` to `counts` (#271).
    Its sources are the lexicon's words (lemma_min), its extra words, and every
    IRV word the lexicon knows that occurs at least irv_min times; so with the
    lexicon and the settings unchanged since the last build, and no changed
    word crossing irv_min, the same sorted sources give the same index. A
    language with an on_build_index hook (hi, ml: consistency clusters from
    counts) is always rebuilt."""
    checker = loaded.checker
    if checker.lang.on_build_index or loaded.index_state != (checker.lex.generation, checker.settings_gen):
        return False
    irv_min = checker.settings["suggest"]["irv_min"]
    for word in set(previous) | set(counts):
        delta = counts.get(word, 0) - previous.get(word, 0)
        if not delta:
            continue
        after = checker.irv_count.get(word, 0)
        if ((after - delta) >= irv_min) != (after >= irv_min) and checker.lex.known(word):
            return False
    return True


_LOCK = threading.Lock()
_RESIDENT: LoadedChecker | None = None

# What a word not in the OV dictionary looks like to the checker: the "Book
# words" list (indic-qa's unknown-word table). irv_ok / inflected_ok are words
# the IRV itself uses; unknown is neither.
BOOK_WORD_STATUSES = frozenset({"unknown", "irv_ok", "inflected_ok", "compound", "rare_near_common"})


def word_statuses(pack_name: str, words: list[str]) -> dict[str, tuple[str, int, int]] | None:
    """word -> (status, IRV count, OV count) from the resident checker of
    `pack_name`, for words outside the dictionary; None when no checker of that
    pack is resident (no pass has run it yet). Read under the adapter's lock,
    since a pass mutates the checker."""
    with _LOCK:
        loaded = _RESIDENT
        if loaded is None or loaded.key[0] != pack_name:
            return None
        checker = loaded.checker
        out: dict[str, tuple[str, int, int]] = {}
        for word in words:
            status = checker.classify(word).status
            if status in BOOK_WORD_STATUSES:
                out[word] = (status, int(checker.irv_count.get(word, 0)), int(checker.lex.lemma_count.get(word, 0)))
        return out


def _settings(pack: RulePack) -> dict[str, Any]:
    """What the checker runs with, over its language defaults (the checker
    merges one level deep): the project's own settings (pack.checker_settings,
    the Checker settings dialog), then indic-qa's per-rule switches, which
    follow the pack and its overrides so a rule Bridge disabled does not run
    inside the checker either, then a layer's forced switches
    (indic_qa_tamil.SETTINGS), which a project cannot change."""
    settings: dict[str, Any] = json.loads(json.dumps(pack.checker_settings))
    settings["rules"] = {r.id: r.enabled for r in pack.rules}
    config = indic_config(pack.meta)
    if config is not None and config["layer"]:
        for section, values in indic_qa_tamil.SETTINGS.items():
            settings[section] = {**settings.get(section, {}), **values}
    return settings


def with_resident(pack_name: str, read: Callable[[Any, Any], Any]) -> Any:
    """read(checker, profile) on the resident checker of `pack_name`, under the
    adapter's lock since a pass mutates it; None when no checker of that pack
    is resident (no pass has loaded it yet)."""
    with _LOCK:
        loaded = _RESIDENT
        if loaded is None or loaded.key[0] != pack_name:
            return None
        return read(loaded.checker, loaded.profile)


# A checker is rebuilt from the snapshot whenever a pass moves to another book
# (_resident). What that costs is reading the dictionary and decoding the
# snapshot, which never change while the files do not: so the restored index
# state is kept, pickled in memory, for the last snapshot read, and a layer's
# Lexicon (read only: the dictionaries are never written, NOTICE.md contract 2)
# is shared. A rebuilt checker is then identical to one built from the files.
# The pickle is one stream of pieces (_native_pieces), each dumped and loaded
# by its own call, so that no one call holds the GIL for long; one Pickler and
# one Unpickler share their memo across the pieces, so the copy shares objects
# exactly as one pickle of the whole state would.
_STATE_CACHE: dict[tuple, tuple[tuple[bytes, int], dict[str, Any]]] = {}
_LEXICON_CACHE: dict[tuple, Any] = {}
_STATE_FIELDS = ("book_count", "irv_count", "data", "book_pairs", "irv_pairs", "book_form_use", "irv_form_use")


def _file_key(path: Path) -> tuple:
    stat = path.stat()
    return (str(path.resolve()), stat.st_mtime_ns, stat.st_size)


def _restore_cached(checker: Any, path: Path) -> dict[str, Any]:
    """restore_state, decoded once per snapshot file version."""
    key = _file_key(path)
    cached = _STATE_CACHE.get(key)
    if cached is None:
        provenance = restore_state(checker, path)
        buffer = io.BytesIO()
        pickler = pickle.Pickler(buffer, protocol=pickle.HIGHEST_PROTOCOL)
        count = 0
        for piece in _native_pieces({f: getattr(checker, f) for f in _STATE_FIELDS}):
            pickler.dump(piece)
            count += 1
        del pickler
        _STATE_CACHE.clear()
        _STATE_CACHE[key] = cached = ((buffer.getvalue(), count), provenance)
        return provenance
    (blob, count), provenance = cached
    unpickler = pickle.Unpickler(io.BytesIO(blob))
    containers: dict[int, Any] = {0: {}}
    for _ in range(count):
        _fill(containers, *unpickler.load())
    for name, value in containers[0].items():
        setattr(checker, name, value)
    return provenance


def _lexicon(mods: Any, folder: Path, lang: Any, shared: bool) -> Any:
    if not shared:
        return mods.checker.Lexicon.load(folder, lang)
    key = (_file_key(folder / "wordlist.txt"), _file_key(folder / "words.tsv"), lang.code)
    lex = _LEXICON_CACHE.get(key)
    if lex is None:
        _LEXICON_CACHE.clear()
        lex = _LEXICON_CACHE[key] = mods.checker.Lexicon.load(folder, lang)
    return lex


def _load(pack: RulePack) -> LoadedChecker:
    mods = indic_qa_vendor.modules()
    config = indic_config(pack.meta) or {}
    code = str(config.get("profile") or "")
    lang = mods.langs.get(code)
    folder = pack.directory / str(config.get("dictionary") or "dictionary")
    lexicon = _lexicon(mods, folder, lang, shared=bool(config.get("layer")))
    checker = mods.checker.Checker(lexicon, _settings(pack), lang)
    provenance: dict[str, Any] = {}
    state = pack.directory / IRV_STATE
    if state.is_file():
        provenance = _restore_cached(checker, state)
    # No build_index here: the first pass indexes its book and builds then.
    return LoadedChecker((pack.name, pack.version, json.dumps(_settings(pack), sort_keys=True)), checker,
                         lang, indic_qa_vendor.profile(code), provenance)


def _drop(loaded: LoadedChecker | None) -> None:
    """Free a checker that is no longer resident, before the next one loads.
    It holds no reference cycle (test_a_released_checker_is_freed_without_the_
    cycle_collector), so dropping it frees it. The gc.collect() that was here
    collected nothing after real passes of all five packs, and a full
    collection scans the whole engine heap in one call (45-90 ms measured
    during a scan). Its index state is let go a book at a time: freeing it in
    one cascade is one long call too. A container is emptied only when this
    is its last reference, so nothing anyone else holds is ever changed."""
    if loaded is None:
        return
    state = vars(loaded.checker)
    del loaded
    for name in _STATE_FIELDS:
        value = state.pop(name, None)
        # A dict of containers (book -> Counter) is popped one entry at a time,
        # when `value` and getrefcount's argument are its only references.
        if (isinstance(value, dict) and value and sys.getrefcount(value) == 2
                and isinstance(next(iter(value.values())), (dict, set))):
            while value:
                value.popitem()
        del value


def release(keep: str | None = None) -> None:
    """Drop the resident checker unless it belongs to pack `keep`."""
    global _RESIDENT
    with _LOCK:
        if _RESIDENT is not None and _RESIDENT.key[0] != keep:
            old, _RESIDENT = _RESIDENT, None
            _drop(old)


def checker_key(pack: RulePack) -> str:
    """What a resident checker is built from (_resident's key) as one string:
    the pack, its version and every checker setting, project overrides
    included, which RulePack.fingerprint() does not cover. A cached book
    result of the checker is valid only under the same key (#271)."""
    return json.dumps([pack.name, pack.version, _settings(pack)], sort_keys=True, ensure_ascii=False)


def is_resident(pack: RulePack, book: str) -> bool:
    """Whether the resident checker is `pack`'s, under its current settings,
    holding `book`'s live text: what the panel's Book words list reads. A pass
    that reuses its cached book result must still leave this true, so it runs
    the checker again when it is not (another book or pack was checked)."""
    key = (pack.name, pack.version, json.dumps(_settings(pack), sort_keys=True))
    with _LOCK:
        return _RESIDENT is not None and _RESIDENT.key == key and _RESIDENT.live_book == book_key(book)


def _resident(pack: RulePack, book: str) -> LoadedChecker:
    """The pack's checker, holding the IRV snapshot plus at most one live book.
    A pass over another book starts again from the snapshot: otherwise a book
    checked earlier in the session would keep its live counts, and a book's
    findings would depend on which books were opened before it."""
    global _RESIDENT
    key = (pack.name, pack.version, json.dumps(_settings(pack), sort_keys=True))
    if _RESIDENT is None or _RESIDENT.key != key or _RESIDENT.live_book not in (None, book):
        old, _RESIDENT = _RESIDENT, None
        _drop(old)
        _RESIDENT = _load(pack)
    return _RESIDENT


# -- Bridge chapters as an indic-qa book ---------------------------------------------

# Heading tags that are references, not text: never checked.
REFERENCE_HEADINGS = frozenset({"r", "mr", "sr", "rq"})
# Footnote parts that are prose (\fr is the reference, \fv a verse number).
FOOTNOTE_TEXT = frozenset({"ft", "fq", "fqa", "fk", "fp", "fl", "fw"})


@dataclass(frozen=True)
class LineRef:
    chapter: str
    verse: str
    text: str            # the raw string offsets index: the verse as stored, or a heading's text
    lifted: Any          # language_qa.LiftedVerse of `text`
    base: int            # where this physical line starts in lifted.visible
    context: str = "verse"       # "verse" | "heading"
    # Footnote runs on this line: (run start in the line, raw offset of its text in `text`).
    notes: tuple[tuple[int, int], ...] = ()
    index: int = 0       # a heading's place among the headings before its verse


def book_key(book: str) -> str:
    """The checker's index key for a book: Bridge's book id, lower case."""
    return book.strip().lower()


def _verse_numbers(verse: str) -> tuple[int, int | None]:
    """First and last number of a verse key ("3", "3-4", "3a"); the key itself
    is kept as given on every finding (CLAUDE.md gotcha 12)."""
    head, _, tail = verse.partition("-")
    first = int("".join(ch for ch in head if ch.isdigit()) or 0)
    last = "".join(ch for ch in tail if ch.isdigit())
    return first, int(last) if last else None


# (raw text, base, length) -> its runs: a book pass splits every line again,
# though only an edited verse's lines can split differently (#271). Bounded by
# clearing; a line's runs are a pure function of its raw text.
_RUNS: dict[tuple[str, int, int], list[tuple[int, int]]] = {}
RUNS_MEMO = 8192


def _runs(lifted: Any, base: int, length: int, raw: str | None = None) -> list[tuple[int, int]]:
    """The text runs of one physical line, as (start, end) in the line: a run
    ends where lifted markup was (the next visible character does not follow
    the previous one in the raw verse). indic-qa's runs end at every marker
    too, and some of its rules work per run (Malayalam's grouped encoding fix);
    for adjacency it joins the runs of a line into one stream, as here.
    `raw`, the text `lifted` was lifted from, memoizes the answer."""
    if raw is not None:
        key = (raw, base, length)
        known = _RUNS.get(key)
        if known is None:
            if len(_RUNS) >= RUNS_MEMO:
                _RUNS.clear()
            known = _RUNS[key] = _runs(lifted, base, length)
        return known
    if length == 0:
        return [(0, 0)]
    index = lifted.raw_index
    out, start = [], 0
    for i in range(1, length):
        if index[base + i] != index[base + i - 1] + 1:
            out.append((start, i))
            start = i
    out.append((start, length))
    return out


def _footnote_texts(raw: str, notes: Any = None) -> tuple[list[tuple[str, int]], int]:
    """([(text, raw offset)], skipped) for the prose parts of a verse's
    footnotes. usfm_verse.lift_verse is the reader (gotcha 14); `notes`, when
    the verse was lifted already, are its notes (no second lifting, #271). A
    part's text is cut verbatim from the note, so it is found again inside the
    note's own raw range by plain string search. A part that cannot be found
    is skipped and counted, never guessed."""
    out: list[tuple[str, int]] = []
    skipped = 0
    for note in (lift_verse(raw).notes if notes is None else notes):
        if note.kind != "footnote":
            continue
        cursor = note.raw_start
        for marker, text in note.parts:
            at = raw.find(text, cursor, note.raw_end) if text else -1
            if at < 0:
                skipped += marker in FOOTNOTE_TEXT
                continue
            cursor = at + len(text)
            if marker in FOOTNOTE_TEXT:
                out.append((text, at))
    return out, skipped


def build_book(book: str, chapters: dict[str, dict[str, Any]], *, lift: Callable[[str], Any],
               max_verse_chars: int, headings: dict[str, dict[str, list[dict[str, Any]]]] | None = None,
               footnotes: bool = False) -> tuple[Any, dict[int, LineRef], list[str]]:
    """(indic-qa Book, line index -> LineRef, notes). `lift(text)` is
    language_qa.lift_inline_usfm. A verse whose markup cannot be lifted is
    left out; the common rules already report why.

    `headings` (chapter -> introduced verse -> [{tag, text}], tc_project's
    chapter_headings) adds each section heading as its own line before the
    verse it introduces; `footnotes` adds each footnote's prose as a separate
    stream on its verse's first line, as indic-qa's own parser does. A
    profile pack passes neither, so its book is exactly what it was."""
    ud = indic_qa_vendor.modules().usfm_doc
    lines: list[Any] = []
    refs: dict[int, LineRef] = {}
    spans: list[tuple[int, int]] = [(0, -1)]  # chapter 0: front matter, none
    notes: list[str] = []
    skipped_notes = 0
    line_no = 0

    def heading_lines(chapter: str, n: int, verse: str, items: list[dict[str, Any]], previous: int) -> None:
        nonlocal line_no
        number, last = _verse_numbers(verse)
        for k, item in enumerate(items):
            tag, text = str(item.get("tag") or "s"), item.get("text")
            if tag in REFERENCE_HEADINGS or not isinstance(text, str) or not text.strip() \
                    or len(text) > max_verse_chars:
                continue
            lifted, _reason = lift(text)
            if lifted is None:
                continue
            base = 0
            for piece in lifted.visible.split("\n"):
                line_no += 1
                segs = [ud.Seg("t", piece[a:b], a, "", "heading", 0) for a, b in _runs(lifted, base, len(piece), text)]
                refs[len(lines)] = LineRef(chapter, verse, text, lifted, base, "heading", (), k)
                lines.append(ud.Line(line_no, piece, "s", "s", n, number, last, f"{book} {n}:{verse}", segs, [],
                                     (n, previous, None, "s")))
                base += len(piece) + 1

    for chapter in sorted(chapters, key=lambda c: int(c) if c.isdecimal() else 0):
        if not chapter.isdecimal():
            continue
        n = int(chapter)
        while len(spans) < n:
            spans.append((len(lines), len(lines) - 1))  # a missing chapter: empty
        first = len(lines)
        line_no += 1
        # The chapter line stops next_first() and the stream at a chapter break.
        lines.append(ud.Line(line_no, "", "c", "p", n, 0, None, f"{book} {n}:0", [], [], (n, 0, None, "p")))
        pending = dict((headings or {}).get(chapter) or {})
        previous = 0
        for verse, text in chapters[chapter].items():
            if verse in pending:
                heading_lines(chapter, n, verse, pending.pop(verse), previous)
            if not verse[:1].isdigit() or not isinstance(text, str) or len(text) > max_verse_chars:
                continue
            lifted, _reason = lift(text)
            if lifted is None:
                continue
            number, last = _verse_numbers(verse)
            parts, skipped = _footnote_texts(text, lifted.notes) if footnotes else ([], 0)
            skipped_notes += skipped
            base = 0
            for k, piece in enumerate(lifted.visible.split("\n")):
                line_no += 1
                ref = f"{book} {n}:{verse}"
                style, para = ("v", "p") if k == 0 else ("q", "q")
                segs = [ud.Seg("t", piece[a:b], a, "", "verse", 0) for a, b in _runs(lifted, base, len(piece), text)]
                note_runs: list[tuple[int, int]] = []
                if k == 0:
                    # Each footnote part is its own stream, placed after the line's
                    # text so its run offsets never meet the body's.
                    at = len(piece) + 1
                    for stream, (note_text, raw_at) in enumerate(parts, start=1):
                        segs.append(ud.Seg("t", note_text, at, "", "footnote_text", stream))
                        note_runs.append((at, raw_at))
                        at += len(note_text) + 1
                refs[len(lines)] = LineRef(chapter, verse, text, lifted, base, "verse", tuple(note_runs))
                lines.append(ud.Line(line_no, piece, style, para, n, number, last, ref, segs, [],
                                     (n, previous, None, "p")))
                base += len(piece) + 1
            previous = number
        for verse, items in pending.items():  # a heading whose verse is not in the chapter map
            heading_lines(chapter, n, verse, items, previous)
        spans.append((first, len(lines) - 1))
    if skipped_notes:
        notes.append(f"{skipped_notes} footnote part(s) could not be located in their note; not checked.")
    return ud.Book(book, lines, spans), refs, notes


# -- mapping ------------------------------------------------------------------------

def _suggestion(text: str, source: str, rationale: str, *, kind: str = "", freq: int | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"text": text, "rank": 1, "source": source, "rationale": rationale}
    if kind:
        out["kind"] = kind
    if freq is not None:
        out["freq"] = int(freq)
    return out


def _items(block: dict[str, Any], profile: Any, corpus: Any = None, *, irv_accept_min: int = 5,
           stats: Counter | None = None) -> list[indic_qa_tamil.Item]:
    """Every finding in one checked line of a profile pack's book, offsets
    within the line text (an item's own offsets are within its run, which
    starts at the run's `s`). With a general corpus (#246): an unknown word
    the corpus knows is accepted and counted in `stats`; one it does not know
    gains the corpus's near-misses after the checker's suggestions; a word the
    IRV uses `irv_accept_min` times that neither the OV nor the corpus knows,
    one edit from a corpus word, is the consistent-slip rule."""
    out = []
    switch = getattr(profile, "SHAPE_RULE_SWITCH", {})
    status_rule = getattr(profile, "STATUS_RULE", {})
    generic = getattr(profile, "GENERIC_WARNING_RULE", {})
    slip_rule = general_corpus.rule_id(profile.PROFILE.code) if corpus is not None else ""
    for seg in block["segs"]:
        if seg.get("k") != "t" or not seg.get("checked"):
            continue
        at = seg["s"]

        def item(rule: str, start: int, end: int, suggestions: list, why: str, detail: str) -> indic_qa_tamil.Item:
            return indic_qa_tamil.Item(rule, start, end, suggestions, why, detail, at, 0, "verse")

        for token in seg.get("tokens", ()):
            if token.get("ignored_once"):
                continue
            said = general_corpus.verdict(corpus, token, irv_accept_min=irv_accept_min) if corpus is not None else None
            if said is not None and said.kind == "accept":
                if stats is not None:
                    stats["accepted"] += 1
                continue
            if said is not None and said.kind == "slip":
                out.append(item(slip_rule, at + token["s"], at + token["e"], said.suggestions, said.note,
                                token["status"]))
                continue
            if token["status"] not in FINDING_STATUSES:
                continue
            detail = token.get("rule") or status_rule.get(token["status"], "")
            suggestions = [_suggestion(s["w"], "lexicon", f"{s.get('cls') or s.get('op') or ''}"
                                       + (f" · {s['freq']}× in the IRV" if s.get("freq") else ""),
                                       kind=str(s.get("cls") or s.get("op") or ""),
                                       freq=s.get("freq") if isinstance(s.get("freq"), int) else None)
                           for s in token.get("sugg", ()) if s.get("w")]
            why = "; ".join(token.get("why") or ())
            if said is not None and said.kind == "augment":
                suggestions = general_corpus.append_suggestions(suggestions, said.suggestions)
                why = f"{why}; {said.note}" if why else said.note
            out.append(item(switch.get(detail, detail), at + token["s"], at + token["e"], suggestions, why, detail))
        for lead in seg.get("sandhi", ()):
            if lead.get("ignored"):
                continue
            proposed = lead.get("proposed")
            source = "majority-form" if lead.get("kind") == "consistency" else "rule"
            why = "; ".join(lead.get("why") or ())
            suggestions = [_suggestion(proposed, source, why)] if proposed and proposed != lead.get("w1") else []
            out.append(item(lead.get("rule", ""), at + lead["s"], at + lead["e"], suggestions,
                            lead.get("title") or "", lead.get("rule", "")))
        for warning in seg.get("warnings", ()):
            if warning.get("ignored"):
                continue
            rule = warning.get("rule") or generic.get(warning["kind"], "")
            fix = warning.get("fix")
            suggestions = [_suggestion(fix, "rule", warning.get("fix_label") or "")] if fix is not None else []
            out.append(item(rule, at + warning["s"], at + warning["e"], suggestions, warning.get("label") or "", rule))
    return out


def profile_findings(pack: RulePack, book: str, chapters: dict[str, dict[str, Any]], *,
                     lift: Callable[[str], Any], max_verse_chars: int, finding_id: Callable[..., str],
                     rule_fields: Callable[..., dict[str, Any]], text_hash: Callable[[str], str],
                     crossing_note: str, proceed: Callable[[], bool] = lambda: True,
                     headings: dict[str, dict[str, list[dict[str, Any]]]] | None = None,
                     ) -> tuple[list[dict[str, Any]], list[str]] | None:
    """Every finding of the pack's checker over one book, in reading order,
    before decisions; and coverage notes. None when `proceed()` says stop.
    The language_qa helpers are passed in, to keep the import one-way.

    A layer (ta-irv's indicQa) also checks `headings` and footnote text, and
    attaches the OV verse (ov_reference) to each finding. A finding in a
    heading carries `context: "heading"`, its offsets index the heading's own
    text (`contextText`), and it offers no suggestion to apply: a fix would be
    written into the verse, which is not where the heading lives. A finding
    in a footnote carries `context: "footnote"`; its offsets are in the
    stored verse, so its fix goes through the one verse writer as usual."""
    config = indic_config(pack.meta) or {"layer": "", "dictionary": "dictionary"}
    layer = bool(config["layer"])
    timings = check_timing.current()
    with timings.step("lqa.indicqa.build_book"):
        synthetic, refs, notes = build_book(book, chapters, lift=lift, max_verse_chars=max_verse_chars,
                                            headings=headings if layer else None, footnotes=layer)
    dictionary = pack.directory / config["dictionary"] if pack.directory else None
    findings: list[dict[str, Any]] = []
    crossing = unmapped = 0
    with _LOCK:
        # The snapshot keys books by Bridge's book id, lower case ("1ch"); the
        # same key here replaces that book's share instead of adding a 67th.
        key = book_key(book)
        with timings.step("lqa.indicqa.checker_load"):
            loaded = _resident(pack, key)
        loaded.live_book = key
        checker = loaded.checker
        with timings.step("lqa.indicqa.index_book"):
            checker.index_book(key, synthetic)
        counts = checker.book_count.get(key, Counter())
        previous = loaded.built_for.get(key)
        if previous != counts:
            # A new or changed word can start or join a consistency cluster, and
            # build_index is where clusters are made; it also clears classify()'s
            # cache, which is keyed by generation, not by counts. Unchanged text
            # (a decision, a status refresh) needs neither.
            if previous is not None and _same_index(loaded, previous, counts):
                # The suggestion index build_index would make is the one held:
                # only the caches it clears are stale (#271).
                timings.cached("lqa.indicqa.build_index")
                checker._cache.clear()
                checker._rule_cache.clear()
            else:
                with timings.step("lqa.indicqa.build_index"):
                    checker.build_index()
                loaded.index_state = (checker.lex.generation, checker.settings_gen)
            loaded.built_for = {key: Counter(counts)}
        occurrences: Counter = Counter()
        ov_table = ov_reference.verses(dictionary) if layer and dictionary is not None else None
        # The general corpus (#246): consulted after the checker, in Bridge's
        # code. The slip rule reports a word once per book, at its first place.
        with timings.step("lqa.indicqa.corpus_load"):
            corpus = general_corpus.for_pack(pack.meta, pack.directory, config["profile"])
        corpus_stats: Counter = Counter()
        slip_rule = general_corpus.rule_id(config["profile"]) if corpus is not None else ""
        slips_seen: set[str] = set()
        irv_accept_min = int((checker.settings.get("lex") or {}).get("irv_accept_min")
                             or indic_qa_tamil.IRV_ACCEPT_MIN)
        for n in range(1, len(synthetic.chapters)):
            if not proceed():
                return None
            lo, _hi = synthetic.chapters[n]
            with timings.step("lqa.indicqa.check_chapter"):
                blocks = list(checker.check_chapter(synthetic, n))
            map_items = timings.step("lqa.indicqa.map_findings")
            map_items.__enter__()
            for offset, block in enumerate(blocks):
                ref = refs.get(lo + offset)
                if ref is None:
                    continue
                found = (indic_qa_tamil.items(block, corpus, stats=corpus_stats) if layer
                         else _items(block, loaded.profile, corpus, irv_accept_min=irv_accept_min, stats=corpus_stats))
                for item in found:
                    rule = pack.by_id(item.rule)
                    if rule is None:
                        unmapped += 1
                        continue
                    if not rule.enabled:
                        continue
                    if item.stream > 0:
                        raw_at = dict(ref.notes).get(item.seg_start)
                        span = (None if raw_at is None else
                                (raw_at + item.start - item.seg_start, raw_at + item.end - item.seg_start))
                    else:
                        span = ref.lifted.raw_span(ref.base + item.start, ref.base + item.end)
                    if span is None:
                        crossing += 1
                        continue
                    context = ref.context if ref.context != "verse" else ("footnote" if item.stream else "verse")
                    id_rule = rule.name if context == "verse" else (
                        f"{rule.name}@{context}" + (str(ref.index) if context == "heading" else ""))
                    original = ref.text[span[0]:span[1]]
                    if item.rule == slip_rule:
                        # Once per book, at its first place that maps to the
                        # text: keyed on the word as it stands in the verse,
                        # after the span is known, so markup earlier on the
                        # line cannot shift it (#246 review).
                        if original in slips_seen:
                            continue
                        slips_seen.add(original)
                    occurrences[(ref.chapter, ref.verse, id_rule, original)] += 1
                    suggestions = item.suggestions
                    message = rule.message + (f" — {item.why}" if item.why else "")
                    if context == "heading":
                        if suggestions:
                            message += f" (suggested: {suggestions[0]['text']})"
                        suggestions = []
                    finding = {
                        "id": finding_id(book, ref.chapter, ref.verse, id_rule, original,
                                         occurrences[(ref.chapter, ref.verse, id_rule, original)]),
                        "book": book, "chapter": ref.chapter, "verse": ref.verse, "rule": rule.name,
                        "severity": rule.severity, "start": span[0], "end": span[1], "originalText": original,
                        "message": message, "textHash": text_hash(ref.text),
                        "ruleVersion": pack.stamp(rule)[1], "status": "review-needed",
                        **rule_fields(rule.name, suggestions, pack=pack, pack_rule=rule),
                    }
                    if item.detail and item.detail != rule.name:
                        finding["detailRule"] = item.detail
                    if context != "verse":
                        finding["context"] = context
                    if context == "heading":
                        finding["contextText"] = ref.lifted.visible
                    if ov_table is not None:
                        reference = ov_reference.lookup(ov_table, book, ref.chapter, ref.verse)
                        if reference is not None:
                            finding["reference"] = reference
                    findings.append(finding)
            map_items.__exit__(None, None, None)
    if corpus_stats["accepted"]:
        notes.append(f"{corpus_stats['accepted']} word(s) outside the OV accepted from the general corpus "
                     f"({pack.name}).")
    if crossing:
        notes.append(f"{crossing} {pack.name} {crossing_note}")
    if unmapped:
        notes.append(f"{unmapped} {pack.name} finding(s) from a rule outside the pack's catalogue omitted.")
    return findings, notes


def state_digest(pack: RulePack) -> str:
    """For the panel and the benchmark: which IRV snapshot a pack runs on."""
    path = pack.directory / IRV_STATE if pack.directory else None
    if not path or not path.is_file():
        return "none"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
