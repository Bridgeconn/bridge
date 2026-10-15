"""Every Tamil string Bridge puts on screen, with its English and the screen (#235).

Requirement 3 asks a native speaker to review the Tamil in the Language QA
surfaces. There is no i18n file: the strings live in the engine (the coverage
statement in language_qa.py, the indic-qa Tamil layer's labels), in the ta-irv
pack (finding messages and fix rationales, the sandhi grammar's rule names) and
in a few Svelte components. This script collects them into one table, so the
reviewer has one document and the next round is a diff of it.

    python scripts/export_tamil_ui_strings.py            # write docs/TAMIL_UI_STRINGS.md
    python scripts/export_tamil_ui_strings.py --check    # exit 1 if that file is stale
    python scripts/export_tamil_ui_strings.py --csv out.csv   # a sheet for the reviewer

The CSV is UTF-8 with a BOM, so Excel opens the Tamil correctly, and has two
empty columns for the reviewer. Corrections are applied by hand at the source
each row names; then this script is re-run and the Markdown diff is the record.

Two kinds of row. "Tamil" is a Tamil rendering of the English beside it: review
the whole string. "Term" is a Tamil word or example inside an English sentence:
review the Tamil only. The pack rules' `title.ta` is listed last because no
screen shows it today.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "engine"))

from tc_ai_bridge import language_qa  # noqa: E402
from tc_ai_bridge.language_packs import indic_qa_tamil  # noqa: E402

OUT = REPO / "docs" / "TAMIL_UI_STRINGS.md"
PACK = REPO / "engine" / "language_packs" / "ta-irv"
COMPONENTS = REPO / "src" / "lib" / "components"
TAMIL = re.compile("[\u0b80-\u0bff]")

# Where each Svelte file's strings appear, for the Screen column.
_SVELTE_SCREENS = {
    "LanguageQaPanel.svelte": "Language QA panel, (i)",
    "SettingsModal.svelte": "Settings",
}
FINDING = "Language QA finding (panel list, Review panel)"
TOOLTIP = "Fix tooltip (Review panel, verse right-click menu)"


def _row(section: str, rid: str, screen: str, english: str, tamil: str, kind: str, source: str) -> dict[str, str]:
    return {"section": section, "id": rid, "screen": screen, "english": english, "tamil": tamil,
            "kind": kind, "source": source}


def _coverage() -> list[dict[str, str]]:
    src = "engine/tc_ai_bridge/language_qa.py"
    cov = language_qa.coverage()
    rows = []
    for item in cov["inScope"]:
        if item["labelTa"]:
            rows.append(_row("Coverage", f"in.{item['category']}", "Language QA panel, (i), Checks",
                             item["label"], item["labelTa"], "Tamil", f"{src} _IN_SCOPE_LABELS"))
    # "learned" is outside DEFAULT_COVERAGE but carries a Tamil label for when it is listed.
    for category, (label, label_ta) in language_qa._IN_SCOPE_LABELS.items():
        if label_ta and category not in {item["category"] for item in cov["inScope"]}:
            rows.append(_row("Coverage", f"in.{category}", "Language QA panel, (i), Checks",
                             label, label_ta, "Tamil", f"{src} _IN_SCOPE_LABELS"))
    for item in cov["outOfScope"]:
        where = "Language QA panel, (i), Does not check"
        rows.append(_row("Coverage", f"out.{item['category']}", where, item["label"], item["labelTa"],
                         "Tamil", f"{src} _OUT_OF_SCOPE"))
        rows.append(_row("Coverage", f"out.{item['category']}.reason", where, item["reason"], item["reasonTa"],
                         "Tamil", f"{src} _OUT_OF_SCOPE"))
    # Tamil inside an English label (in-scope "sandhi", out-of-scope "agreement").
    for row in rows[:]:
        if row["kind"] == "Tamil" and TAMIL.search(row["english"]):
            rows.append(_row("Coverage", row["id"] + ".en", row["screen"], row["english"],
                             _tamil_runs(row["english"]), "Term", row["source"]))
    return rows


def _svelte() -> list[dict[str, str]]:
    rows = []
    for path in sorted(COMPONENTS.glob("*.svelte")):
        screen = _SVELTE_SCREENS.get(path.name, path.stem)
        for line in path.read_text(encoding="utf-8").splitlines():
            if not TAMIL.search(line):
                continue
            spans = re.findall(r'<span lang="ta">([^<{]+)</span>', line)
            if spans:
                # A heading such as `<h3>Checks{#if tamilCoverage} · <span lang="ta">…</span>{/if}</h3>`.
                english = re.sub(r"\{[^}]*\}|<[^>]+>|·", " ", re.sub(r'<span lang="ta">[^<]*</span>', "", line))
                english = " ".join(english.split())
                for tamil in spans:
                    rows.append(_row("Panel and dialogs", f"{path.stem}.{_slug(english)}", screen, english,
                                     tamil.strip(), "Tamil", f"src/lib/components/{path.name}"))
                continue
            text = (re.search(r'placeholder="([^"]*)"', line) or re.search(r">([^<]*[\u0b80-\u0bff][^<]*)<?", line)
                    or re.search(r"(.*)", line)).group(1)
            text = " ".join(re.sub(r"<[^>]+>", " ", text).split())
            rows.append(_row("Panel and dialogs", f"{path.stem}.{_slug(text)}", screen, text, _tamil_runs(text),
                             "Term", f"src/lib/components/{path.name}"))
    return rows


def _pack_rules() -> list[dict[str, str]]:
    """Finding messages, context messages and fix rationales with Tamil in them,
    one row per distinct string with the rules that share it."""
    seen: dict[tuple[str, str, str], list[str]] = {}
    for path in sorted((PACK / "rules").glob("*.json")):
        rule = json.loads(path.read_text(encoding="utf-8"))
        texts = [("message", FINDING, (rule.get("message") or {}).get("en", "")),
                 ("rationale", TOOLTIP, rule.get("rationale", ""))]
        for ctx in rule.get("contexts") or []:
            texts.append(("context message", FINDING, (ctx.get("message") or {}).get("en", "")))
            texts.append(("context rationale", TOOLTIP, ctx.get("rationale", "")))
            texts += [("alternative rationale", TOOLTIP, alt.get("rationale", "")) for alt in ctx.get("alternatives") or []]
        for field, screen, text in texts:
            if text and TAMIL.search(text):
                seen.setdefault((field, screen, text), []).append(rule["id"])
    rows = []
    for (field, screen, text), rules in seen.items():
        rows.append(_row("ta-irv pack rules", f"{rules[0]}.{field.replace(' ', '-')}", screen, text,
                         _tamil_runs(text), "Term", "engine/language_packs/ta-irv/rules/: " + ", ".join(rules)))
    return rows


def _indic_qa_layer() -> list[dict[str, str]]:
    src = "engine/tc_ai_bridge/language_packs/indic_qa_tamil.py"
    rows = []
    for rid, (_group, label, _inline, _on) in indic_qa_tamil.RULES.items():
        if TAMIL.search(label):
            rows.append(_row("indic-qa Tamil layer", rid, FINDING + "; Checker settings switch", label,
                             _tamil_runs(label), "Term", f"{src} RULES"))
    for name, table, screen in (("WARNING_LABELS", indic_qa_tamil.WARNING_LABELS, FINDING),
                                ("DANGLING_REASONS", indic_qa_tamil.DANGLING_REASONS, "Sandhi finding detail"),
                                ("BASIS", indic_qa_tamil.BASIS, "Sandhi finding detail and fix tooltip")):
        for key, text in table.items():
            if TAMIL.search(text):
                rows.append(_row("indic-qa Tamil layer", f"{name}.{key}", screen, text, _tamil_runs(text),
                                 "Term", f"{src} {name}"))
    return rows


def _sandhi_grammar() -> list[dict[str, str]]:
    """The sandhi grammar's rule names, quoted in a sandhi finding's detail as
    "rule <id>: <name_en> (<name_ta>)". Pack dictionary data: Bridge never
    writes it (CLAUDE.md, indic-qa rules), so a correction here is a change
    upstream in indic-qa, re-synced with scripts/sync_indic_qa.py."""
    path = PACK / "dictionary" / "sandhi_rules.tsv"
    lines = [ln for ln in path.read_text(encoding="utf-8-sig").splitlines() if ln and not ln.startswith("#")]
    header = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        cells = dict(zip(header, line.split("\t")))
        if cells.get("name_ta"):
            rows.append(_row("Sandhi grammar rule names", cells["id"], "Sandhi finding detail",
                             cells.get("name_en", ""), cells["name_ta"], "Tamil",
                             "engine/language_packs/ta-irv/dictionary/sandhi_rules.tsv (upstream data)"))
    return rows


def _unshown_titles() -> list[dict[str, str]]:
    rows = []
    for path in sorted((PACK / "rules").glob("*.json")):
        rule = json.loads(path.read_text(encoding="utf-8"))
        title = rule.get("title") or {}
        if title.get("ta"):
            rows.append(_row("Pack rule titles (not shown on any screen today)", rule["id"], "none",
                             title.get("en", ""), title["ta"], "Tamil", f"engine/language_packs/ta-irv/rules/{path.name}"))
    return rows


def _tamil_runs(text: str) -> str:
    """The Tamil words of a mixed string, in order, without repeats."""
    runs = re.findall(r"[\u0b80-\u0bff]+(?:[\s/–-]*[\u0b80-\u0bff]+)*", text)
    # A lone pulli is a message template's "{initial}்", not a word to review.
    return " · ".join(dict.fromkeys(r.strip() for r in runs if r.strip() != "்"))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "tamil"


def collect() -> list[dict[str, str]]:
    rows = _coverage() + _svelte() + _pack_rules() + _indic_qa_layer() + _sandhi_grammar() + _unshown_titles()
    rows = [row for row in rows if row["tamil"]]
    seen: dict[str, int] = {}
    for row in rows:  # two placeholders can slug alike ("Comma-separated, e.g. …")
        seen[row["id"]] = seen.get(row["id"], 0) + 1
        if seen[row["id"]] > 1:
            row["id"] += f"-{seen[row['id']]}"
    return rows


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(rows: list[dict[str, str]]) -> str:
    out = io.StringIO()
    out.write("# Tamil UI strings for native review\n\n"
              "Generated by `scripts/export_tamil_ui_strings.py` (#235); do not edit by hand. "
              "Re-run it after changing any string below, and the diff of this file is the review record. "
              "`--csv` writes the same rows as a sheet with columns for the reviewer.\n\n"
              "**Kind.** *Tamil*: a Tamil rendering of the English beside it; review the whole string. "
              "*Term*: Tamil words inside an English sentence (the Tamil column lists them); review those words only. "
              "Correct a row at its **Source**. The sandhi grammar's names are indic-qa data that Bridge never "
              "writes, so a correction there goes upstream and comes back through `scripts/sync_indic_qa.py`.\n\n")
    out.write(f"{len(rows)} rows.\n")
    section = None
    for row in rows:
        if row["section"] != section:
            section = row["section"]
            out.write(f"\n## {section}\n\n| Id | Screen | English | Tamil | Kind | Source |\n|---|---|---|---|---|---|\n")
        out.write("| " + " | ".join(_cell(row[k]) for k in ("id", "screen", "english", "tamil", "kind", "source")) + " |\n")
    return out.getvalue()


def write_csv(rows: list[dict[str, str]], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Section", "Id", "Screen", "English", "Tamil", "Kind", "Source",
                         "Reviewer: corrected Tamil", "Reviewer: note"])
        for row in rows:
            writer.writerow([row[k] for k in ("section", "id", "screen", "english", "tamil", "kind", "source")] + ["", ""])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help=f"exit 1 if {OUT.relative_to(REPO)} is stale")
    parser.add_argument("--csv", type=Path, help="also write the rows as a CSV sheet for the reviewer")
    args = parser.parse_args(argv)
    rows = collect()
    text = render_markdown(rows)
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT.relative_to(REPO)} is stale: run python scripts/export_tamil_ui_strings.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(REPO)} ({len(rows)} rows)")
    if args.csv:
        write_csv(rows, args.csv)
        print(f"wrote {args.csv} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
