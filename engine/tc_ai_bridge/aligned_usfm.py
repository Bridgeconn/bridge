from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from .models import TokenRef, VerseAlignment
from .usfm import whitespace_tokens
from .usfm_verse import lift_verse


class AlignedUsfmError(ValueError):
    pass


@dataclass(frozen=True)
class _TokenSpan:
    token: TokenRef
    start: int
    end: int


def _target_tokens(text: str) -> list[TokenRef]:
    words = whitespace_tokens(text)
    totals = Counter(words)
    seen: Counter[str] = Counter()
    result: list[TokenRef] = []
    for word in words:
        seen[word] += 1
        result.append(TokenRef(word, seen[word], totals[word], type="bottomWord"))
    return result


def _masked_ranges(text: str) -> list[bool]:
    """Which code points of the raw verse are markup or note content, so a
    target token is never located inside them. The fragment reader decides
    (#91 Phase 1b): exactly the ranges it removes to make the visible text,
    which is also what `whitespace_tokens` tokenised, so every token is
    locatable in what remains."""
    masked = [False] * len(text)
    for start, end in lift_verse(text).removed:
        for index in range(start, end):
            masked[index] = True
    return masked


def _token_spans(text: str) -> list[_TokenSpan]:
    masked = _masked_ranges(text)
    cursor = 0
    spans: list[_TokenSpan] = []
    for token in _target_tokens(text):
        position = text.find(token.word, cursor)
        while position >= 0:
            end = position + len(token.word)
            if not any(masked[position:end]):
                spans.append(_TokenSpan(token, position, end))
                cursor = end
                break
            position = text.find(token.word, end)
        else:
            raise AlignedUsfmError(
                f"Could not locate target token {token.word!r} in the current verse text."
            )
    return spans


def _attribute(value: Any) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _source_milestone(token: TokenRef) -> str:
    attributes = []
    if token.strong:
        attributes.append(("x-strong", token.strong))
    if token.lemma:
        attributes.append(("x-lemma", token.lemma))
    if token.morph:
        attributes.append(("x-morph", token.morph))
    attributes.extend((
        ("x-occurrence", token.occurrence),
        ("x-occurrences", token.occurrences),
        ("x-content", token.word),
    ))
    rendered = " ".join(f'{name}="{_attribute(value)}"' for name, value in attributes)
    return f"\\zaln-s |{rendered}\\*"


def _target_word(token: TokenRef, original: str) -> str:
    return (
        f'\\w {original}|x-occurrence="{token.occurrence}" '
        f'x-occurrences="{token.occurrences}"\\w*'
    )


NO_SOURCE_TOKENS = "no-source-tokens"
NO_SOURCE_TOKENS_DETAIL = (
    "No original-language source tokens are available for this verse "
    "(a lettered segment such as 5a, or a verse the source text does not have), "
    "so it was written without alignment."
)
# #339 point 3: a verse whose alignment data cannot be serialized (its tokens
# no longer match the verse text, a target word sits in two groups, ...) is
# written without alignment and reported by reference; it never blocks the book.
ALIGNMENT_NOT_SERIALIZABLE = "alignment-not-serializable"


def render_unaligned_verse(text: str) -> str:
    """The verse with every target word as a `\\w` word carrying its occurrence
    attributes and no `\\zaln-s`: what `render_aligned_verse` writes for a verse
    with no groups, built from the text alone so it can never fail to match."""
    return render_aligned_verse(text, VerseAlignment([], _target_tokens(text)))


def unaligned_reason(text: str, alignment: VerseAlignment) -> str | None:
    """Why `render_aligned_verse` writes this verse with no alignment at all,
    or None when it can carry alignment. Only a verse that has target words
    and no source tokens is reported; a verse that has source tokens but is
    not aligned yet is ordinary unfinished work, counted by alignment status."""
    if alignment.all_top() or not whitespace_tokens(text):
        return None
    return NO_SOURCE_TOKENS


