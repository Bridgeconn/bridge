"""The one fragment reader (#91 Phase 1a): what a stored verse string shows.

The parity test at the bottom is what makes `usfm_verse` and `usfm_parser` one
parser in effect: the scanner's plain text must tokenise like usfmtc's own
reading of the same verse, for every stored verse of both IRV fixtures. The
USJ/USX walker it uses lives here, in the test, and nowhere in production.
"""
from __future__ import annotations

import pytest

from tc_ai_bridge.usfm_parser import _usfmtc_documents, parse_usfm
from tc_ai_bridge.usfm_verse import lift_verse, normalize_style_reopens, redundant_style_reopens


def _collapse(text: str) -> str:
    return " ".join(text.split())


# --- deletion-only contract -------------------------------------------------

def test_a_verse_without_markup_is_unchanged():
    raw = "அந்த காகம்  பறந்தது"
    lifted = lift_verse(raw)
    assert lifted.plain == raw
    assert lifted.raw_index == tuple(range(len(raw)))
    assert lifted.notes == () and lifted.styles == () and lifted.warnings == () and lifted.removed == ()


def test_plain_is_raw_minus_removed_ranges_for_every_fixture_verse(tamil_php_usfm, tamil_luk_usfm):
    for path in (tamil_php_usfm, tamil_luk_usfm):
        for verse in parse_usfm(path.read_text(encoding="utf-8-sig")).verses:
            lifted = lift_verse(verse.text)
            kept = set(range(len(verse.text)))
            for start, end in lifted.removed:
                kept -= set(range(start, end))
            assert lifted.raw_index == tuple(sorted(kept)), (verse.chapter, verse.verse)
            assert lifted.plain == "".join(verse.text[i] for i in lifted.raw_index)
            for i, raw_i in enumerate(lifted.raw_index):
                assert lifted.map_offset(raw_i) == i


# --- notes: the frontend's parseVerseNotes, now on the engine side ----------

def test_lifts_notes_with_the_frontend_swallow_rule():
    # Same table as usfmNotes.test.ts and test_language_qa.py's lift table.
    for raw, plain in [
        ("a \\f + \\ft n\\f* b", "a b"),
        ("a\\f + \\ft n\\f* b", "a b"),
        ("a \\f + \\ft n\\f*", "a "),
        ("a\\f + \\ft n\\f*", "a"),
        ("\\f + \\ft n\\f* b", "b"),
        ("a \\x - \\xo 1.1 \\xt Gen 1.1\\x* b", "a b"),
    ]:
        assert lift_verse(raw).plain == plain, raw


def test_note_shape_matches_the_frontend():
    raw = "Paul,\\f + \\fr 1.6 \\fq good work \\ft will finish it.\\f* a servant \\x - \\xo 1:1 \\xt Acts 16:12\\x* of God."
    lifted = lift_verse(raw)
    assert lifted.plain == "Paul, a servant of God."
    footnote, xref = lifted.notes
    assert footnote.kind == "footnote" and footnote.caller == "+" and footnote.reference == "1.6"
    assert footnote.parts == (("fr", "1.6"), ("fq", "good work"), ("ft", "will finish it."))
    assert footnote.text == "good work will finish it."
    assert footnote.position == len("Paul,")
    assert xref.kind == "xref" and xref.caller == "-" and xref.reference == "1:1"
    assert xref.text == "Acts 16:12"
    assert xref.position == len("Paul, a servant ")  # the swallowed space follows the note
    assert raw[footnote.raw_start:footnote.raw_end].startswith("\\f +")


def test_caller_defaults_to_plus_and_endnotes_are_footnotes():
    lifted = lift_verse("a \\fe \\ft endnote\\fe* b \\ef - \\ft extended\\ef* c")
    assert lifted.plain == "a b c"
    assert [n.kind for n in lifted.notes] == ["footnote", "footnote"]
    assert lifted.notes[0].caller == "+" and lifted.notes[1].caller == "-"
    assert lifted.warnings == ()


def test_an_unterminated_note_is_a_warning_not_a_swallowed_verse():
    lifted = lift_verse("அந்த \\ft காகம்")
    assert lifted.warnings and lifted.warnings[0].startswith("Footnote or cross-reference markup outside a complete")
    assert "காகம்" in lifted.plain  # best effort: the text is still there


# --- offsets ----------------------------------------------------------------

