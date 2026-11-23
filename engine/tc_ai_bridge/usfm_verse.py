"""The one fragment reader: what a stored verse string shows (#91, Phase 1a).

`usfm_parser.parse_usfm` decides where a verse starts and ends in a whole book.
This module answers the other question every per-verse consumer asks of the
stored string it produced: *which of these code points are Scripture a reader
sees*, which are notes, which are markup, and where does each visible character
come from. The reader display, Language QA, the checks' tokeniser, the names
check's offsets and the aligned exporter all need the same answer, and until
this module they each had a regex of their own.

Design, and why it is not usfmtc:

- usfmtc reports positions for *elements* (paragraphs, verses, notes) but not
  for text nodes, and these readers run on hot paths -- every chapter open,
  every `alignment.get`, every save, every check -- thousands of times per
  book. So this is Bridge's own scanner, grown from `language_qa.lift_inline_usfm`
  and the frontend's `parseVerseNotes`, and it is bound to usfmtc by a parity
  test: for every stored verse of both IRV fixtures, `lift_verse(s).plain`
  tokenises identically to the plain text walked out of usfmtc's own parse of
  that verse (`tests/project_io/test_usfm_verse.py`). The USJ walker lives in
  the test, never here.
- **Deletion only.** `plain` is `raw` with ranges removed, never rewritten or
  reordered, so `raw_index`/`map_offset` are exact and a span of plain text
  that crosses no removed range is byte-identical to the raw span it maps to.
  That is what lets a finding computed on the raw stored string land on the
  right displayed word, and a fix made on the display be written back.
- **Total.** It never refuses a verse: the best-effort `plain` is always
  returned, and anything the markup got wrong is in `warnings`. Language QA
  keeps declining to scan a verse with warnings; the reader cannot decline to
  show one.

Marker classes -- the one list the parity test guards:

- **Notes**, removed with their content and recorded in `notes`: `\\f`, `\\fe`,
  `\\ef` (footnote kinds) and `\\x`, `\\ex` (cross-reference kinds), each from
  its opener to its own closer. One adjacent space goes with the note (the
  frontend's swallow rule, pinned by `test_language_qa.py`'s lift table).
- **Non-Scripture character content**, removed with its content: alternate
  chapter/verse numbers `\\va`, `\\vp`, `\\ca`, `\\cp`, figures `\\fig`, and an
  inline quotation reference `\\rq`. None of it is a translation of any word.
- **Attributes**: the `|…` of `\\w word|lemma="…"\\w*` and of a milestone such
  as `\\zaln-s |x-strong="…"\\*`, up to the closing marker.
- **Every other marker token**: character styles (`\\nd`, `\\wj`, `\\it`, nested
  `\\+nd` …) and their closers, `\\w`/`\\w*`, milestones and their bare `\\*`,
  and the paragraph/poetry markers chapter JSON keeps inside a verse
  (`…;\\n\\q2 …`). The marker goes, its content stays; an opener's one following
  space is marker syntax and goes with it, a closer's is text. A character
  style that opens and closes is recorded in `styles` so a reader can render
  it; the line break before a `\\q2` stays, as whitespace.
- **Paragraph markers** (`PARAGRAPH_MARKERS`: `\\p`, `\\q1`, `\\q2`, `\\d`, `\\b`
  …) are removed like any other marker token, and each is also recorded in
  `paras` with the place in `plain` where its content starts (#507). That is
  what lets the reader draw a poetry line on its own line at its own indent
  without parsing anything. A marker with nothing after it is recorded too:
  the `\\q1` a stored verse ends with is the paragraph the NEXT verse opens in.
"""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from typing import Any

# The tokeniser's boundary rule, shared by every consumer that produces or
# locates tC `word/occurrence/occurrences` tokens (#91 Phase 1b). Split on
# whitespace only -- Tamil and Hebrew combining marks must stay attached --
# then trim ordinary punctuation from both ends of each token.
WHITESPACE_TOKEN_TRIM_CHARS = ' \t\r\n.,;:!?“”‘’"\'()[]{}<>—–…।॥'

# Paired markers whose open/close counts are checked. The messages are pinned
# by Language QA's tests, so the text here is a contract.
PAIRED_MARKERS = ('f', 'x', 'add', 'nd', 'wj', 'qt', 'k', 'bd', 'it', 'em')


