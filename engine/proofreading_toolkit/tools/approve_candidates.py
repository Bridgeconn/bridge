"""approve_candidates.py [code] : move candidates marked 'y' in profiles/<code>/candidates.tsv into the profile's
minority_forms, so build.py adds a row for each occurrence (with live whole-Bible counts)."""
import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project as P
code = sys.argv[1] if len(sys.argv) > 1 else (P.detect_language()["code"] or "generic").split("-")[0].lower()
d = os.path.join(P.ROOT, "profiles", code); pf = os.path.join(d, "profile.json"); prof = json.load(open(pf, encoding="utf-8"))
W = prof["word_chars"]; n = 0; have = {f["from"] for f in prof.setdefault("minority_forms", [])}
for ln in open(os.path.join(d, "candidates.tsv"), encoding="utf-8").read().splitlines()[1:]:
    p = ln.split("\t")
    if len(p) >= 5 and p[4].strip().lower() in ("y", "yes"):
        rare, common = p[0], p[1]
        rx = rf"(?<![{W}]){re.escape(rare)}(?![{W}])"
        if rx in have: continue
        prof["minority_forms"].append({"word": rx, "from": rx, "to": common, "type": "Possible typo", "severity": "Low", "confidence": "Medium",
                                       "reason": f"{rare} is a rare variant of {common} in this translation (approved candidate)."}); n += 1
json.dump(prof, open(pf, "w", encoding="utf-8"), ensure_ascii=False, indent=1); print(f"{n} approved forms added to {pf}")
