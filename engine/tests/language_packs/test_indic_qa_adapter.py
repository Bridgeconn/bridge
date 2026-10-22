"""The indic-qa adapter's own logic, without the shipped dictionaries:
the snapshot codec, run splitting, synthetic books and the rule catalogue."""
from collections import Counter
from types import SimpleNamespace

import pytest

from tc_ai_bridge.language_packs import PackError, indic_qa_adapter as adapter
from tc_ai_bridge.language_qa import MAX_VERSE_CHARS, lift_inline_usfm


def test_the_snapshot_codec_keeps_every_type_the_checker_relies_on():
    state = {"irv_canon": Counter({"क": 3, "ख": 1}),
             "join_split": Counter({("उस", "ने"): 2}),
             "book_state": {"GEN": {"irv_canon": Counter({"क": 2}), "abbr": Counter()}},
             "names": {"a", "b"}, "pair": ("x", 1), "plain": [1, "two"]}
    back = adapter.decode_state(adapter.encode_state(state))
    assert back == state
    assert type(back["irv_canon"]) is Counter and type(back["book_state"]["GEN"]["irv_canon"]) is Counter
    assert list(back["join_split"]) == [("उस", "ने")]
    assert isinstance(back["names"], set) and back["pair"] == ("x", 1)


def test_the_snapshot_encoding_is_deterministic():
    one = Counter({"b": 1, "a": 2, ("x", "y"): 3})
    two = Counter({("x", "y"): 3, "a": 2, "b": 1})
    assert adapter.encode_state(one) == adapter.encode_state(two)


def _ordered(value):
    """A value with every dict's insertion order and every type made visible."""
    if isinstance(value, dict):
        return (type(value).__name__, [(_ordered(k), _ordered(v)) for k, v in value.items()])
    if isinstance(value, (set, frozenset)):
        return (type(value).__name__, sorted(map(repr, value)))
    if isinstance(value, (list, tuple)):
        return (type(value).__name__, [_ordered(v) for v in value])
    return (type(value).__name__, value)


def _big_state():
    """Every shape a real snapshot has: book -> Counter, tuple keys, nested
    dicts, tuples holding Counters (pa), a set, and containers larger than a
    piece; entries out of sorted order, so order is tested too."""
    n = adapter.STATE_PIECE * 2 + 7
    return {
        "bookCount": {f"b{i}": Counter({f"w{j}": j + 1 for j in range(n if i == 1 else 3, 0, -1)}) for i in (2, 1)},
        "data": {"irv_canon": Counter({f"k{j}": j for j in range(n, 0, -1)}),
                 "join_split": Counter({("उस", f"ने{j}"): j for j in range(5)}),
                 "book_state": {"gen": {"abbr": Counter(), "q": (Counter({"x": 1}), Counter())}},
                 "quotes_book": {"gen": (1, 2)}, "names": {"a", ("b", 1)}, "empty": {}},
        "bookPairs": {"gen": Counter({("க", "k", 1): 2, ("ச", "c", 0): 1})},
        "bookFormUse": {"gen": Counter({("வா", 0): 3})},
    }


def _format_1(path, fields, provenance):
    import gzip
    import json
    raw = {"format": 1, **{k: adapter.encode_state(v) for k, v in fields.items()}, "provenance": provenance}
    path.write_bytes(gzip.compress(json.dumps(raw, ensure_ascii=False, separators=(",", ":"),
                                              sort_keys=True).encode("utf-8"), 9, mtime=0))