def unbalanced_markers(text: str) -> list[tuple[str, int, int]]:
    """Each paired marker whose opens and closes differ: (marker, opens, closes)."""
    found: list[tuple[str, int, int]] = []
    for marker in PAIRED_MARKERS:
        opens = len(re.findall(rf'\\{re.escape(marker)}(?:\s|\+)', text))
        closes = len(re.findall(rf'\\{re.escape(marker)}\*', text))
        if opens != closes:
            found.append((marker, opens, closes))
    return found


def balance_message(marker: str, opens: int, closes: int) -> str:
    return f'Unbalanced \\{marker}: {opens} open, {closes} close'


def marker_balance_issues(text: str) -> list[str]:
    return [balance_message(*found) for found in unbalanced_markers(text)]


def plain_text(raw: str) -> str:
    """The verse's visible text with whitespace collapsed to single spaces --
    what checks, tN/tW selection counting and AI prompts read. Whitespace is
    collapsed on purpose: `usfm.strip_usfm` always did, and callers count
    selections against it (`tc_project._normalize_check_selections`)."""
    return " ".join(lift_verse(raw).plain.split())


def marker_names(raw: str) -> tuple[str, ...]:
    """Every USFM marker token in `raw`, in order, by name: `\\f`, `\\ft`,
    `\\f*`, `\\nd`, `\\nd*` give ("f", "ft", "f", "nd", "nd"). Notes are not
    skipped and closers are listed like openers, because the caller
    (`passage_semantic_runtime`'s structure markers, #91 Phase 3c) records
    where markup *occurs*, not what it shows. A nested `\\+nd` is "nd"; a
    milestone's bare `\\*` is not a marker and is left out."""
    return tuple(
        match.group(2) for match in _MARKER.finditer(raw) if match.group(2) is not None
    )


def tokens(raw: str) -> list[str]:
    """Whitespace tokens of the visible text, punctuation trimmed from both
    ends, empties dropped -- the tC word inventory of a verse."""
    out: list[str] = []
    for word in lift_verse(raw).plain.split():
        token = word.strip(WHITESPACE_TOKEN_TRIM_CHARS)
        if token:
            out.append(token)
    return out


# Notes: opener, one whitespace char, body, the same marker's closer.
_NOTE = re.compile(r"\\(fe|ef|ex|f|x)\s.*?\\\1\*", re.DOTALL)
_FOOTNOTE_KINDS = frozenset({"f", "fe", "ef"})
# A note-family marker anywhere outside a complete note is a problem, not text.
_NOTE_FAMILY = re.compile(r"\\(?!fig\b)[fx][A-Za-z]*\b")
# Character content that is not Scripture: alternate numbering, figures, an
# inline quotation reference. Removed with its content.
_NON_SCRIPTURE = re.compile(r"\\(va|vp|ca|cp|fig|rq)\s.*?\\\1\*", re.DOTALL)
# USFM 3 attributes: the bar up to the closing marker is not visible text.
_ATTRIBUTES = re.compile(r"\|[^\\]*(?=\\(?:\+?[A-Za-z0-9_-]+)?\*)")
# Any other marker token. Groups: 1 nesting plus, 2 name, 3 closer star,
# 4 a milestone's bare star, 5 one following space.
_MARKER = re.compile(r"\\(?:(\+?)([A-Za-z0-9_-]+)(\*)?|(\*))( )?")
# Inside a note body: `\fr 1.6 \fq quoted \ft body` into (marker, text) pairs.
_NOTE_PART = re.compile(r"\\([A-Za-z0-9+_-]+)\*?\s*(.*?)(?=\\[A-Za-z0-9+_-]+\*?|$)", re.DOTALL)
_FIRST_INNER_MARKER = re.compile(r"\\[A-Za-z0-9]")


@dataclass(frozen=True)
class VerseNote:
    kind: str                       # "footnote" or "xref"
    caller: str                     # the glyph after \f / \x, usually "+"
    reference: str                  # \fr (footnote) or \xo (xref) text, or ""
    parts: tuple[tuple[str, str], ...]  # (marker without backslash, text), in order
    text: str                       # everything but the reference, flattened
    position: int                   # index into `plain` where the note sat
    raw_start: int                  # the removed raw range, swallow rule applied
    raw_end: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "caller": self.caller, "reference": self.reference,
            "parts": [{"marker": marker, "text": text} for marker, text in self.parts],
            "text": self.text, "position": self.position,
        }


