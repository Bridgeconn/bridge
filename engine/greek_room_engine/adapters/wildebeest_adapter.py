"""
Wildebeest adapter.

Per doc §7, this is the first and cleanest Greek Room component to
integrate: direct Python API, read-only, no modification of source files.
It catches mixed scripts, bad Unicode, misplaced Indic marks, punctuation
anomalies, etc. — exactly what the "Unicode" badge category needs.

This adapter tries to use the real `wildebeest` package if installed. If
it's not available (e.g. during frontend/protocol development before the
pip dependency is wired up), it falls back to a small set of deterministic
mock checks so the rest of the pipeline (protocol, caching, UI) can be
built and tested independently.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import sys
import threading
import unicodedata
from collections import Counter, OrderedDict
from typing import Any

from .base import CheckAdapter
from ..models.finding import QaFinding, FindingCategory, Severity, EvidenceItem

log = logging.getLogger(__name__)

try:
    import wildebeest  # type: ignore
    import wildebeest.wb_analysis as wb_ana  # type: ignore
    _WILDEBEEST_AVAILABLE = True
    # stdout is reserved strictly for the JSON-RPC protocol stream
    # (stdio_transport.py) — stderr is where the Rust side's sidecar.rs
    # prints everything, prefixed "[bridge-engine]", visible live in
    # whichever terminal `npm run tauri dev` is running in. Without this
    # line, whether the real engine loaded or silently fell back to the
    # mock was completely invisible short of manually calling engine.info.
    print(f"[wildebeest] real engine active, version {getattr(wildebeest, '__version__', 'unknown')}",
          file=sys.stderr, flush=True)
except Exception as exc:
    # Deliberately broad, not just ImportError: an installed-but-broken
    # wildebeest must degrade to the mock, never crash the whole sidecar at
    # startup. Confirmed necessary, not defensive-programming paranoia —
    # wildebeest-nlp 0.9.2 (the only release on PyPI, and the same on
    # upstream's GitHub HEAD as of 2026-08) fails with UnicodeEncodeError,
    # not ImportError, when compiled under Python 3.13: one of its
    # docstrings contains a literal lone-surrogate escape (\uDC80-\uDCFF,
    # used as prose describing surrogateescape handling), which Python 3.13
    # newly rejects in docstrings (see CPython issue #142411). See
    # docs/BUILD_LOG.md for the full investigation and options.
    wb_ana = None
    _WILDEBEEST_AVAILABLE = False
    print(f"[wildebeest] real engine unavailable ({exc!r}), using mock fallback",
          file=sys.stderr, flush=True)


# -- Bridge's own reading of what Wildebeest tallies but does not flag ---------
#
# Two of the reporter's cases in #204 are real gaps in the report itself:
# Wildebeest lists a lone `@` only under `pattern`, beside every token that
# merely ends in a full stop, and a whole Malayalam word inside an English
# verse only as a count under `letter-script`. The helpers below turn those
# into findings. They are shared by the real path and the mock so the two
# raise the same check types for the same verse.

# Symbols with no place in Scripture text. Wildebeest reports every token
# holding one of its "characters of interest" under `pattern`, but that set
# also holds ordinary sentence punctuation (`.`, `,`, `-`, `'`, `?`), so the
# adapter keeps the subset a reviewer should see, and scans for it itself on
# both paths (see `_token_level_findings` for why the report is not read).
_SUSPICIOUS_SYMBOLS = frozenset("@#$%&*+~_|\u00A6\u00A7\u20AC\u00A3\u00A5\u20AA\u00A2\u00A4\u20A8\u20B9\u00B5")

# Usual script per language id (the manifest's target_language.id: an ISO 639
# code, optionally with a region, `ta-IN`). The same table as
# tc_ai_bridge.language_qa.LANGUAGE_SCRIPTS, copied rather than imported: this
# package stays free of tc_ai_bridge imports (see names_adapter).
_LANGUAGE_SCRIPTS = {
    "ta": "TAMIL", "tam": "TAMIL", "hi": "DEVANAGARI", "hin": "DEVANAGARI",
    "mr": "DEVANAGARI", "mar": "DEVANAGARI", "ne": "DEVANAGARI", "nep": "DEVANAGARI",
    "sa": "DEVANAGARI", "san": "DEVANAGARI", "bn": "BENGALI", "ben": "BENGALI",
    "as": "BENGALI", "asm": "BENGALI", "te": "TELUGU", "tel": "TELUGU",
    "kn": "KANNADA", "kan": "KANNADA", "ml": "MALAYALAM", "mal": "MALAYALAM",
    "gu": "GUJARATI", "guj": "GUJARATI", "pa": "GURMUKHI", "pan": "GURMUKHI",
    "or": "ORIYA", "ori": "ORIYA", "od": "ORIYA", "ory": "ORIYA",
    "ur": "ARABIC", "urd": "ARABIC", "ar": "ARABIC", "ara": "ARABIC",
    "he": "HEBREW", "heb": "HEBREW", "el": "GREEK", "ell": "GREEK",
    "ru": "CYRILLIC", "rus": "CYRILLIC", "en": "LATIN", "eng": "LATIN",
}

# A letter's script is the first word of its Unicode name ("TAMIL LETTER A",
# "LATIN SMALL LETTER A"). A letter named otherwise ("MODIFIER LETTER ...",
# "CJK UNIFIED ...") has no script here and never decides anything.
_SCRIPT_NAMES = frozenset((
    "TAMIL", "DEVANAGARI", "BENGALI", "TELUGU", "KANNADA", "MALAYALAM",
    "GUJARATI", "GURMUKHI", "ORIYA", "SINHALA", "ARABIC", "HEBREW", "LATIN",
    "CYRILLIC", "GREEK", "SYRIAC", "THAI", "MYANMAR", "ETHIOPIC", "ARMENIAN",
    "GEORGIAN", "TIBETAN", "KHMER",
))

_WORD_CHUNK_RE = re.compile(r"\S+")
# A USFM marker. Findings are offsets into the raw stored verse string, which
# an aligned or styled import keeps verbatim (`\zaln-s |x-strong="H430"\*\w
# ...`, `\wj ...\wj*`), so a token scan of such a verse would flag its markup
# as Latin words and symbols. Wildebeest's own checks tokenise at punctuation
# and are not misled; the token-level checks below run on the lifted plain
# text the caller passes, and stand down on such a verse when it does not
# (`_token_level_findings`). Presence only; this never parses USFM (gotcha 14).
_USFM_MARKER_RE = re.compile(r"\\[A-Za-z]")


def _script_of(char: str) -> str | None:
    if not char.isalpha():
        return None
    first = unicodedata.name(char, "").split(" ", 1)[0]
    return first if first in _SCRIPT_NAMES else None


def _expected_script(lang_code: str, text: str) -> str | None:
    """The script this verse is expected in: the language's usual script, or,
    for a language id the table does not know, the script of a strict majority
    of the verse's letters. None when neither decides."""
    code = (lang_code or "").strip().lower().replace("_", "-").split("-", 1)[0]
    known = _LANGUAGE_SCRIPTS.get(code)
    if known:
        return known
    counts = Counter(script for script in map(_script_of, text) if script)
    if not counts:
        return None
    (top, n), = counts.most_common(1)
    return top if n * 2 > sum(counts.values()) else None


