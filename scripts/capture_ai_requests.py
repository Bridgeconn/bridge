"""Offline capture of the AI review requests for one chapter (#500).

Runs the verse review on a COPY of a project with the network call replaced by a
recorder, and reports the characters of every request and of every field of its
input. Nothing is sent to a provider: the client is handed a transport that
records the POST body and answers it locally, and `ai_http.urlopen` is replaced
with a function that raises, so a code path that bypassed the transport would
fail rather than connect.

    python scripts/capture_ai_requests.py <project folder> --chapter 1 --out <folder>

The project folder is never opened. It is copied, with the `resources` folder
two levels above it, into a scratch folder laid out like Bridge's data folder
(`<work>/Bridge/data/projects/<name>`, `<work>/Bridge/data/resources`), and
`LOCALAPPDATA` points at that scratch folder before any engine module is
imported, so the workspace database the engine registers the copy in is a
scratch one too. Close Bridge first: a workbench database copied while Bridge
is writing to it may be mid-transaction.

What the recorder answers, so the three calls of a verse follow one another as
they do on a real run:

- semantic mapping: the mapping the project copy already stores for that
  passage, when it has one (a project that has been reviewed), restricted to
  the units and segments the request names; otherwise every unit unresolved.
  The request itself is always issued cold, because a cached mapping sends
  nothing and the point is to see what a first run sends.
- alignment gap-fill: no links.
- review: one `review` row per check, no selections.

So the REQUESTS are the ones the code builds; the answers are stand-ins and say
nothing about verdicts. The copy's stored AI reviews are overwritten by those
stand-ins, which is why this only ever runs on a copy.

Limits worth knowing before quoting a number from this:

- Characters, not tokens. Hebrew and Devanagari cost more tokens per character
  than English; `estimatedInputTokens` is the same rough estimate the engine
  uses for an unanswered call (`ai_client.estimate_input_tokens`).
- A project that has already been reviewed is not a fresh import: its checks
  carry selections, its approved renderings are filled in and its alignment
  gaps are mostly closed, so its review requests are larger and its alignment
  requests fewer than the first paid run's were.
- The number of mapping requests depends on the answers (an unresolved unit
  widens the search and asks again), so with stand-in answers it is an
  approximation of a real run's.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

SCHEMA_KINDS = {
    "bridge_semantic_mapping_v04": "mapping",
    "tc_alignment_proposal": "alignment",
    "tc_full_review": "review",
    # #502: several verses in one review request.
    "tc_window_review": "review",
}


def _chars(value: Any) -> int:
    """Characters of a value as it is serialised into the request input."""
    return len(json.dumps(value, ensure_ascii=False))


def _common_prefix(a: str, b: str) -> int:
    limit = min(len(a), len(b))
    n = 0
    while n < limit and a[n] == b[n]:
        n += 1
    return n


def copy_project(source: Path, work: Path) -> Path:
    """Copy the project (and the resources folder beside `projects`) into a
    scratch data folder and return the copy's path. The source is only read."""
    source = source.resolve()
    if not (source / "manifest.json").is_file():
        raise SystemExit(f"Not a Bridge project folder (no manifest.json): {source}")
    data = work / "Bridge" / "data"
    dest = data / "projects" / source.name
    if dest.exists():
        raise SystemExit(f"Scratch copy already exists, choose an empty --work folder: {dest}")
    work_resolved = work.resolve()
    if work_resolved == source or work_resolved in source.parents or source in work_resolved.parents:
        raise SystemExit("--work must be outside the project folder and must not contain it.")
    shutil.copytree(source, dest)
    resources = source.parent.parent / "resources"
    if resources.is_dir():
        shutil.copytree(resources, data / "resources")
    return dest