@dataclass(frozen=True)
class StyleSpan:
    marker: str   # without backslash or nesting plus: "nd", "wj", "it", "w" ...
    start: int    # into `plain`, code points
    end: int

    def to_dict(self) -> dict[str, Any]:
        return {"marker": self.marker, "start": self.start, "end": self.end}


@dataclass(frozen=True)
class ParaMark:
    marker: str    # without backslash: "q1", "q2", "p", "d", "b" ...
    position: int  # into `plain`, code points: where this paragraph's content starts
    raw_start: int = 0  # the marker token in the raw string: its backslash ...
    raw_end: int = 0    # ... to the end of its one following space, when it has one

    def to_dict(self) -> dict[str, Any]:
        return {"marker": self.marker, "position": self.position}


@dataclass(frozen=True)
class LiftedVerse:
    raw: str
    plain: str
    raw_index: tuple[int, ...]            # raw_index[i] is the raw offset of plain[i]
    notes: tuple[VerseNote, ...] = ()
    styles: tuple[StyleSpan, ...] = ()
    warnings: tuple[str, ...] = ()
    removed: tuple[tuple[int, int], ...] = field(default=())  # raw ranges, merged
    paras: tuple[ParaMark, ...] = ()      # paragraph markers inside the verse, in order

    def map_offset(self, raw_offset: int) -> int:
        """Where a raw offset lands in `plain`. An offset inside a removed range
        collapses to the position the removal left behind, so a span that lived
        entirely inside a note maps to a zero-length range."""
        if raw_offset <= 0:
            return 0
        if raw_offset >= len(self.raw):
            return len(self.plain)
        return bisect.bisect_left(self.raw_index, raw_offset)

    def raw_span(self, start: int, end: int) -> tuple[int, int] | None:
        """Raw half-open span for plain[start:end], or None when that span
        crosses removed markup (it would not be one contiguous piece of raw text)."""
        if not 0 <= start < end <= len(self.plain):
            return None
        raw_start, raw_end = self.raw_index[start], self.raw_index[end - 1] + 1
        return (raw_start, raw_end) if raw_end - raw_start == end - start else None

    def removed_range_containing(self, raw_offset: int) -> tuple[int, int] | None:
        """The removed raw range `raw_offset` falls strictly inside, or None.

        An offset at either edge of a removed range sits between markup and
        text, so inserting there leaves every marker whole; one strictly inside
        would split a marker, its attributes or a note (#314)."""
        for start, end in self.removed:
            if start >= raw_offset:
                break
            if raw_offset < end:
                return (start, end)
        return None

    def insertion_points(self) -> tuple[int, ...]:
        """Raw offsets where an inserted word lands between words (#314).

        The start of the verse, and the end of each whitespace-delimited word of
        `plain` -- taken *after* any markup between that word and the next
        whitespace (its closing markers, attributes, an attached note), so an
        insertion never lands inside a `\\w … \\w*` word or before a note's
        anchor word. None of these is strictly inside a removed range."""
        points = {0}
        plain = self.plain
        for index in range(1, len(plain) + 1):
            if plain[index - 1].isspace():
                continue
            if index == len(plain):
                points.add(len(self.raw))
            elif plain[index].isspace():
                points.add(self.raw_index[index])
        return tuple(sorted(points))

    def to_dict(self) -> dict[str, Any]:
        """The display payload the protocol carries (#91 Phase 2). Offsets are
        code points, as every engine finding's are."""
        return {
            "plain": self.plain,
            "notes": [note.to_dict() for note in self.notes],
            "removed": [[start, end] for start, end in self.removed],
            "styles": [span.to_dict() for span in self.styles],
            "warnings": list(self.warnings),
            "paras": [para.to_dict() for para in self.paras],
        }