def test_offsets_after_a_note_land_on_the_same_word():
    raw = "இந்த \\f + \\ft குறிப்பு\\f* நற்கிரியையை"
    lifted = lift_verse(raw)
    start = raw.index("நற்கிரியையை")
    end = start + len("நற்கிரியையை")
    assert lifted.plain[lifted.map_offset(start):lifted.map_offset(end)] == "நற்கிரியையை"
    assert lifted.raw_span(lifted.map_offset(start), lifted.map_offset(end)) == (start, end)


def test_a_span_inside_a_note_collapses_to_zero_length():
    raw = "a \\f + \\ft inside\\f* b"
    lifted = lift_verse(raw)
    inside = raw.index("inside")
    assert lifted.map_offset(inside) == lifted.map_offset(inside + len("inside")) == 2
    assert lifted.map_offset(-5) == 0 and lifted.map_offset(len(raw) + 5) == len(lifted.plain)


def test_raw_span_refuses_a_range_that_crosses_markup():
    lifted = lift_verse("அந்த\n\\q காகம்")
    assert lifted.plain == "அந்த\nகாகம்"
    assert lifted.raw_span(0, 4) == (0, 4)
    assert lifted.raw_span(0, len(lifted.plain)) is None


# --- styles, attributes, milestones, non-Scripture content ------------------

def test_character_styles_are_removed_and_recorded():
    lifted = lift_verse("the \\nd Lord\\nd*, \\wj said \\+it so\\+it* to him\\wj*.")
    assert lifted.plain == "the Lord, said so to him."
    assert lifted.styles == (
        type(lifted.styles[0])("nd", 4, 8),
        type(lifted.styles[0])("wj", 10, 24),
        type(lifted.styles[0])("it", 15, 17),
    )
    assert lifted.plain[4:8] == "Lord" and lifted.plain[15:17] == "so"


def test_word_attributes_and_alignment_milestones_are_not_visible_text():
    assert lift_verse('\\w அந்த|lemma="x"\\w* காகம்').plain == "அந்த காகம்"
    lifted = lift_verse('அவன் \\zaln-s |x-strong="G1"\\*\\w வந்தான்|x-occurrence="1"\\w*\\zaln-e\\*.')
    assert lifted.plain == "அவன் வந்தான்."
    assert [s.marker for s in lifted.styles] == ["w"]
    assert lifted.warnings == ()


def test_non_scripture_character_content_is_dropped_with_its_content():
    lifted = lift_verse("\\va 2\\va* In the beginning \\fig Creation|src=\"c.png\" size=\"col\"\\fig* God \\rq Gen 1:1\\rq* made.")
    assert lifted.plain == "In the beginning God made."
    assert lifted.warnings == ()


def test_a_poetry_marker_inside_the_verse_keeps_its_line_break():
    lifted = lift_verse("யெகோவா என் மேய்ப்பராக இருக்கிறார்;\n\\q நான் தாழ்ச்சி அடையமாட்டேன்.\n\\q")
    assert lifted.plain == "யெகோவா என் மேய்ப்பராக இருக்கிறார்;\nநான் தாழ்ச்சி அடையமாட்டேன்.\n"


def test_paragraph_markers_are_recorded_where_their_content_starts():
    """#507: the reader draws each poetry line on its own line at its own
    indent from these, and never parses USFM for it."""
    lifted = lift_verse("Lord, how\n\\q2 many are they \\qs Selah\\qs*\n\\b\n\\q1")
    assert lifted.plain == "Lord, how\nmany are they Selah\n\n"
    assert [(p.marker, p.position) for p in lifted.paras] == [
        ("q2", len("Lord, how\n")),
        ("b", len("Lord, how\nmany are they Selah\n")),
        # Nothing follows it: this is the paragraph the next verse opens in.
        ("q1", len(lifted.plain)),
    ]
    assert lifted.plain[lifted.paras[0].position:].startswith("many are they")
    # A character style is not a paragraph, and neither is its closer.
    assert [(s.marker, lifted.plain[s.start:s.end]) for s in lifted.styles] == [("qs", "Selah")]


def test_a_descriptive_title_inside_a_verse_is_a_paragraph():
    lifted = lift_verse("a\n\\d A Psalm of David\n\\q1")
    assert [(p.marker, lifted.plain[p.position:].split("\n")[0]) for p in lifted.paras] == [
        ("d", "A Psalm of David"), ("q1", ""),
    ]