def _word_span(chunk: str) -> tuple[int, int] | None:
    """The chunk minus its leading and trailing punctuation."""
    keep = [i for i, c in enumerate(chunk) if c.isalnum() or unicodedata.category(c).startswith("M")]
    if not keep:
        return None
    return keep[0], keep[-1] + 1


def _foreign_script_words(text: str, expected: str) -> list[tuple[str, int, int, str]]:
    """Whole words written in one script that is not `expected`, as
    (word, start, end, script). A token with letters from two scripts is
    Wildebeest's mixed-script case and is left to it."""
    out: list[tuple[str, int, int, str]] = []
    for match in _WORD_CHUNK_RE.finditer(text):
        chunk = match.group()
        scripts = {script for script in map(_script_of, chunk) if script}
        if len(scripts) != 1 or expected in scripts:
            continue
        span = _word_span(chunk)
        if span is None:
            continue
        out.append((chunk[span[0]:span[1]], match.start() + span[0], match.start() + span[1], next(iter(scripts))))
    return out


def _symbol_tokens(text: str) -> list[tuple[str, int, int, str]]:
    """Whitespace tokens holding a suspicious symbol, as (token, start, end,
    symbol): the first such symbol in the token, one finding per token."""
    out: list[tuple[str, int, int, str]] = []
    for match in _WORD_CHUNK_RE.finditer(text):
        chunk = match.group()
        symbol = next((c for c in chunk if c in _SUSPICIOUS_SYMBOLS), None)
        if symbol is not None:
            out.append((chunk, match.start(), match.end(), symbol))
    return out