# Character-style markers whose close-then-reopen with nothing between is
# never meant: `\wj And \wj*\wj there` is one run of red letters, and the
# space inside the reopened marker is syntax, so a faithful reader (this one,
# usfmtc) glues the words. Notes are not here (`\f*\f ` is two notes) and
# neither is `\w` (the KJV's `who\w*\w soever` is one word on purpose). #203.
STYLE_MARKERS = frozenset({
    "add", "bd", "bdit", "bk", "dc", "em", "it", "k", "lit", "nd", "no", "ord", "pn",
    "png", "qac", "qs", "qt", "rq", "sc", "sig", "sls", "sup", "tl", "wj",
})
_STYLE_REOPEN = re.compile(r"\\(?P<plus>\+?)(?P<marker>[A-Za-z]+)\*\\(?P=plus)(?P=marker) ")

# Paragraph-level markers that chapter JSON keeps inside a verse (USFM 3.0
# paragraphs, poetry, lists, table rows, and the descriptive title `\d`). Each
# starts a new block of the verse; `lift_verse` records where (#507). Section
# headings are not here: the parser cuts them out of verse text (#180).
PARAGRAPH_MARKERS = frozenset({
    "p", "m", "po", "pr", "cls", "pmo", "pm", "pmc", "pmr", "mi", "nb", "pc", "b",
    "pi", "pi1", "pi2", "pi3", "ph", "ph1", "ph2", "ph3",
    "q", "q1", "q2", "q3", "q4", "qr", "qc", "qa", "qd",
    "qm", "qm1", "qm2", "qm3",
    "d", "lh", "lf", "li", "li1", "li2", "li3", "li4",
    "lim", "lim1", "lim2", "lim3", "lim4", "tr",
})


@dataclass(frozen=True)
class MarkupFix:
    """One mechanical repair of the raw string: replace raw[start:end] with
    `replacement`. `original` is raw[start:end], so a stale fix is detectable."""
    marker: str
    start: int
    end: int
    original: str
    replacement: str


def redundant_style_reopens(raw: str) -> tuple[MarkupFix, ...]:
    """Every `\\X*\\X ` pair for a character-style X, with the repair: drop the
    pair, keeping one space when it is glued to the previous word (so
    `lepers\\wj*\\wj in` becomes `lepers in`, and `And \\wj*\\wj there` becomes
    `And there`)."""
    fixes = []
    for match in _STYLE_REOPEN.finditer(raw):
        marker = match.group("marker")
        if marker not in STYLE_MARKERS:
            continue
        start, end = match.span()
        glued = start > 0 and not raw[start - 1].isspace()
        fixes.append(MarkupFix(marker, start, end, raw[start:end], " " if glued else ""))
    return tuple(fixes)


def normalize_style_reopens(raw: str) -> str:
    """`raw` with every redundant style reopen repaired (see above)."""
    out: list[str] = []
    cursor = 0
    for fix in redundant_style_reopens(raw):
        out.append(raw[cursor:fix.start])
        out.append(fix.replacement)
        cursor = fix.end
    out.append(raw[cursor:])
    return "".join(out)


def _note(raw: str, match: re.Match[str], position: int, raw_start: int, raw_end: int) -> VerseNote:
    marker = match.group(1)
    kind = "footnote" if marker in _FOOTNOTE_KINDS else "xref"
    # Body sits between the opener (`\f` + one whitespace char) and the closer.
    body = raw[match.start() + len(marker) + 2:match.end() - len(marker) - 2].strip()
    first = _FIRST_INNER_MARKER.search(body)
    caller = (body if first is None else body[:first.start()]).strip() or "+"
    rest = "" if first is None else body[first.start():]
    parts = tuple(
        (part.group(1), part.group(2).strip())
        for part in _NOTE_PART.finditer(rest)
        if part.group(2).strip()
    )
    reference_marker = "fr" if kind == "footnote" else "xo"
    reference = next((text for name, text in parts if name == reference_marker), "")
    text = " ".join(text for name, text in parts if name != reference_marker).strip()
    return VerseNote(kind, caller, reference, parts, text, position, raw_start, raw_end)