class Recorder:
    """A transport that records each request and answers it locally."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.bodies: list[bytes] = []
        self.current_reference = ""
        self.mapping_oracle: dict[str, Any] | None = None
        self.mapping_from_store = False

    def __call__(self, url: str, headers: dict[str, str], body: bytes, timeout: float) -> tuple[int, bytes]:
        from tc_ai_bridge.ai_client import estimate_input_tokens

        text = body.decode("utf-8")
        request = json.loads(text)
        fmt = request.get("text", {}).get("format", {})
        kind = SCHEMA_KINDS.get(str(fmt.get("name")), str(fmt.get("name")))
        input_text = str(request.get("input") or "")
        input_obj = json.loads(input_text)
        entry: dict[str, Any] = {
            "index": len(self.requests),
            "kind": kind,
            "reference": str(input_obj.get("reference") or self.current_reference),
            "forVerse": self.current_reference,
            "timeoutSeconds": timeout,
            "promptCacheKey": bool(request.get("prompt_cache_key")),
            "chars": {
                "instructions": len(str(request.get("instructions") or "")),
                "schema": _chars(fmt.get("schema")),
                "input": len(input_text),
                "body": len(text),
            },
            "estimatedInputTokens": estimate_input_tokens(body),
            "inputFields": {key: _chars(value) for key, value in input_obj.items()},
        }
        if kind == "review":
            # A window request (#502) nests each verse under `verses`; a
            # single-verse request is its own one verse.
            blocks = input_obj.get("verses") if isinstance(input_obj.get("verses"), list) else [input_obj]
            checks = [c for block in blocks for c in (block.get("translationCore_checks") or [])]
            entry["checks"] = len(checks)
            entry["verses"] = [str(block.get("reference") or "") for block in blocks]
            if "verses" in input_obj:
                entry["reference"] = f"{entry['verses'][0]} .. {entry['verses'][-1]}" if len(blocks) > 1 else entry["verses"][0]
                verse_fields: dict[str, int] = {}
                for block in blocks:
                    for key, value in block.items():
                        verse_fields[key] = verse_fields.get(key, 0) + _chars(value)
                entry["verseFields"] = verse_fields
            by_kind: dict[str, int] = {}
            for item in (input_obj.get("evidence_catalog") or {}).values():
                name = str(item.get("kind") or "?") if isinstance(item, dict) else "?"
                by_kind[name] = by_kind.get(name, 0) + _chars(item)
            entry["evidenceByKind"] = by_kind
            check_fields: dict[str, int] = {}
            for check in checks:
                for key, value in check.items():
                    check_fields[key] = check_fields.get(key, 0) + _chars(value)
            entry["checkFields"] = check_fields
        if kind == "mapping":
            entry["answeredFromStoredMapping"] = self.mapping_from_store
        entry["_instructions"] = str(request.get("instructions") or "")
        entry["_input"] = input_text
        entry["_schema"] = json.dumps(fmt.get("schema"), ensure_ascii=False, sort_keys=True)
        self.requests.append(entry)
        self.bodies.append(body)
        answer = self._answer(kind, input_obj)
        return 200, json.dumps({
            "output_text": json.dumps(answer, ensure_ascii=False),
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                      "input_tokens_details": {"cached_tokens": 0}},
        }).encode("utf-8")

    def _answer(self, kind: str, input_obj: dict[str, Any]) -> dict[str, Any]:
        if kind == "mapping":
            requested = [str(u.get("id")) for u in input_obj.get("source_units") or []]
            stored = {
                str(m.get("source_unit_id")): m
                for m in (self.mapping_oracle or {}).get("mappings", []) if isinstance(m, dict)
            }
            mappings = [stored[uid] for uid in requested if uid in stored]
            unresolved = [
                {"source_unit_id": uid, "reason": "NOT_LOCATED",
                 "detail": "Offline capture: no stored mapping for this unit."}
                for uid in requested if uid not in stored
            ]
            return {"mappings": mappings, "unresolved_source_units": unresolved,
                    "passage_assessment": "MAPPED" if not unresolved else "NEEDS_REVIEW"}
        if kind == "alignment":
            return {"links": [], "implicit_top_ids": [], "target_only_ids": [], "review_notes": []}
        if kind == "review" and isinstance(input_obj.get("verses"), list):
            return {
                "summaries": [
                    {"reference": str(block.get("reference") or ""), "summary": "Offline capture stand-in."}
                    for block in input_obj["verses"]
                ],
                "check_reviews": [
                    {
                        "reference": str(block.get("reference") or ""),
                        "tool": str(c.get("tool") or ""), "group_id": str(c.get("groupId") or ""),
                        "check_id": str(c.get("checkId") or ""), "source_quote": str(c.get("source_quote") or ""),
                        "selection_ids": [], "nothing_to_select": False, "verdict": "review",
                        "severity": "info", "rationale": "Offline capture stand-in; not a model verdict.",
                        "suggested_correction": "", "confidence": 0.0, "evidence_ids": [],
                    }
                    for block in input_obj["verses"] for c in (block.get("translationCore_checks") or [])
                ],
                "qa_issues": [],
            }
        if kind == "review":
            return {
                "summary": "Offline capture stand-in.",
                "check_reviews": [
                    {
                        "tool": str(c.get("tool") or ""), "group_id": str(c.get("groupId") or ""),
                        "check_id": str(c.get("checkId") or ""), "source_quote": str(c.get("source_quote") or ""),
                        "selection_ids": [], "nothing_to_select": False, "verdict": "review",
                        "severity": "info", "rationale": "Offline capture stand-in; not a model verdict.",
                        "suggested_correction": "", "confidence": 0.0, "evidence_ids": [],
                    }
                    for c in input_obj.get("translationCore_checks") or []
                ],
                "qa_issues": [],
            }
        raise RuntimeError(f"Offline capture has no stand-in answer for schema kind {kind!r}.")


def install_cold_mapping(recorder: Recorder) -> None:
    """Make every mapping request go out as it would on a cold cache, while the
    review still gets the mapping the copy stores (when it stores one)."""
    from tc_ai_bridge import semantic_mapping

    original = semantic_mapping.SemanticMappingEngine.map_units
    asked: dict[tuple[str, ...], Any] = {}

    class _NoRequest(Exception):
        pass

    class _Silent:
        model = ""

        def __init__(self, model: str) -> None:
            self.model = model

        def _post_structured(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise _NoRequest()

    def map_units(self, *, target_index, source_units, store=None, force=False):  # type: ignore[no-untyped-def]
        live_client = self.client
        cached = None
        if store is not None:
            # The stored mapping's fingerprint includes the model that made it,
            # which need not be the model this capture names; look it up under
            # each model the copy holds a mapping from for this reference.
            live_model = self.model
            models = [live_model]
            for record in store.records_for_reference(target_index.book, source_units[0].source_reference):
                name = str(record.get("model") or "")
                if name and name not in models:
                    models.append(name)
            self.client = _Silent(live_model)
            try:
                for name in models:
                    self.model = name
                    try:
                        cached = original(
                            self, target_index=target_index, source_units=source_units, store=store, force=False)
                        break
                    except _NoRequest:
                        cached = None
            finally:
                self.client = live_client
                self.model = live_model
        # A later verse of the same passage asks for the same units and, on a
        # real run, is served from the mapping the first verse stored. Issue the
        # cold request once per set of units, as that run would.
        key = tuple(sorted(unit.id for unit in source_units))
        if key in asked:
            return asked[key]
        recorder.mapping_oracle = cached.result if cached is not None else None
        recorder.mapping_from_store = cached is not None
        try:
            cold = original(self, target_index=target_index, source_units=source_units, store=None, force=True)
        finally:
            recorder.mapping_oracle = None
            recorder.mapping_from_store = False
        asked[key] = cached if cached is not None else cold
        return asked[key]

    semantic_mapping.SemanticMappingEngine.map_units = map_units  # type: ignore[method-assign]


def block_network() -> None:
    from tc_ai_bridge import ai_http

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Offline capture: a network call was attempted and refused.")

    ai_http.urlopen = refuse  # type: ignore[assignment]


def run_chapter(project: Any, client: Any, recorder: Recorder, chapter: str, verses: list[str]) -> list[dict[str, Any]]:
    """Today's path: one verse at a time through `prepare_verse_review`, the
    call `_run_ai_review_for_project` makes for each verse of a job."""
    outcomes: list[dict[str, Any]] = []
    for verse in verses:
        recorder.current_reference = f"{str(project.book_id).upper()} {chapter}:{verse}"
        before = len(recorder.requests)
        started = time.perf_counter()
        error = ""
        try:
            alignment = project.load_verse_alignment(chapter, verse)
            client.prepare_verse_review(project, chapter, verse, alignment)
        except Exception as exc:  # reported per verse; the chapter carries on
            error = f"{type(exc).__name__}: {exc}"
        outcomes.append({
            "verse": verse, "requests": len(recorder.requests) - before,
            "seconds": round(time.perf_counter() - started, 2), "error": error,
        })
    return outcomes


def run_chapter_windows(
    project: Any, client: Any, recorder: Recorder, chapter: str, verses: list[str], window_settings: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The window run (#502): the same `WindowReviewSession` the job uses, with
    a reporter that only keeps score. Returns the per-verse outcomes and the
    windows that were sent."""
    import threading

    from tc_ai_bridge.ai_review_windows import WindowReviewSession

    book = str(project.book_id).upper()
    outcomes: dict[str, dict[str, Any]] = {v: {"verse": v, "requests": 0, "seconds": 0.0, "error": ""} for v in verses}

    class Reporter:
        def begin(self, verse: str) -> None:
            recorder.current_reference = f"{book} {chapter}:{verse}"

        def stage(self, verse: str, percent: int, text: str) -> None:
            pass

        def window(self, window_verses: list[str]) -> None:
            recorder.current_reference = f"{book} {chapter}:{window_verses[0]}"

        def done(self, verse: str, prepared: Any, reviews: Any, issues: Any, summary: str, meta: Any) -> None:
            pass

        def failed(self, verse: str, error: Exception, usage: Any, cost: float) -> None:
            outcomes[verse]["error"] = f"{type(error).__name__}: {error}"

        def cancelled(self, verse: str) -> None:
            outcomes[verse]["error"] = "cancelled"

    session = WindowReviewSession(client, project, chapter, verses, window_settings)
    session.run(Reporter(), threading.Event())
    return list(outcomes.values()), session.windows_sent


