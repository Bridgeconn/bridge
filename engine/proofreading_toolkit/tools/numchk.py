"""numchk.py BOOK : verses whose digit numbers in the target do not all appear among the reference verse's numbers.
Reference numbers are read from digits and, for an English reference, from number words. Leads only."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project as P
b = sys.argv[1].upper()
Vt = P.parse(P.target(b))[3]; Ve = P.parse(P.reference(b))[3]
W = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
W.update({"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90})
def nums(t):
    s = {int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*\d|\d", t)}
    cur = tot = 0; run = False
    for w in re.findall(r"[a-z]+", t.lower().replace("-", " ")) + ["x"]:
        if w in W: cur += W[w]; run = True
        elif w == "hundred" and run: cur *= 100
        elif w == "thousand" and run: tot += cur * 1000; cur = 0
        elif w == "and" and run: continue
        else:
            if run: s.add(tot + cur)
            cur = tot = 0; run = False
    return s
n = 0
for k, t in Vt.items():
    found = [int(re.sub(r"[ ,]", "", x)) for x in re.findall(r"\d[\d, ]*\d|\d", t)]
    if not found: continue
    e = nums(Ve.get(k, Ve.get((k[0], k[1].split("-")[0]), "")))
    miss = [x for x in found if x not in e]
    if miss: n += 1; print(f"{k[0]}:{k[1]}", miss, "| reference:", sorted(e))
print(f"-- {n} verse(s) to check")