def lift_verse(raw: str) -> LiftedVerse:
    """What the stored verse string shows, and where each visible code point
    came from. See the module docstring for the marker classes."""
    removed = bytearray(len(raw))

    def remove(start: int, end: int) -> None:
        removed[start:end] = b"\x01" * (end - start)

    warnings: list[str] = list(marker_balance_issues(raw))

    def swallow_one_space(start: int, end: int) -> tuple[int, int]:
        # Removing content between two spaces would leave a double space
        # behind. Swallow exactly one, and nothing else (the frontend's rule).
        if start == 0 or raw[start - 1].isspace():
            if end < len(raw) and raw[end].isspace():
                end += 1
        elif end == len(raw) and raw[start - 1].isspace():
            start -= 1
        return start, end

    note_matches: list[tuple[re.Match[str], int, int]] = []
    for match in _NOTE.finditer(raw):
        start, end = swallow_one_space(*match.span())
        remove(start, end)
        note_matches.append((match, start, end))
    for match in _NOTE_FAMILY.finditer(raw):
        if not removed[match.start()]:
            warnings.append(
                "Footnote or cross-reference markup outside a complete "
                "\\f … \\f* or \\x … \\x* note"
            )
            break
    for match in _NON_SCRIPTURE.finditer(raw):
        if not removed[match.start()]:
            remove(*swallow_one_space(*match.span()))
    for match in _ATTRIBUTES.finditer(raw):
        if not removed[match.start()]:
            remove(*match.span())

    # (name, raw offset of the opener) for character styles still open.
    open_styles: list[tuple[str, int]] = []
    style_ranges: list[tuple[str, int, int]] = []  # name, raw open, raw close
    para_starts: list[tuple[str, int, int]] = []   # name, raw start of the token, raw end
    for match in _MARKER.finditer(raw):
        if removed[match.start()]:
            continue
        end = match.end()
        closer = bool(match.group(3) or match.group(4))
        if match.group(5) and closer:
            end -= 1  # the space after a closer is text, not marker syntax
        remove(match.start(), end)
        name = match.group(2)
        if name is None:
            continue
        if not closer and not match.group(1) and name in PARAGRAPH_MARKERS:
            # A paragraph never closes, so it is not an open character style.
            para_starts.append((name, match.start(), end))
            continue
        if match.group(3):
            for index in range(len(open_styles) - 1, -1, -1):
                if open_styles[index][0] == name:
                    _, opened_at = open_styles.pop(index)
                    style_ranges.append((name, opened_at, match.start()))
                    break
        else:
            open_styles.append((name, end))

    raw_index = tuple(i for i in range(len(raw)) if not removed[i])
    plain = "".join(raw[i] for i in raw_index)

    def plain_pos(raw_offset: int) -> int:
        return bisect.bisect_left(raw_index, raw_offset)

    stray = plain.find("\\")
    if stray != -1:
        warnings.append(f"Backslash that is not a USFM marker at code-point {raw_index[stray]}")
    bar = plain.find("|")
    if bar != -1:
        # Attributes whose marker never closes properly (seen for real: a custom
        # `\zsem-s |x-note="..."*` milestone ending in a bare `*`) would otherwise
        # leak glosses, Greek and notes into the visible text.
        warnings.append(f"Word attributes not closed by a USFM marker at code-point {raw_index[bar]}")

    notes = tuple(
        _note(raw, match, plain_pos(start), start, end) for match, start, end in note_matches
    )
    styles = tuple(
        StyleSpan(name, plain_pos(opened_at), plain_pos(closed_at))
        for name, opened_at, closed_at in sorted(style_ranges, key=lambda item: item[1])
    )
    ranges: list[tuple[int, int]] = []
    start = None
    for index, flag in enumerate(removed):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            ranges.append((start, index))
            start = None
    if start is not None:
        ranges.append((start, len(raw)))

    paras = tuple(
        ParaMark(name, plain_pos(token_end), token_start, token_end)
        for name, token_start, token_end in para_starts
    )

    return LiftedVerse(
        raw=raw, plain=plain, raw_index=raw_index, notes=notes, styles=styles,
        warnings=tuple(warnings), removed=tuple(ranges), paras=paras,
    )