def summarise(recorder: Recorder, outcomes: list[dict[str, Any]], label: str, meta: dict[str, Any]) -> dict[str, Any]:
    by_kind: dict[str, dict[str, Any]] = {}
    for req in recorder.requests:
        row = by_kind.setdefault(req["kind"], {
            "requests": 0, "instructions": 0, "schema": 0, "input": 0, "body": 0,
            "estimatedInputTokens": 0, "inputFields": {},
        })
        row["requests"] += 1
        for key in ("instructions", "schema", "input", "body"):
            row[key] += req["chars"][key]
        row["estimatedInputTokens"] += req["estimatedInputTokens"]
        for key, value in req["inputFields"].items():
            row["inputFields"][key] = row["inputFields"].get(key, 0) + value
    for row in by_kind.values():
        row["inputFields"] = dict(sorted(row["inputFields"].items(), key=lambda kv: -kv[1]))
    review = [r for r in recorder.requests if r["kind"] == "review"]
    evidence: dict[str, int] = {}
    check_fields: dict[str, int] = {}
    for req in review:
        for key, value in req.get("evidenceByKind", {}).items():
            evidence[key] = evidence.get(key, 0) + value
        for key, value in req.get("checkFields", {}).items():
            check_fields[key] = check_fields.get(key, 0) + value
    # What a provider's prefix cache could match from one review request to the
    # next: the shared leading characters of the instructions, and of the input.
    prefix_instructions = [
        _common_prefix(a["_instructions"], b["_instructions"]) for a, b in zip(review, review[1:])
    ]
    prefix_input = [_common_prefix(a["_input"], b["_input"]) for a, b in zip(review, review[1:])]
    whole_instructions = sum(
        1 for a, b in zip(review, review[1:]) if a["_instructions"] == b["_instructions"]
    )
    same_schema = sum(1 for a, b in zip(review, review[1:]) if a["_schema"] == b["_schema"])
    # Input characters that follow what a request shares with the one before
    # it: the part a prefix cache could not serve even if it served all of the
    # shared part. The first request shares nothing.
    beyond_shared = (len(review[0]["_input"]) if review else 0) + sum(
        len(b["_input"]) - shared for b, shared in zip(review[1:], prefix_input)
    )
    prefix = {
        "pairs": len(prefix_instructions),
        "inputBeyondShared": beyond_shared,
        "inputShared": sum(prefix_input),
        "instructionsSharedMin": min(prefix_instructions, default=0),
        "instructionsSharedMean": round(sum(prefix_instructions) / len(prefix_instructions)) if prefix_instructions else 0,
        "instructionsIdenticalPairs": whole_instructions,
        "schemaIdenticalPairs": same_schema,
        "inputSharedMin": min(prefix_input, default=0),
        "inputSharedMean": round(sum(prefix_input) / len(prefix_input)) if prefix_input else 0,
    }
    requests = [{k: v for k, v in req.items() if not k.startswith("_")} for req in recorder.requests]
    return {
        "label": label,
        **meta,
        "totals": {
            "requests": len(recorder.requests),
            "body": sum(r["chars"]["body"] for r in recorder.requests),
            "input": sum(r["chars"]["input"] for r in recorder.requests),
            "instructions": sum(r["chars"]["instructions"] for r in recorder.requests),
            "schema": sum(r["chars"]["schema"] for r in recorder.requests),
            "estimatedInputTokens": sum(r["estimatedInputTokens"] for r in recorder.requests),
            "checks": sum(r.get("checks", 0) for r in review),
        },
        "byKind": by_kind,
        "reviewEvidenceByKind": dict(sorted(evidence.items(), key=lambda kv: -kv[1])),
        "reviewCheckFields": dict(sorted(check_fields.items(), key=lambda kv: -kv[1])),
        "reviewPrefix": prefix,
        "verses": outcomes,
        "requests": requests,
    }