def test_a_verse_that_starts_with_a_paragraph_marker_has_it_at_zero():
    lifted = lift_verse("\\q1 Lord, how\n\\q2 many")
    assert [(p.marker, p.position) for p in lifted.paras] == [("q1", 0), ("q2", len("Lord, how\n"))]
    assert lifted.to_dict()["paras"] == [
        {"marker": "q1", "position": 0}, {"marker": "q2", "position": len("Lord, how\n")},
    ]


def test_warnings_are_total_not_refusals():
    unbalanced = lift_verse("\\wj Jesus said")
    assert unbalanced.warnings == ("Unbalanced \\wj: 1 open, 0 close",)
    assert unbalanced.plain == "Jesus said"
    stray = lift_verse("அந்த \\ காகம்")
    assert stray.warnings == ("Backslash that is not a USFM marker at code-point 5",)
    bar = lift_verse('a \\zsem-s |x-note="n"* b')
    assert any(w.startswith("Word attributes not closed by a USFM marker at code-point") for w in bar.warnings)


def test_to_dict_is_the_protocol_payload():
    payload = lift_verse("Paul,\\f + \\fr 1.6 \\ft note\\f* servant").to_dict()
    assert payload["plain"] == "Paul, servant"
    assert payload["notes"][0]["reference"] == "1.6" and payload["notes"][0]["position"] == 5
    assert payload["removed"] == [[5, 29]]
    assert payload["styles"] == [] and payload["warnings"] == [] and payload["paras"] == []


# --- redundant style reopen (#203) -------------------------------------------

def test_redundant_style_reopens_are_found_with_their_repair():
    raw = "\\wj And \\wj*\\wj there were many lepers\\wj*\\wj in Israel\\wj*"
    fixes = redundant_style_reopens(raw)
    assert [(f.marker, f.original, f.replacement) for f in fixes] == [
        ("wj", "\\wj*\\wj ", ""),    # after "And " -- a space is already there
        ("wj", "\\wj*\\wj ", " "),   # glued to "lepers" -- keep one space
    ]
    assert normalize_style_reopens(raw) == "\\wj And there were many lepers in Israel\\wj*"
    assert lift_verse(normalize_style_reopens(raw)).plain == "And there were many lepers in Israel"


def test_notes_and_aligned_words_back_to_back_are_not_redundant():
    # Two footnotes in a row are two notes; the KJV's `who\w*\w soever` is one
    # word on purpose, and the spec reading "whosoever" is the right one.
    for raw in [
        "a\\f + \\ft one\\f*\\f + \\ft two\\f* b",
        "\\x - \\xo 1:1 \\xt Gen 1\\x*\\x - \\xo 1:1 \\xt Gen 2\\x*",
        '\\w who|strong="G3739"\\w*\\w soever|strong="G1437"\\w*',
        "\\+w who\\+w*\\+w soever\\+w*",
    ]:
        assert redundant_style_reopens(raw) == (), raw
        assert normalize_style_reopens(raw) == raw
    assert lift_verse('\\w who|strong="G3739"\\w*\\w soever|strong="G1437"\\w*').plain == "whosoever"


def test_nested_style_reopen_is_matched_as_a_pair():
    raw = "\\wj He said \\+nd Lord\\+nd*\\+nd God\\+nd* to them\\wj*"
    [fix] = redundant_style_reopens(raw)
    assert fix.marker == "nd" and fix.replacement == " "
    assert normalize_style_reopens(raw) == "\\wj He said \\+nd Lord God\\+nd* to them\\wj*"


# --- the parity test: this scanner against usfmtc ----------------------------

_USX_SKIP_TAGS = frozenset({"note", "figure", "book", "chapter", "verse", "ms"})
_USX_SKIP_CHAR_STYLES = frozenset({"va", "vp", "ca", "cp", "rq"})


def _usx_plain(verse_text: str) -> str:
    """usfmtc's own reading of one stored verse string, as plain text. Lives in
    the test on purpose: production has exactly one fragment reader."""
    roots, _errors = _usfmtc_documents(f"\\id TST\n\\c 1\n\\v 1 {verse_text}\n")

    def skipped(element) -> bool:
        return element.tag in _USX_SKIP_TAGS or (
            element.tag == "char" and (element.get("style") or "") in _USX_SKIP_CHAR_STYLES
        )

    def text_of(element) -> str:
        # Inline children's tails are the parent's text; a skipped child keeps
        # only its tail.
        text = element.text or ""
        for child in element:
            text += ("" if skipped(child) else text_of(child)) + (child.tail or "")
        return text

    # Each paragraph (`\q2` inside a verse becomes its own para element) is a
    # line of its own; a verse milestone at root level carries its text as tail.
    paragraphs: list[str] = []
    for root in roots:
        for element in root:
            if element.tag in {"book", "chapter"}:
                continue
            paragraphs.append(element.tail or "" if element.tag == "verse" else text_of(element))
    return "\n".join(paragraphs)