def test_the_format_2_snapshot_restores_what_format_1_did_in_the_same_order(tmp_path):
    import gzip
    fields, provenance = _big_state(), {"books": 2, "dictionary": {"wordlist.txt": "x"}}
    old, new = tmp_path / "old.json.gz", tmp_path / "new.json.gz"
    _format_1(old, fields, provenance)
    encoded = {k: adapter.encode_state(v) for k, v in fields.items()}
    new.write_bytes(gzip.compress(adapter.encode_state_file(encoded, provenance), 9, mtime=0))
    from_old, prov_old = adapter.read_state(old)  # format 1 is still read
    from_new, prov_new = adapter.read_state(new)
    assert prov_old == prov_new == provenance
    assert set(from_old) == set(from_new) == set(fields)
    for key in fields:
        assert _ordered(from_new[key]) == _ordered(from_old[key])
    lines = gzip.decompress(new.read_bytes()).decode("utf-8").splitlines()
    assert lines[0].startswith('{"format":2,')
    import json
    assert max(len(json.loads(line)[1]) for line in lines[1:]) <= adapter.STATE_PIECE


def test_write_state_writes_format_2_deterministically(tmp_path):
    fields = _big_state()
    checker = SimpleNamespace(book_count=fields["bookCount"], data=fields["data"],
                              book_pairs=fields["bookPairs"], book_form_use=fields["bookFormUse"],
                              lang=SimpleNamespace(sandhi=True))
    one, two = tmp_path / "1.gz", tmp_path / "2.gz"
    adapter.write_state(one, checker, {"books": 2})
    adapter.write_state(two, checker, {"books": 2})
    assert one.read_bytes() == two.read_bytes()
    restored = SimpleNamespace()
    assert adapter.restore_state(restored, one) == {"books": 2}
    assert _ordered(restored.book_count) == _ordered(adapter.decode_state(adapter.encode_state(fields["bookCount"])))
    assert restored.irv_count["w1"] == 4 and restored.irv_pairs[("க", "k")] == [2, 0]


def test_a_cached_restore_is_an_independent_copy_of_the_file_restore(tmp_path):
    """_restore_cached's piecewise pickle gives what the file gave, in the
    same order, sharing nothing with the copy before it."""
    path = tmp_path / adapter.IRV_STATE
    fields = _big_state()
    checker = SimpleNamespace(book_count=fields["bookCount"], data=fields["data"],
                              book_pairs=fields["bookPairs"], book_form_use=fields["bookFormUse"],
                              lang=SimpleNamespace(sandhi=True))
    adapter.write_state(path, checker, {"books": 2})
    adapter._STATE_CACHE.clear()
    first, second = SimpleNamespace(), SimpleNamespace()
    assert adapter._restore_cached(first, path) == {"books": 2}
    expected = {f: _ordered(getattr(first, f)) for f in adapter._STATE_FIELDS}
    first.book_count["b1"]["w1"] += 100  # a pass mutates its checker
    first.irv_pairs[("க", "k")][1] += 100
    assert adapter._restore_cached(second, path) == {"books": 2}
    assert {f: _ordered(getattr(second, f)) for f in adapter._STATE_FIELDS} == expected
    assert second.book_count["b1"] is not first.book_count["b1"]
    adapter._STATE_CACHE.clear()


def test_a_run_ends_where_lifted_markup_was():
    text = "पहला शब्द\\f + \\ft टिप्पणी\\f* दूसरा"
    lifted, _ = lift_inline_usfm(text)
    runs = adapter._runs(lifted, 0, len(lifted.visible))
    assert len(runs) == 2
    first, second = (lifted.visible[a:b] for a, b in runs)
    assert first == "पहला शब्द"
    for a, b in runs:  # each run is one contiguous piece of the raw verse
        assert adapter.LineRef("1", "1", text, lifted, 0).lifted.raw_span(a, b) is not None
    assert second.strip() == "दूसरा"


def _book(chapters):
    return adapter.build_book("GEN", chapters, lift=lift_inline_usfm, max_verse_chars=MAX_VERSE_CHARS)


def test_a_poetry_verse_becomes_one_line_per_physical_line():
    book, refs, _ = _book({"1": {"1": "पहली पंक्ति\n\\q दूसरी पंक्ति", "2": "तीसरा"}})
    verse_lines = [line for line in book.lines if line.style != "c"]
    assert [line.raw for line in verse_lines] == ["पहली पंक्ति", "दूसरी पंक्ति", "तीसरा"]
    assert [line.style for line in verse_lines] == ["v", "q", "v"]
    # The second line starts after the first line's text and its "\n".
    second = next(i for i, line in enumerate(book.lines) if line.raw == "दूसरी पंक्ति")
    assert refs[second].base == len("पहली पंक्ति") + 1
    assert "\n" not in "".join(line.raw for line in book.lines)