def print_summary(summary: dict[str, Any]) -> None:
    totals = summary["totals"]
    print(f"\n== {summary['label']}: {summary['book']} {summary['chapter']}, "
          f"{len(summary['verses'])} verses, {totals['checks']} checks")
    print(f"{'call':<10} {'requests':>8} {'instructions':>13} {'schema':>9} {'input':>11} {'body':>11} {'~tokens':>10}")
    for kind, row in summary["byKind"].items():
        print(f"{kind:<10} {row['requests']:>8} {row['instructions']:>13,} {row['schema']:>9,} "
              f"{row['input']:>11,} {row['body']:>11,} {row['estimatedInputTokens']:>10,}")
    print(f"{'total':<10} {totals['requests']:>8} {totals['instructions']:>13,} {totals['schema']:>9,} "
          f"{totals['input']:>11,} {totals['body']:>11,} {totals['estimatedInputTokens']:>10,}")
    for kind, row in summary["byKind"].items():
        print(f"\n{kind} input by field (characters, whole chapter):")
        for key, value in row["inputFields"].items():
            print(f"  {key:<40} {value:>11,}")
    if summary["reviewEvidenceByKind"]:
        print("\nreview evidence_catalog by kind:")
        for key, value in summary["reviewEvidenceByKind"].items():
            print(f"  {key:<40} {value:>11,}")
        print("\nreview translationCore_checks by field:")
        for key, value in summary["reviewCheckFields"].items():
            print(f"  {key:<40} {value:>11,}")
    prefix = summary["reviewPrefix"]
    print(f"\nreview request to the next ({prefix['pairs']} pairs): instructions identical on "
          f"{prefix['instructionsIdenticalPairs']}, schema identical on {prefix['schemaIdenticalPairs']}; "
          f"input shares {prefix['inputSharedMin']:,} leading characters at least, "
          f"{prefix['inputSharedMean']:,} on average; "
          f"{prefix['inputShared']:,} review input characters repeat the previous request's start, "
          f"{prefix['inputBeyondShared']:,} do not")
    if summary.get("windows"):
        sizes = [len(w["verses"]) for w in summary["windows"]]
        print(f"windows sent: {len(sizes)} (verses per window: {sizes})")
    failed = [v for v in summary["verses"] if v["error"]]
    for verse in failed:
        print(f"  verse {verse['verse']} failed: {verse['error']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("project", help="Project folder to copy. It is read, never opened by the engine.")
    parser.add_argument("--chapter", required=True)
    parser.add_argument("--verses", default="", help="Comma-separated verses; default is the whole chapter.")
    parser.add_argument("--out", default="", help="Folder for summary.json (and the bodies with --dump).")
    parser.add_argument("--work", default="", help="Empty scratch folder for the copy; default is a new temp folder.")
    parser.add_argument("--label", default="capture")
    parser.add_argument("--dump", action="store_true",
                        help="Also write every request body. They contain Scripture, helps text and local paths.")
    parser.add_argument("--keep", action="store_true", help="Keep the scratch copy afterwards.")
    parser.add_argument("--lean-evidence", action="store_true",
                        help="#500 switch (off by default in Bridge): leave out the tW cross-reference sections, "
                             "the TWL occurrence list and the tA example sections.")
    parser.add_argument("--verses-per-request", type=int, default=1,
                        help="#502: verses per review request, 1 to 6. 1 is the single-verse run.")
    parser.add_argument("--whole-chapter", action="store_true",
                        help="#502: no verse limit; a request closes at the whole-chapter caps.")
    parser.add_argument("--chapter-context", action="store_true",
                        help="#502: one shared block (decisions and every article of the chapter) first in every request.")
    parser.add_argument("--window-max-checks", type=int, default=0,
                        help="Measurement only: replace the 24-check cap of a fixed-size window.")
    parser.add_argument("--window-max-chars", type=int, default=0,
                        help="Measurement only: replace the 60,000-character cap of a fixed-size window.")
    parser.add_argument("--count-in-input", action="store_true",
                        help="#500 cache experiment: the check count in the input, not in the instructions or schema.")
    args = parser.parse_args(argv)

    source = Path(args.project)
    made_work = not args.work
    work = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="bridge-ai-capture-"))
    work.mkdir(parents=True, exist_ok=True)
    copy = copy_project(source, work)

    # Before any engine import: the workspace database and settings the engine
    # creates must be the scratch ones, and no real key may be picked up.
    os.environ["LOCALAPPDATA"] = str(work)
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.path.insert(0, str(REPO / "engine"))
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from tc_ai_bridge.ai_client import OpenAIResponsesClient
    from tc_ai_bridge.tc_project import TranslationCoreProject

    block_network()
    recorder = Recorder()
    install_cold_mapping(recorder)
    project = TranslationCoreProject(copy)
    client = OpenAIResponsesClient("offline-capture", transport=recorder)
    from tc_ai_bridge.ai_review_payload import ReviewPayloadOptions
    client.review_options = ReviewPayloadOptions.from_settings({
        "leanEvidence": args.lean_evidence, "countInInput": args.count_in_input,
    })
    chapter = str(args.chapter)
    verses = [v.strip() for v in args.verses.split(",") if v.strip()] or [
        v for v in project.verses(chapter) if v != "front"
    ]
    from tc_ai_bridge import ai_review_windows
    from tc_ai_bridge.ai_review_windows import WindowSettings
    # The caps are constants in Bridge. Lifting them here shows what a window
    # size would send if they were different; it changes nothing in the app.
    if args.window_max_checks:
        ai_review_windows.WINDOW_MAX_CHECKS = args.window_max_checks
    if args.window_max_chars:
        ai_review_windows.WINDOW_MAX_INPUT_CHARS = args.window_max_chars
    window_settings = WindowSettings.from_settings({
        "versesPerRequest": args.verses_per_request, "wholeChapter": args.whole_chapter,
        "chapterContext": args.chapter_context,
    })
    windows: list[dict[str, Any]] = []
    try:
        if window_settings.windowed:
            outcomes, windows = run_chapter_windows(project, client, recorder, chapter, verses, window_settings)
        else:
            # The defaults: exactly the call the job makes for each verse.
            outcomes = run_chapter(project, client, recorder, chapter, verses)
    finally:
        close = getattr(project, "close", None)
        if callable(close):
            close()
    summary = summarise(recorder, outcomes, args.label, {
        "book": str(project.book_id).upper(), "chapter": chapter,
        "project": source.name, "model": client.model,
        "options": {
            "leanEvidence": args.lean_evidence, "countInInput": args.count_in_input,
            "versesPerRequest": window_settings.verses_per_request, "wholeChapter": window_settings.whole_chapter,
            "chapterContext": window_settings.chapter_context,
            "windowMaxChecks": ai_review_windows.WINDOW_MAX_CHECKS,
            "windowMaxChars": ai_review_windows.WINDOW_MAX_INPUT_CHARS,
        },
        "windows": windows,
    })
    print_summary(summary)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{args.label}.summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.dump:
            dump = out / f"{args.label}.requests"
            dump.mkdir(parents=True, exist_ok=True)
            for req, body in zip(recorder.requests, recorder.bodies):
                name = f"{req['index']:03d}_{req['kind']}_{req['forVerse'].replace(' ', '_').replace(':', '-')}.json"
                (dump / name).write_bytes(body)
        print(f"\nWrote {out / (args.label + '.summary.json')}")
    if made_work and not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print(f"Scratch copy kept at {copy}")
    return 1 if any(v["error"] for v in outcomes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