def _non_canonical_runs(text: str) -> list[tuple[str, int, int, str]]:
    """Base-plus-combining-mark runs that are not in NFC, first occurrence of
    each distinct run, as (run, start, end, nfc). The mock's equivalent of
    Wildebeest's `non-canonical` report, which is also per distinct form."""
    out: list[tuple[str, int, int, str]] = []
    seen: set[str] = set()
    i, n = 0, len(text)
    while i < n:
        j = i + 1
        while j < n and unicodedata.combining(text[j]):
            j += 1
        run = text[i:j]
        if j > i + 1 and run not in seen:
            nfc = unicodedata.normalize("NFC", run)
            if nfc != run:
                seen.add(run)
                out.append((run, i, j, nfc))
        i = j
    return out


def _symbol_explanation(symbol: str) -> str:
    name = unicodedata.name(symbol, "symbol")
    return f"Contains {symbol} (U+{ord(symbol):04X} {name}), a symbol not expected in Scripture text."


def _foreign_script_explanation(script: str, expected: str) -> str:
    return f"{script.capitalize()} word in {expected.capitalize()}-script text."


# The parts of a Wildebeest report this adapter reads, per (language, text).
# wb_ana.process is a pure function of its input for the package version this
# process loaded, and it was 58-68% of a whole-book check job, run again on
# every verse of every job and every verse selection (#230). Held for the life
# of the sidecar, not persisted: the project's check_cache rows are written
# through the workbench journal, and a row per verse would flood change_log.
# Keyed by a digest, so the cache never holds verse text; bounded, oldest out.
_REPORT_CACHE: "OrderedDict[tuple[str, bytes], dict[str, Any]]" = OrderedDict()
_REPORT_CACHE_MAX = 50_000
_REPORT_CACHE_LOCK = threading.Lock()


def _report_key(lang_code: str, text: str) -> tuple[str, bytes]:
    return (lang_code, hashlib.sha1(text.encode("utf-8", errors="surrogatepass")).digest())


def _cached_report(lang_code: str, text: str) -> dict[str, Any]:
    """The used part of wb_ana.process's report for this text. Raises what
    process raises; a failure is not cached, so the next call tries again."""
    key = _report_key(lang_code, text)
    with _REPORT_CACHE_LOCK:
        report = _REPORT_CACHE.get(key)
        if report is not None:
            _REPORT_CACHE.move_to_end(key)
            return report
    buf = io.StringIO()
    wb_ana.process(string=text, lang_code=lang_code, json_output=buf)  # type: ignore[union-attr]
    data = json.loads(buf.getvalue())
    report = {
        "notable-token": data.get("notable-token") or {},
        "non-canonical": data.get("non-canonical") or {},
        "zero-width": ((data.get("block") or {}).get("ZERO_WIDTH")) or {},
    }
    with _REPORT_CACHE_LOCK:
        _REPORT_CACHE[key] = report
        _REPORT_CACHE.move_to_end(key)
        while len(_REPORT_CACHE) > _REPORT_CACHE_MAX:
            _REPORT_CACHE.popitem(last=False)
    return report