# --- marker edits on the string an editor holds (#507) -----------------------
#
# The verse editor edits the raw stored string. These make the marker changes a
# reviewer would otherwise type by hand -- mark words as a keyword (`\k`) or as
# Selah (`\qs`), set a poetry line's level, break a line, join two -- on that
# string, and hand back the new string and where the selection is in it. They
# write nothing: the editor still saves through `verse.edit`, and the reviewer
# sees the result before saving. They live here because finding a marker in a
# verse string is this module's job and nobody else's (gotcha 14).
#
# One rule holds for all of them: **the verse's words do not change.** Each
# result is checked against it (`_same_words`), and an edit that would change
# them is refused with the reason rather than returned.

# The character styles the editor can switch on and off for a selection.
TOGGLE_STYLES = ("k", "qs")
# The poetry levels the editor offers for a line.
LINE_LEVELS = ("q", "q1", "q2", "q3")


@dataclass(frozen=True)
class MarkupEdit:
    text: str      # the verse string after the edit; the one given when refused
    start: int     # the selection in `text`, code points
    end: int
    changed: bool
    reason: str = ""  # why nothing changed, for the reviewer; "" when it did

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "start": self.start, "end": self.end,
                "changed": self.changed, "reason": self.reason}


def _refused(raw: str, start: int, end: int, reason: str) -> MarkupEdit:
    return MarkupEdit(raw, start, end, False, reason)


def _same_words(before: str, after: str) -> bool:
    return " ".join(lift_verse(before).plain.split()) == " ".join(lift_verse(after).plain.split())


def _clamp(raw: str, offset: int) -> int:
    return max(0, min(len(raw), int(offset)))


def _line_of(lifted: LiftedVerse, offset: int) -> ParaMark | None:
    """The paragraph marker whose line `offset` is in: the last one at or
    before it. None on the verse's first line, which has no marker of its own."""
    found = None
    for para in lifted.paras:
        if para.raw_start > offset:
            break
        found = para
    return found


def toggle_style(raw: str, start: int, end: int, marker: str) -> MarkupEdit:
    """Mark raw[start:end] with a character style (`\\k … \\k*`), or take the
    style off when the selection or the caret is already inside one."""
    start, end = sorted((_clamp(raw, start), _clamp(raw, end)))
    if marker not in TOGGLE_STYLES:
        return _refused(raw, start, end, f"\\{marker} cannot be switched from here.")
    existing = re.compile(rf"\\{re.escape(marker)} (.*?)\\{re.escape(marker)}\*", re.DOTALL)
    for match in existing.finditer(raw):
        if match.start() <= start and end <= match.end():
            inner = match.group(1)
            text = raw[:match.start()] + inner + raw[match.end():]
            if not _same_words(raw, text):
                return _refused(raw, start, end, "Taking the marker off would change the verse's words.")
            return MarkupEdit(text, match.start(), match.start() + len(inner), True)
    while start < end and raw[start].isspace():
        start += 1
    while end > start and raw[end - 1].isspace():
        end -= 1
    if start == end:
        return _refused(raw, start, end, "Select the words to mark first.")
    selected = raw[start:end]
    lifted = lift_verse(raw)
    if ("\\" in selected or "|" in selected
            or lifted.removed_range_containing(start) or lifted.removed_range_containing(end)):
        return _refused(raw, start, end, "Select plain words only: the selection has a marker or a note in it.")
    at = lifted.map_offset(start)
    for span in lifted.styles:
        if span.start <= at < span.end:
            return _refused(
                raw, start, end,
                f"The selection is inside \\{span.marker} … \\{span.marker}*. Marking inside another style is not done from here.",
            )
    opener = f"\\{marker} "
    text = raw[:start] + opener + selected + f"\\{marker}*" + raw[end:]
    if not _same_words(raw, text):
        return _refused(raw, start, end, "Marking this selection would change the verse's words.")
    return MarkupEdit(text, start + len(opener), start + len(opener) + len(selected), True)


def set_line_level(raw: str, offset: int, marker: str) -> MarkupEdit:
    """Change the paragraph marker of the line `offset` is in to `marker`."""
    offset = _clamp(raw, offset)
    if marker not in LINE_LEVELS:
        return _refused(raw, offset, offset, f"\\{marker} is not a line level.")
    para = _line_of(lift_verse(raw), offset)
    if para is None:
        return _refused(
            raw, offset, offset,
            "The first line of a verse takes its level from the marker that ends the verse before it. "
            "Change it there.",
        )
    if para.marker == marker:
        return _refused(raw, offset, offset, f"This line is already \\{marker}.")
    name_start = para.raw_start + 1
    name_end = name_start + len(para.marker)
    text = raw[:name_start] + marker + raw[name_end:]
    if not _same_words(raw, text):
        return _refused(raw, offset, offset, "Changing this marker would change the verse's words.")
    caret = offset if offset <= name_start else max(name_start + len(marker), offset + len(marker) - len(para.marker))
    return MarkupEdit(text, caret, caret, True)


