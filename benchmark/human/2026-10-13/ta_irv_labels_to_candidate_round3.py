#!/usr/bin/env python3
"""Turn the returned round-3 ta-irv reviewer workbook into benchmark data (#230).

    python ta_irv_labels_to_candidate_round3.py <completed.xlsx> --out <folder> --repo <bridge checkout>

Reads the reviewer's dropdown verdicts (sheets 1A, 1C, 2, 4, 6 and the word list,
sheet 3) joined to the hidden `_data` sheet, and writes, in --out:

  human_labels.jsonl   every row with a machine verdict code (ground truth). Kinds:
                       flagged    a current finding (sheets 1A, 1C, 2, 4): scored by the benchmark
                       candidate  a structure check with no rule yet (sheet 6): not scored until
                                  its rule exists; `rule` names the intended rule
                       wordlist   the reviewer's own word list (sheet 3)
  lexicon_curated.csv  new one-word misspelling pairs only (Round-2 Issues CSV shape, for
                       scripts/build_tamil_lexicon.py --curated): a wrong form already in the
                       shipped lexicon's `deprecated` map as a human pair, or in an earlier
                       round's lexicon_curated.csv, is dropped
  summary.json / pack_changes.md   precision per rule from the verdicts, what each says

Verdict codes keep rounds 1-2's (TP, TP1, TP23, TP_OTHER_FIX, FP*, HOUSE, UNSURE).
New: sheet 1C (unnecessary doubling) TP / TP_OTHER_FIX / FP_DOUBLING_RIGHT / HOUSE;
sheet 6 TP / FP; word list TYPO / JOINED / SPLIT_WORD / NOT_AN_ERROR.
No file in the repository is modified.
"""
from __future__ import annotations

import argparse, collections, csv, gzip, json, unicodedata
from pathlib import Path

from openpyxl import load_workbook

nfc = lambda s: unicodedata.normalize("NFC", str(s or ""))

V1A = {"சரி — மிகல் தேவை; பரிந்துரை சரி": "TP", "சரி — மிகல் தேவை; ஆனால் வேறு வடிவம்": "TP_OTHER_FIX",
       "தவறு — இது வேற்றுமை உருபு அல்ல": "FP_ROOT", "தவறு — வேற்றுமை உருபுதான்; ஆனால் இங்கு மிகல் வேண்டாம்": "FP_NODOUBLE",
       "IRV வழக்கு": "HOUSE", "தெரியவில்லை": "UNSURE"}
V1C = {"சரி — மிகல் வேண்டாம்": "TP", "சரி — பிழைதான்; ஆனால் சரியான வடிவம் வேறு": "TP_OTHER_FIX",
       "தவறு — இங்கு மிகல் சரியானது": "FP_DOUBLING_RIGHT", "IRV வழக்கு": "HOUSE", "தெரியவில்லை": "UNSURE"}
V2 = {"சரி — பிழை; பரிந்துரை 1 சரி": "TP1", "சரி — பிழை; பரிந்துரை 2 அல்லது 3 சரி": "TP23",
      "சரி — பிழை; ஆனால் சரியான வடிவம் வேறு": "TP_OTHER_FIX", "தவறு — சொல் சரியானது": "FP",
      "தவறு — ஆட்பெயர்": "FP_NAME", "தெரியவில்லை": "UNSURE"}
V4 = {"சரி — பிழை": "TP", "தவறு — பிழை இல்லை": "FP", "தெரியவில்லை": "UNSURE"}
V6 = {"சரி — திருத்த வேண்டும்": "TP", "தவறு — இப்படியே சரி": "FP", "தெரியவில்லை": "UNSURE"}
V3 = {"எழுத்துப்பிழை": "TYPO", "பிரிந்த சொல்": "SPLIT_WORD", "சேர்ந்த சொல்": "JOINED", "பெயர் / சரியான சொல்": "NOT_AN_ERROR"}
DATA_COLS = ["id", "sheet", "cls", "rule", "fid", "book", "ch", "v", "start", "end", "original", "prev", "next", "suggestions"]


