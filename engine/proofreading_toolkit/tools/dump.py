"""dump.py BOOK 1 3      -> target text of chapters 1-3 (headings kept, paragraph-only lines dropped)
dump.py BOOK intro      -> book introduction
dump.py BOOK ref 5:3 5:4-6   -> reference-Bible verses
dump.py BOOK both 5     -> chapter 5 verse by verse: target, then reference"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project as P
b = sys.argv[1].upper(); mode = sys.argv[2]
if mode in ("ref", "esv"):
    Ve = P.parse(P.reference(b))[3]
    for r in sys.argv[3:]:
        c, v = r.split(":")
        vs = range(int(v.split("-")[0]), int(v.split("-")[1]) + 1) if "-" in v else [v]
        print(r, " ".join(f"[{i}] " + Ve.get((int(c), str(i)), "?") for i in vs) if "-" in v else Ve.get((int(c), v), "?"))
    sys.exit()
s = open(P.target(b), encoding="utf-8-sig").read().replace("\r\n", "\n")
if mode == "intro": print(s[:s.index("\\c 1")] if "\\c 1" in s else s[:3000]); sys.exit()
if mode == "both":
    c = int(sys.argv[3]); Vt = P.parse(P.target(b))[3]; Ve = P.parse(P.reference(b))[3]
    for (cc, v), t in Vt.items():
        if cc == c: print(f"{c}:{v} T: {t}\n{c}:{v} R: {Ve.get((c, v.split('-')[0]), '?')}\n")
    sys.exit()
a, z = int(mode), int(sys.argv[3])
i = s.index(f"\\c {a}"); j = s.find(f"\\c {z+1}\n"); t = s[i:j if j > 0 else None]
t = re.sub(r"\n\\(p|m|b|q\d?|pi\d?)\s*(?=\n)", "", t); t = re.sub(r"\\v ", "", t); t = re.sub(r"\\wj\*?\s?", "", t)
print(t)