class WildebeestAdapter(CheckAdapter):
    engine_name = "wildebeest"

    def is_available(self) -> bool:
        # Always available: falls back to the mock implementation when the
        # real `wildebeest` package isn't installed, so protocol/UI work
        # isn't blocked on the upstream dependency being wired up yet.
        return True

    def using_real_engine(self) -> bool:
        return _WILDEBEEST_AVAILABLE

    def version(self) -> str:
        if _WILDEBEEST_AVAILABLE:
            try:
                import wildebeest  # type: ignore
                return getattr(wildebeest, "__version__", "unknown")
            except Exception:
                return "unknown"
        return "mock-0.0.0"

    def check_verse(self, *, project_id: str, lang_code: str, ref: str,
                     text: str, params: dict[str, Any]) -> list[QaFinding]:
        if _WILDEBEEST_AVAILABLE:
            return self._check_with_wildebeest(project_id, lang_code, ref, text, params)
        return self._check_mock(project_id, lang_code, ref, text, params)

    # -- real integration -------------------------------------------------

    def _check_with_wildebeest(self, project_id: str, lang_code: str,
                                ref: str, text: str, params: dict[str, Any]) -> list[QaFinding]:
        """
        Adapts real Wildebeest analysis into QaFindings.

        wb_analysis has no `check()`/issue-list function — it's built as a
        bulk file-analysis tool. The actual programmatic entry point is
        `wb_analysis.process(string=..., lang_code=..., json_output=<IO>)`,
        which writes an aggregate report grouped by category, not a flat
        per-position issue list (verified directly against wildebeest-nlp
        0.9.2, since its own docs don't describe this — see
        docs/BUILD_LOG.md for the investigation).

        Only a subset of that report's top-level keys represent an actual
        problem for a single short verse; most of the rest (letter-script
        counts, the full per-character `block` inventory, digit/number
        breakdowns) are corpus-level descriptive tallies — e.g. `block`
        lists ordinary Tamil letters just because they occurred, not
        because anything is wrong with them. Treating every key as a
        finding would flood a verse with "findings" for its own ordinary
        text. Wired up so far, each verified against real flagged input:
          - `notable-token`: tokens containing characters from more than
            one script (mixed-script tokens — the case the old mock
            approximated with one regex).
          - `non-canonical`: characters not in Unicode Normalization Form C
            (e.g. NFD-decomposed instead of NFC-composed).
          - zero-width/invisible characters, read from `block.ZERO_WIDTH`
            (bidi/formatting characters that are invisible but real).
        Two more checks come from `_token_level_findings`, Bridge's own scan
        of the verse, not from the report (#204). The report does hold the
        raw material — a lone `@` is filed under `pattern` as "TOKENS WITH @
        (U+0040 COMMERCIAL AT)", and a Malayalam word inside an English verse
        is a count under `letter-script` — but `pattern` files `dark.` under
        "TOKENS WITH . (U+002E FULL STOP)" beside it, and `letter-script`
        says nothing per token; and the report is of the raw stored verse,
        where every `\\wj*` would be a token with an asterisk. So the scan
        runs on the lifted plain text when the caller supplies it (see
        `_token_level_findings`) and only its symbol set is taken from
        Wildebeest's: `_SUSPICIOUS_SYMBOLS` is the subset of its characters
        of interest a reviewer should see.
        Not yet wired: `char-conflict` and `pattern` — real categories in the
        schema. `pattern`'s shape is now verified (above); `char-conflict`'s
        is not: no input was found that populated it. Don't guess it; that's
        exactly the mistake that made this function wrong the first time.
        Verify against real triggering input before adding it (#125).
        """
        findings: list[QaFinding] = []
        book = ref.split()[0] if " " in ref else ""
        try:
            data = _cached_report(lang_code, text)
        except Exception:
            # Wildebeest is explicitly Alpha (doc §31) — a bad verse must
            # degrade to "no wildebeest findings for this verse", never take
            # down the whole verse.runChecks call alongside local/tN/tW
            # findings that have nothing to do with it.
            log.exception("Real Wildebeest analysis failed for %s; skipping wildebeest findings for this verse.", ref)
            return findings

        for category_name, tokens in data["notable-token"].items():
            if not isinstance(tokens, dict):
                continue
            for token_text in tokens:
                findings.append(self._make_finding(
                    project_id=project_id, book=book, text=text, flagged=token_text,
                    check_type="wildebeest.notable_token",
                    severity=Severity.HIGH, confidence=0.85,
                    explanation=f"{category_name.capitalize()}.",
                    evidence=[EvidenceItem(label="Category", value=category_name)],
                ))

        for orig, details in data["non-canonical"].items():
            if not isinstance(details, dict):
                continue
            norm = str(details.get("norm") or "") or None
            orig_form = str(details.get("orig-form") or "").strip().rstrip(",").strip()
            norm_form = str(details.get("norm-form") or "").strip().rstrip(",").strip()
            findings.append(self._make_finding(
                project_id=project_id, book=book, text=text, flagged=orig,
                check_type="wildebeest.non_canonical",
                severity=Severity.MEDIUM, confidence=0.75,
                explanation=f"Not in Unicode Normalization Form C ({orig_form} instead of {norm_form}).",
                suggested_replacement=norm,
            ))

        for char, details in data["zero-width"].items():
            if not isinstance(details, dict):
                continue
            name = str(details.get("name") or "unknown character")
            findings.append(self._make_finding(
                project_id=project_id, book=book, text=text, flagged=char,
                check_type="wildebeest.zero_width",
                severity=Severity.MEDIUM, confidence=0.8,
                explanation=f"Contains a zero-width/invisible character: {name}.",
            ))

        findings.extend(self._token_level_findings(project_id, lang_code, book, text, params))
        return findings

    def _token_level_findings(self, project_id: str, lang_code: str, book: str, text: str,
                              params: dict[str, Any], *, mixed_script: bool = False,
                              extra_evidence: list[EvidenceItem] = ()) -> list[QaFinding]:
        """Bridge's own per-token checks (#204): a token holding a suspicious
        symbol, a whole word in a script other than the verse's, and — for the
        mock only — a token mixing scripts, which the real engine reports
        itself as `notable-token`.

        A finding's offsets are into the raw stored verse string, which an
        aligned or styled import keeps verbatim (`\\wj ...\\wj*`, `\\f + ...\\f*`,
        `\\zaln-s |x-strong="H430"\\*`), and a scan of that string would flag
        its markup as Latin words and asterisks. So the scan runs on the lifted
        plain text when the caller hands it over as `params["lifted"]` — a
        `tc_ai_bridge.usfm_verse.LiftedVerse`, duck-typed here: `plain` and
        `raw_span(start, end)` are all that is used, so this package stays free
        of tc_ai_bridge imports, the way the names check is tokenised by its
        caller. Without it, a verse that carries any marker is left alone by
        these checks rather than mis-scanned; one without markup is scanned
        directly, its plain text being the raw string.
        """
        lifted = params.get("lifted") if isinstance(params, dict) else None
        if lifted is not None and hasattr(lifted, "plain") and hasattr(lifted, "raw_span"):
            plain = str(lifted.plain)
            to_raw = lifted.raw_span
        elif _USFM_MARKER_RE.search(text):
            return []
        else:
            plain = text
            to_raw = lambda start, end: (start, end)  # noqa: E731

        def raw_offsets(start: int, end: int) -> tuple[int | None, int | None]:
            span = to_raw(start, end)
            return (span[0], span[1]) if span else (None, None)

        findings: list[QaFinding] = []
        extra = list(extra_evidence)

        if mixed_script:
            for match in _WORD_CHUNK_RE.finditer(plain):
                chunk = match.group()
                scripts = sorted({script for script in map(_script_of, chunk) if script})
                if len(scripts) < 2:
                    continue
                start, end = raw_offsets(match.start(), match.end())
                findings.append(self._make_finding(
                    project_id=project_id, book=book, text=text, flagged=chunk, start=start, end=end,
                    check_type="wildebeest.script.mixed",
                    severity=Severity.HIGH, confidence=0.9,
                    explanation=f"Token contains characters from more than one script ({', '.join(s.lower() for s in scripts)}).",
                    evidence=list(extra),
                ))

        for token, start, end, symbol in _symbol_tokens(plain):
            start, end = raw_offsets(start, end)
            findings.append(self._make_finding(
                project_id=project_id, book=book, text=text, flagged=token, start=start, end=end,
                check_type="wildebeest.special_character",
                severity=Severity.MEDIUM, confidence=0.8,
                explanation=_symbol_explanation(symbol), evidence=list(extra),
            ))

        expected = _expected_script(lang_code, plain)
        if expected is None:
            return findings
        code = (lang_code or "").strip().lower().replace("_", "-").split("-", 1)[0]
        basis = f"language id {lang_code!r}" if _LANGUAGE_SCRIPTS.get(code) else "the script of most letters in the verse"
        for word, start, end, script in _foreign_script_words(plain, expected):
            start, end = raw_offsets(start, end)
            findings.append(self._make_finding(
                project_id=project_id, book=book, text=text, flagged=word, start=start, end=end,
                check_type="wildebeest.foreign_script",
                severity=Severity.MEDIUM, confidence=0.7,
                explanation=_foreign_script_explanation(script, expected),
                evidence=[EvidenceItem(label="Expected script", value=f"{expected.capitalize()}, from {basis}"), *extra],
            ))
        return findings

    def _make_finding(self, *, project_id: str, book: str, text: str, flagged: str,
                       check_type: str, severity: Severity, confidence: float,
                       explanation: str, suggested_replacement: str | None = None,
                       evidence: list[EvidenceItem] | None = None,
                       start: int | None = None, end: int | None = None) -> QaFinding:
        if start is None:
            found = text.find(flagged) if flagged else -1
            start = found if found >= 0 else None
            end = (found + len(flagged)) if found >= 0 else None
        return QaFinding(
            project_id=project_id,
            book=book,
            original_text=flagged,
            start_offset=start,
            end_offset=end,
            engine=self.engine_name,
            check_type=check_type,
            category=FindingCategory.UNICODE,
            severity=severity,
            confidence=confidence,
            suggested_replacement=suggested_replacement,
            explanation=explanation,
            evidence=evidence or [],
            engine_version=self.version(),
        )

    # -- fallback mock ------------------------------------------------------

    def _check_mock(self, project_id: str, lang_code: str, ref: str,
                     text: str, params: dict[str, Any]) -> list[QaFinding]:
        """The same check types the real path raises, from the same helpers,
        so a build on the mock (Python 3.13, a missing extra) still surfaces
        them; the Mode evidence says which engine produced them. The mixed-
        script check is per token here as the real engine's `notable-token`
        is (#204): the mock used to flag the first Latin letter anywhere in a
        verse that also had Tamil or Devanagari, so a whole English word in a
        Tamil verse was "mixed script" and a Malayalam one was nothing."""
        book = ref.split()[0] if " " in ref else ""
        mode = EvidenceItem(label="Mode", value="mock adapter (wildebeest not installed)")
        findings: list[QaFinding] = []
        # NFD is found on the raw string: markup is ASCII and has no combining
        # marks, so the raw offsets are exact without a lift.
        for run, start, end, nfc in _non_canonical_runs(text):
            findings.append(self._make_finding(
                project_id=project_id, book=book, text=text, flagged=run, start=start, end=end,
                check_type="wildebeest.non_canonical",
                severity=Severity.MEDIUM, confidence=0.75,
                explanation="Not in Unicode Normalization Form C (NFD instead of NFC).",
                suggested_replacement=nfc, evidence=[mode],
            ))
        findings.extend(self._token_level_findings(
            project_id, lang_code, book, text, params, mixed_script=True, extra_evidence=[mode],
        ))
        return findings