def code(value, table):
    value = nfc(value).strip()
    if not value:
        return None
    for prefix, c in table.items():
        if value.startswith(nfc(prefix)):
            return c
    raise SystemExit(f"unknown verdict: {value!r}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workbook")
    ap.add_argument("--out", required=True)
    ap.add_argument("--repo", required=True)
    a = ap.parse_args()
    out, repo = Path(a.out), Path(a.repo)
    out.mkdir(parents=True, exist_ok=True)
    wb = load_workbook(a.workbook, data_only=True)

    data = {}
    for r in wb["_data"].iter_rows(min_row=2, values_only=True):
        if r[0]:
            d = dict(zip(DATA_COLS, r))
            d["suggestions"] = json.loads(d["suggestions"]) if d["suggestions"] else []
            d["ch"], d["v"] = str(d["ch"]), str(d["v"])
            data[r[0]] = d

    labels = []
    # sheet title, verdict table, verdict column, (name column), correct-form column, note column (1-based)
    sheets = [("1A சந்தி கண்டறிந்தவை", V1A, 10, 11, 12, 13), ("1C மிகா இடம்", V1C, 10, None, 11, 12),
              ("2 எழுத்துப்பிழை", V2, 12, None, 13, 14), ("4 பிற", V4, 9, None, None, 10),
              ("6 அமைப்பு (USFM)", V6, 9, None, None, 10)]
    for title, table, vcol, ncol, fcol, notecol in sheets:
        ws = wb[title]
        for r in range(2, ws.max_row + 1):
            rid = ws.cell(r, 1).value
            if not rid:
                continue
            d = dict(data[rid])
            row = {**d, "kind": "candidate" if d["sheet"] == "6" else "flagged",
                   "verdict": code(ws.cell(r, vcol).value, table), "note": nfc(ws.cell(r, notecol).value)}
            if d["sheet"] == "6":
                row["item"] = int(d["cls"].removeprefix("item"))
                row["rule"] = d["rule"].removeprefix("(candidate) ")
                for key in ("start", "end", "fid", "prev", "next"):
                    row.pop(key, None)
            if ncol:
                row["nextIsName"] = nfc(ws.cell(r, ncol).value) == "ஆம்"
            if fcol:
                row["correctForm"] = nfc(ws.cell(r, fcol).value)
            labels.append(row)

    words = []
    ws = wb["3 சொற்பட்டியல்"]
    for r in range(2, ws.max_row + 1):
        wrong, right, book, ch, v, kind, note = (ws.cell(r, c).value for c in range(1, 8))
        if not wrong:
            continue
        words.append({"id": f"W{len(words) + 1:03d}", "kind": "wordlist", "word": nfc(wrong).strip(),
                      "correctForm": nfc(right).strip(), "book": str(book or "").lower(), "ch": str(ch or ""),
                      "v": str(v or ""), "verdict": code(kind, V3), "note": nfc(note)})
    labels += words

    # ---- the word list against what Bridge already ships ----
    lexicon = json.load(gzip.open(repo / "engine/language_packs/ta-irv/lexicon.json.gz", "rt", encoding="utf-8"))
    shipped = {nfc(k): nfc(v) for k, v in lexicon["deprecated"].items()}
    human_shipped = {nfc(w) for w in lexicon.get("humanConfirmed", [])}
    earlier = set()
    for f in sorted((repo / "benchmark/human").glob("*/lexicon_curated.csv")):
        with f.open(encoding="utf-8-sig") as handle:
            earlier |= {nfc(row["Original Tamil"]) for row in csv.DictReader(handle)}
    curated, word_notes = [], []

    def curate(book, ch, v, wrong, right, why):
        if len(wrong.split()) != 1 or len(right.split()) != 1:
            word_notes.append(f"{wrong} → {right}: not one word for one word ({why}); the lexicon builder drops it")
        elif wrong in earlier or (wrong in shipped and wrong in human_shipped):
            word_notes.append(f"{wrong} → {right}: already shipped as a human pair ({why}); dropped")
        else:
            curated.append([book.upper(), ch, v, "Confirmed typo", "Spelling", "High", "High", wrong, right,
                            f"Human review 2026-10-13 ({why})", "", "No", "accepted"])

    for w in words:
        if w["verdict"] == "TYPO":
            if w["word"] in shipped:
                word_notes.append(f"{w['word']} → {w['correctForm']}: already in the shipped map (→ {shipped[w['word']]}); dropped")
            else:
                curate(w["book"], w["ch"], w["v"], w["word"], w["correctForm"], "reviewer's word list")
        elif w["verdict"] == "JOINED":
            word_notes.append(f"{w['word']} → {w['correctForm']}: joined words, a known-join candidate (item 4)")
    for l in labels:
        if l["kind"] == "flagged" and l["sheet"] == "2" and str(l["verdict"]).startswith("TP"):
            right = l["correctForm"] if l["verdict"] == "TP_OTHER_FIX" else (
                l["suggestions"][0] if l["verdict"] == "TP1" else l["correctForm"] or (l["suggestions"][1:2] or [""])[0])
            if right and l["rule"] in ("ta-irv/lexicon.known-misspelling", "ta-irv/indicqa.lex.near-miss",
                                       "ta-irv/indicqa.lex.unknown"):
                curate(l["book"], l["ch"], l["v"], nfc(l["original"]), nfc(right), l["rule"])

    # ---- per rule ----
    per_rule = collections.defaultdict(collections.Counter)
    for l in labels:
        if l["kind"] in ("flagged", "candidate"):
            per_rule[l["rule"]][l["verdict"]] += 1
    summary = {"rules": {}, "wordList": {"rows": len(words), "curatedPairs": len(curated), "notes": word_notes}}
    for rule, cnt in sorted(per_rule.items()):
        tp = sum(n for k, n in cnt.items() if k.startswith("TP"))
        fp = sum(n for k, n in cnt.items() if k.startswith("FP"))
        summary["rules"][rule] = {"labelled": sum(cnt.values()), "tp": tp, "fp": fp, "house": cnt.get("HOUSE", 0),
                                  "unsure": cnt.get("UNSURE", 0), "precision": tp / (tp + fp) if tp + fp else None,
                                  "verdicts": dict(cnt)}

    (out / "human_labels.jsonl").write_text("".join(json.dumps(l, ensure_ascii=False) + "\n" for l in labels),
                                            encoding="utf-8", newline="\n")
    with (out / "lexicon_curated.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        w = csv.writer(handle, lineterminator="\n")
        w.writerow(["Book", "Chapter", "Verse", "Issue Type", "Priority Category", "Severity", "Confidence", "Original Tamil",
                    "Suggested Correction", "Explanation", "Source / Reference Note", "Reviewer Decision Needed", "Status"])
        w.writerows(curated)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")

    md = ["# ta-irv round 3 (2026-10-13): what the reviewer's verdicts say", "",
          "Converter output; numbers are the reviewer's verdicts on this round only. The benchmark",
          "(`scripts/language_qa_benchmark.py --human-labels benchmark/human`) is the score of record.", "",
          "| rule | kind | labelled | TP | FP | house | precision |", "|---|---|---|---|---|---|---|"]
    kinds = {l["rule"]: l["kind"] for l in labels if l["kind"] in ("flagged", "candidate")}
    for rule, s in summary["rules"].items():
        p = "" if s["precision"] is None else f"{s['precision']:.0%}"
        md.append(f"| `{rule}` | {kinds[rule]} | {s['labelled']} | {s['tp']} | {s['fp']} | {s['house']} | {p} |")
    md += ["", "## Word list (sheet 3)", "", f"{len(words)} rows; {len(curated)} new one-word pairs written to "
           "`lexicon_curated.csv` (word list and confirmed sheet-2 pairs).", ""] + [f"- {n}" for n in word_notes]
    md += ["", "## Reviewer notes on false alarms", ""]
    for l in labels:
        if l["kind"] in ("flagged", "candidate") and str(l["verdict"]).startswith("FP") and l.get("note"):
            md.append(f"- `{l['rule']}` {l['book'].upper()} {l['ch']}:{l['v']} «{nfc(l.get('original'))[:60]}»: {l['note']}")
    (out / "pack_changes.md").write_text("\n".join(md) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({r: (s["labelled"], s["tp"], s["fp"], s["house"]) for r, s in summary["rules"].items()},
                     ensure_ascii=False, indent=0))
    print("labels", len(labels), "curated", len(curated))
    for n in word_notes:
        print(" -", n)


if __name__ == "__main__":
    main()