@pytest.mark.parametrize("fixture_name", ["tamil_php_usfm", "tamil_luk_usfm"])
def test_plain_text_agrees_with_usfmtc_on_every_fixture_verse(fixture_name, request):
    path = request.getfixturevalue(fixture_name)
    parsed = parse_usfm(path.read_text(encoding="utf-8-sig"))
    disagreements = []
    for verse in parsed.verses:
        ours = _collapse(lift_verse(verse.text).plain)
        theirs = _collapse(_usx_plain(verse.text))
        if ours != theirs:
            disagreements.append((verse.chapter, verse.verse, ours[-60:], theirs[-60:]))
    assert disagreements == [], f"{len(disagreements)} of {len(parsed.verses)} verses: {disagreements[:5]}"


def _usx_paragraph_styles(verse_text: str) -> list[str]:
    """The paragraphs usfmtc finds inside one stored verse string, by style.
    The first is the paragraph usfmtc opens for a `\\v` that follows `\\c`
    directly; it is not in the source."""
    roots, _errors = _usfmtc_documents(f"\\id TST\n\\c 1\n\\v 1 {verse_text}\n")
    styles = [
        str(element.get("style") or "")
        for root in roots for element in root.iter() if element.tag == "para"
    ]
    return styles[1:]


@pytest.mark.parametrize("fixture_name", ["tamil_php_usfm", "tamil_luk_usfm"])
def test_paragraph_markers_agree_with_usfmtc_on_every_fixture_verse(fixture_name, request):
    """#507: the same binding as the plain-text parity above, for `paras`."""
    path = request.getfixturevalue(fixture_name)
    parsed = parse_usfm(path.read_text(encoding="utf-8-sig"))
    disagreements = []
    with_paragraphs = 0
    for verse in parsed.verses:
        ours = [para.marker for para in lift_verse(verse.text).paras]
        theirs = _usx_paragraph_styles(verse.text)
        with_paragraphs += bool(ours)
        if ours != theirs:
            disagreements.append((verse.chapter, verse.verse, ours, theirs))
    assert disagreements == [], f"{len(disagreements)} of {len(parsed.verses)} verses: {disagreements[:5]}"
    if fixture_name == "tamil_luk_usfm":
        # 50 of Luke's verses carry a paragraph marker (quoted poetry, paragraph
        # breaks), so the comparison above is not vacuous.
        assert with_paragraphs == 50


def test_paragraph_edge_table_agrees_with_usfmtc():
    for raw in [
        "line one\n\\q2 line two\n\\q1",
        "a\n\\d A Psalm of David\n\\q1",
        "Many say\n\\b\n\\q1 again \\qs Selah\\qs*",
        "one\n\\li1 first\n\\li2 second\n\\p",
        "prose\n\\pi indented\n\\m back \\nd Lord\\nd*",
        "the \\nd Lord\\nd*, \\wj said \\+it so\\+it* to him\\wj*.",
    ]:
        assert [para.marker for para in lift_verse(raw).paras] == _usx_paragraph_styles(raw), raw


def test_edge_table_agrees_with_usfmtc():
    for raw in [
        "the \\nd Lord\\nd*, \\wj said \\+it so\\+it* to him\\wj*.",
        '\\w அந்த|lemma="x"\\w* காகம்',
        'அவன் \\zaln-s |x-strong="G1"\\*\\w வந்தான்|x-occurrence="1"\\w*\\zaln-e\\*.',
        "a \\f + \\fr 1.1 \\ft note\\f* b \\x - \\xo 1.1 \\xt Gen 1.1\\x* c",
        "a \\fe + \\ft endnote\\fe* b",
        "\\va 2\\va* In the beginning",
        "quoted \\qt-s |who=\"Pilate\"\\*words\\qt-e\\* here",
        "line one\n\\q2 line two",
        "a \\rb base|gloss\\rb* b",
    ]:
        assert _collapse(lift_verse(raw).plain) == _collapse(_usx_plain(raw)), raw