def test_chapters_get_a_chapter_line_and_their_own_span():
    book, refs, _ = _book({"1": {"1": "क"}, "3": {"1": "ग"}})
    assert book.lines[0].style == "c" and book.lines[0].chapter == 1
    assert len(book.chapters) == 4  # 0 (front matter), 1, 2 (missing: empty), 3
    lo, hi = book.chapters[2]
    assert hi < lo
    lo, hi = book.chapters[3]
    assert [line.raw for line in book.lines[lo:hi + 1]] == ["", "ग"]


def test_verse_bridges_and_segments_keep_their_key():
    book, refs, _ = _book({"1": {"3-4": "क", "5a": "ख"}})
    lines = {refs[i].verse: book.lines[i] for i in refs}
    assert (lines["3-4"].verse, lines["3-4"].verse_end) == (3, 4)
    assert (lines["5a"].verse, lines["5a"].verse_end) == (5, None)


def test_a_verse_that_cannot_be_lifted_is_left_out():
    book, refs, _ = _book({"1": {"1": "क \\f + \\ft खुला", "2": "ख"}})
    assert [refs[i].verse for i in sorted(refs)] == ["2"]


@pytest.mark.parametrize("group", ["Encoding", "Shape", "Punctuation", "Lexicon", "Consistency", "Grammar", "Style"])
def test_a_default_entry_is_never_inline_and_never_blocks_export(group):
    entry = adapter.default_entry("hi.lex.known-misspelling", group, True)
    assert entry["inline"] is False
    assert (entry["severity"], entry["confidence"]) != ("high", "high")
    assert entry["category"] in adapter.CATEGORIES and entry["layer"] in adapter.LAYERS


def test_unknown_default_entry_is_low_confidence_and_follows_upstream():
    """DECISIONS 2026-10-08: an unknown word is drawn as the web app draws it,
    at the lowest severity and confidence, never inline (the human gate)."""
    on = adapter.default_entry("ml.lex.unknown", "Lexicon", True)
    assert (on["enabled"], on["inline"], on["severity"], on["confidence"]) == (True, False, "low", "low")
    assert adapter.default_entry("hi.lex.unknown", "Lexicon", False)["enabled"] is False, "upstream decides"


def _profile(rules):
    return SimpleNamespace(RULES=rules, __name__="qa_app.langs.hi")


def test_rule_versions_must_list_exactly_the_profile_rules():
    profile = _profile({"hi.a": ("Lexicon", "A", False, True), "hi.b": ("Shape", "B", True, True)})
    entry = adapter.default_entry("hi.a", "Lexicon", True)
    with pytest.raises(PackError, match="missing \\['hi.b'\\]"):
        adapter._rules(profile, {"hi.a": entry}, "hi-irv")
    with pytest.raises(PackError, match="unknown \\['hi.c'\\]"):
        adapter._rules(profile, {"hi.a": entry, "hi.b": entry, "hi.c": entry}, "hi-irv")


def test_a_high_high_entry_is_refused():
    profile = _profile({"hi.a": ("Lexicon", "A", False, True)})
    entry = {**adapter.default_entry("hi.a", "Lexicon", True), "severity": "high", "confidence": "high"}
    with pytest.raises(PackError, match="blocks export"):
        adapter._rules(profile, {"hi.a": entry}, "hi-irv")


def test_catalogue_rules_never_run_in_the_verse_scan():
    profile = _profile({"hi.a": ("Lexicon", "A", False, True)})
    [rule] = adapter._rules(profile, {"hi.a": adapter.default_entry("hi.a", "Lexicon", True)}, "hi-irv")
    assert (rule.match_type, rule.stage) == ("indic-qa", "book")
    assert rule.message == "A" and rule.version == 1
