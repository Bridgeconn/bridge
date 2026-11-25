"""Whole-Bible corpus of the target text (verse text only), cached in work_dir.
cnt(pattern) -> (whole Bible, New Testament) counts; show(pattern, books, limit) -> occurrences."""
import os, pickle, re, hashlib, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project as P
_c = P.cfg()
_files = P.book_files(_c["target_dir"])
_sig = hashlib.md5("|".join(f"{p}:{os.path.getmtime(p)}" for p in _files.values()).encode()).hexdigest()[:10]
_pk = os.path.join(_c["work_dir"], f"corpus_{_sig}.pkl")
if os.path.exists(_pk): C = pickle.load(open(_pk, "rb"))
else:
    C = {}
    for b, p in _files.items():
        bk, s, raw, V = P.parse(p); C[b] = (s, raw, V)
    pickle.dump(C, open(_pk, "wb"))
def cnt(pat):
    r = re.compile(pat); n = nt = 0
    for b, (s, raw, V) in C.items():
        for t in V.values():
            k = len(r.findall(t)); n += k
            if b in P.NT: nt += k
    return n, nt
def show(pat, books=None, lim=8):
    r = re.compile(pat); o = []
    for b in P.ORDER:
        if b not in C or (books and b not in books): continue
        for k, t in C[b][2].items():
            m = r.search(t)
            if m: o.append(f"{b} {k[0]}:{k[1]} …{t[max(0, m.start()-40):m.end()+40]}…")
    return o[:lim]
