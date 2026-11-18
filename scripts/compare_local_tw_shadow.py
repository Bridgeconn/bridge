"""What the local translationWords rule would have decided for a chapter, beside
what the AI decided (#501, shadow mode).

    python scripts/compare_local_tw_shadow.py <project folder> --chapter 1 --out <folder>
        [--judged <translator sheet .xlsx>]

Offline and read-only as far as the real project goes: the project is copied
the way `capture_ai_requests.py` copies it, and only the copy is opened. The
copy must already hold AI reviews for the chapter (a project that has been
reviewed); they are read, never re-run, and nothing is sent to a provider.

For every translationWords check of the chapter it reports whether the rule
would pass it, under two views of "a rendering the project already uses":

- `now`: every other check of the term that has a selection, which is what the
  rule sees on a project as it stands. On a reviewed chapter most of those
  selections were applied from the same AI run, so agreement with that run is
  partly the run agreeing with itself.
- `first run`: only selections from earlier verses, which is what the rule
  would have had while the chapter was being reviewed for the first time, in
  order. This is the fair estimate of how many checks it would take.

and compares each would-pass with the stored AI review of that check: the
verdict, and whether the AI selected the same words the alignment gives.
With `--judged`, the translator's verdict on the checks of the #469 sheet is
attached where a check appears in it.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_ai_requests import REPO, copy_project  # noqa: E402


def read_judged(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    """The #469 sheet as `{(verse, check_id): row}`. A minimal .xlsx reader
    (shared strings and the first sheet) so this needs no extra package; the
    file is treated as data and nothing in it is evaluated."""
    with zipfile.ZipFile(path) as archive:
        shared = archive.read("xl/sharedStrings.xml").decode("utf-8")
        sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    strings = [re.sub(r"<[^>]+>", "", m) for m in re.findall(r"<si>(.*?)</si>", shared, re.S)]
    table: list[dict[str, str]] = []
    for row in re.findall(r"<row [^>]*>(.*?)</row>", sheet, re.S):
        cells: dict[str, str] = {}
        for column, attrs, value, inline in re.findall(
            r'<c r="([A-Z]+)\d+"([^>]*)>(?:<v>(.*?)</v>|<is><t[^>]*>(.*?)</t></is>)?', row, re.S,
        ):
            cells[column] = strings[int(value)] if 't="s"' in attrs and value else (value or inline or "")
        table.append(cells)
    if not table:
        return {}
    header = {column: name.strip() for column, name in table[0].items()}
    out: dict[tuple[str, str], dict[str, str]] = {}
    for cells in table[1:]:
        named = {header.get(column, column): value for column, value in cells.items()}
        verse = str(named.get("verse") or "").split(":")[-1].strip()
        check = str(named.get("check_id") or "").strip()
        if verse and check:
            out[(verse, check)] = named
    return out


def verse_key(chapter: str, verse: str) -> tuple[int, int]:
    def number(value: str) -> int:
        digits = re.match(r"\d+", str(value))
        return int(digits.group()) if digits else 0
    return number(chapter), number(verse)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("project", help="Project folder to copy. It is read, never opened by the engine.")
    parser.add_argument("--chapter", required=True)
    parser.add_argument("--out", default="")
    parser.add_argument("--judged", default="", help="The translator-judged sheet (.xlsx) from #469.")
    parser.add_argument("--label", default="shadow")
    args = parser.parse_args(argv)

    work = Path(tempfile.mkdtemp(prefix="bridge-tw-shadow-"))
    copy = copy_project(Path(args.project), work)
    os.environ["LOCALAPPDATA"] = str(work)
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.path.insert(0, str(REPO / "engine"))
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from tc_ai_bridge.local_tw_pass import shadow_tw_decisions
    from tc_ai_bridge.tc_project import TranslationCoreProject

    judged = read_judged(Path(args.judged)) if args.judged else {}
    project = TranslationCoreProject(copy)
    chapter = str(args.chapter)
    rows: list[dict[str, Any]] = []
    models: Counter[str] = Counter()
    try:
        for verse in [v for v in project.verses(chapter) if v != "front"]:
            stored = project.load_ai_review_result(chapter, verse) or {}
            models[str(stored.get("model") or "none")] += 1
            ai_by_check = {
                str(r.get("check_id")): r for r in stored.get("checkReviews", []) if isinstance(r, dict)
            }
            alignment = project.load_verse_alignment(chapter, verse)
            here = verse_key(chapter, verse)
            now = shadow_tw_decisions(project, chapter, verse, alignment)
            first = shadow_tw_decisions(
                project, chapter, verse, alignment,
                accept_reference=lambda ch, vs, here=here: verse_key(ch, vs) < here,
            )
            first_by_check = {r["checkId"]: r for r in first["checks"]}
            for row in now["checks"]:
                ai = ai_by_check.get(row["checkId"], {})
                ai_words = [str(x) for x in (ai.get("proposed_selection_text") or [])]
                same_words = bool(row["alignedTargetWords"]) and Counter(ai_words) == Counter(row["alignedTargetWords"])
                sheet = judged.get((verse, row["checkId"]), {})
                rows.append({
                    "verse": f"{chapter}:{verse}", "checkId": row["checkId"], "groupId": row["groupId"],
                    "sourceQuote": row["sourceQuote"],
                    "alignedTargetWords": " ".join(row["alignedTargetWords"]),
                    "wouldPassNow": row["wouldPass"], "reasonNow": row["reason"],
                    "wouldPassFirstRun": first_by_check[row["checkId"]]["wouldPass"],
                    "reasonFirstRun": first_by_check[row["checkId"]]["reason"],
                    "matchingRenderings": row["matchingRenderings"],
                    "aiVerdict": str(ai.get("verdict") or ""), "aiSelected": " ".join(ai_words),
                    "aiSelectionState": str(ai.get("selection_state") or ""),
                    "aiSameWords": same_words,
                    "inJudgedSheet": bool(sheet),
                    "judgedWrongRun": next((v for k, v in sheet.items() if k.startswith("which run is wrong")), ""),
                    "judgedNote": str(sheet.get("note") or ""),
                })
    finally:
        close = getattr(project, "close", None)
        if callable(close):
            close()
        shutil.rmtree(work, ignore_errors=True)

    def tally(flag: str) -> dict[str, Any]:
        taken = [r for r in rows if r[flag]]
        return {
            "wouldPass": len(taken),
            "aiPassSameWords": sum(1 for r in taken if r["aiVerdict"] == "pass" and r["aiSameWords"]),
            "aiPassOtherWords": sum(1 for r in taken if r["aiVerdict"] == "pass" and not r["aiSameWords"]),
            "aiDidNotPass": sum(1 for r in taken if r["aiVerdict"] != "pass"),
            "aiDidNotPassByVerdict": dict(Counter(r["aiVerdict"] or "no review" for r in taken if r["aiVerdict"] != "pass")),
            "inJudgedSheet": sum(1 for r in taken if r["inJudgedSheet"]),
            "judged": dict(Counter(r["judgedWrongRun"] or "blank" for r in taken if r["inJudgedSheet"])),
        }

    summary = {
        "label": args.label, "project": Path(args.project).name, "chapter": chapter,
        "reviewModels": dict(models), "twChecks": len(rows),
        "aiPassedTw": sum(1 for r in rows if r["aiVerdict"] == "pass"),
        "now": tally("wouldPassNow"), "firstRun": tally("wouldPassFirstRun"),
        "notTakenNow": dict(Counter(r["reasonNow"] for r in rows if not r["wouldPassNow"])),
        "notTakenFirstRun": dict(Counter(r["reasonFirstRun"] for r in rows if not r["wouldPassFirstRun"])),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{args.label}.summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        with open(out / f"{args.label}.checks.csv", "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
            writer.writeheader()
            writer.writerows(rows)
        print(f"Wrote {out / (args.label + '.checks.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