def _contiguous_runs(positions: list[int]) -> list[list[int]]:
    """Sorted target positions split into maximal runs of adjacent positions:
    [0, 1, 4, 6, 7] -> [[0, 1], [4], [6, 7]]."""
    runs: list[list[int]] = []
    for position in positions:
        if runs and position == runs[-1][-1] + 1:
            runs[-1].append(position)
        else:
            runs.append([position])
    return runs


def render_aligned_verse(text: str, alignment: VerseAlignment) -> str:
    """Render translationCore alignment data in unfoldingWord's USFM 3
    `zaln`/`w` extension convention while preserving target punctuation and
    inline USFM surrounding each target token.

    Multiple source tokens sharing a target span are represented by nested
    milestones. A group whose target words are not adjacent (ordinary in a
    reordering language such as Tamil) is written as one `\\zaln-s ... \\zaln-e`
    nest per contiguous run of its target words, each nest repeating the same
    source milestones (#339, Benz's decision 2026-10-26). That is what
    translationCore's own exporter writes: `word-aligner` 1.1.1
    `lib/js/aligner.js` `merge` groups a group's target positions with
    `groupConsecutiveNumbers` and nests the full milestone chain around each
    run, and its reader merges them back through `sameMilestone`, "needed when
    milestones are not contiguous" (`utils/verseObjects.js`). Bridge's own
    import does the same: milestones with one source signature collect every
    target word they enclose into one group.

    A verse with no original-language source tokens -- every lettered segment
    (5a, 5b), whose source is the whole verse 5 -- has nothing to align to, so
    it is written unaligned: each target word as a `\\w` word with its
    occurrence attributes, exactly as an unaligned word of an aligned verse,
    and no `\\zaln-s` (#307). The caller reports it with `unaligned_reason`;
    it is not refused.
    """
    spans = _token_spans(text)
    expected = [span.token.signature for span in spans]
    actual = [token.signature for token in alignment.all_bottom()]
    if Counter(expected) != Counter(actual):
        raise AlignedUsfmError(
            "Alignment target tokens do not exactly match the current verse text. Recheck the verse before export."
        )

    position_by_signature = {span.token.signature: index for index, span in enumerate(spans)}
    opens: dict[int, list[TokenRef]] = {}
    closes: dict[int, int] = {}
    represented_bottom: set[str] = set()
    for group_index, group in enumerate(alignment.alignments, 1):
        if not group.top_words:
            if group.bottom_words:
                raise AlignedUsfmError(f"Alignment group {group_index} has target words but no source words.")
            continue
        if not group.bottom_words:
            # An unresolved source token has no target span to serialize. It
            # remains explicitly incomplete in the project and is not falsely
            # attached to an unrelated target word.
            continue
        try:
            positions = sorted(position_by_signature[token.signature] for token in group.bottom_words)
        except KeyError as exc:
            raise AlignedUsfmError(
                f"Alignment group {group_index} contains a target token absent from the verse."
            ) from exc
        for token in group.bottom_words:
            if token.signature in represented_bottom:
                raise AlignedUsfmError(
                    f"Target token {token.word!r} occurs in more than one alignment group."
                )
            represented_bottom.add(token.signature)
        for run in _contiguous_runs(positions):
            opens.setdefault(run[0], []).extend(group.top_words)
            closes[run[-1]] = closes.get(run[-1], 0) + len(group.top_words)

    pieces: list[str] = []
    cursor = 0
    for index, span in enumerate(spans):
        pieces.append(text[cursor:span.start])
        pieces.extend(_source_milestone(token) for token in opens.get(index, []))
        pieces.append(_target_word(span.token, text[span.start:span.end]))
        pieces.extend("\\zaln-e\\*" for _ in range(closes.get(index, 0)))
        cursor = span.end
    pieces.append(text[cursor:])
    return "".join(pieces)