def break_line(raw: str, offset: int, opening: str = "") -> MarkupEdit:
    """Start a new line at `offset`, at the level of the line it is in.
    `opening` is the level of the verse's first line, which the string itself
    does not hold. At the end of the verse this adds the marker the next verse
    opens in."""
    offset = _clamp(raw, offset)
    lifted = lift_verse(raw)
    if lifted.removed_range_containing(offset):
        return _refused(raw, offset, offset, "Put the cursor between words, not inside a marker or a note.")
    para = _line_of(lifted, offset)
    marker = para.marker if para is not None else opening
    if marker not in PARAGRAPH_MARKERS or marker == "b":
        marker = opening if opening in PARAGRAPH_MARKERS and opening != "b" else "p"
    before = raw[:offset].rstrip(" \t")
    after = raw[offset:].lstrip(" \t")
    if not before.strip():
        return _refused(
            raw, offset, offset,
            "A verse cannot start with a line marker: its first line takes its level from the verse before it.",
        )
    # Nothing between this line's own marker and the cursor, or between the
    # cursor and the next marker: the new line, or the old one, would be empty.
    if para is not None and not raw[para.raw_end:offset].strip():
        return _refused(raw, offset, offset, "A line already starts here.")
    for following in lifted.paras:
        if following.raw_start >= offset and not raw[offset:following.raw_start].strip():
            return _refused(raw, offset, offset, "A line already starts here.")
    text = before + "\n\\" + marker + (" " + after if after else "")
    if not _same_words(raw, text):
        return _refused(raw, offset, offset, "Put the cursor between words.")
    caret = len(before) + 2 + len(marker) + (1 if after else 0)
    return MarkupEdit(text, caret, caret, True)


def join_line(raw: str, offset: int) -> MarkupEdit:
    """Remove the paragraph marker of the line `offset` is in, so the line
    runs on from the one above it."""
    offset = _clamp(raw, offset)
    lifted = lift_verse(raw)
    para = _line_of(lifted, offset)
    if para is None:
        return _refused(raw, offset, offset, "This is the verse's first line: there is no line above it in this verse.")
    before = raw[:para.raw_start].rstrip()
    following = next((item for item in lifted.paras if item.raw_start > para.raw_start), None)
    content_end = following.raw_start if following is not None else len(raw)
    if not raw[para.raw_end:content_end].strip():
        # The line holds no words (a stanza break, or the marker the next verse
        # opens in): only the marker goes, and the lines after it stay lines.
        rest = raw[content_end:]
        text = before + ("\n" if before and rest else "") + rest
        caret = len(before)
    else:
        above = _line_of(lifted, para.raw_start - 1) if para.raw_start else None
        if above is not None and above.marker == "b" and not raw[above.raw_end:para.raw_start].strip():
            return _refused(
                raw, offset, offset,
                "The line above is a stanza break (\\b), which holds no words. Join that line first.",
            )
        after = raw[para.raw_end:].lstrip()
        text = before + (" " if before else "") + after
        caret = len(before) + (1 if before else 0)
    if not _same_words(raw, text):
        return _refused(raw, offset, offset, "Joining these lines would change the verse's words.")
    return MarkupEdit(text, caret, caret, True)


def edit_markup(raw: str, action: str, *, start: int = 0, end: int = 0, marker: str = "",
                opening: str = "") -> MarkupEdit:
    """One marker edit by name, for the protocol (`verse.markup`)."""
    if action == "style":
        return toggle_style(raw, start, end, marker)
    if action == "level":
        return set_line_level(raw, start, marker)
    if action == "break":
        return break_line(raw, start, opening)
    if action == "join":
        return join_line(raw, start)
    return _refused(raw, _clamp(raw, start), _clamp(raw, end), f"Unknown marker edit: {action}.")
