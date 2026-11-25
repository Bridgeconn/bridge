"""build.py BOOK : verify a findings file and turn it into located rows. Must end with 'fail: 0'.
Reads rows/rows_<book>.py (one R(...) per finding, see templates/rows_template.py). Adds automatic rows:
double spaces (one per verse) and the profile's minority spellings (live whole-Bible counts).
Every Original string is located character for character in the verse, heading, introduction or footnote."""
import sys, os, re, collections, importlib.util
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project as P
BOOK = (sys.argv[1] if len(sys.argv) > 1 else "PHP").upper()
CFG = P.cfg(); PROF = P.profile(); W = PROF["word_chars"]
ROWS_DIR = os.environ.get("QA_ROWS", os.path.join(CFG["work_dir"], "rows"))
spec = importlib.util.spec_from_file_location("rows", os.path.join(ROWS_DIR, f"rows_{BOOK.lower()}.py"))
RM = importlib.util.module_from_spec(spec); spec.loader.exec_module(RM); ROWS = RM.ROWS
tp = P.target(BOOK)
try: ep = P.reference(BOOK)
except FileNotFoundError: ep = None
full = open(tp, encoding="utf-8-sig", newline="").read()
lines = [l.rstrip("\r") for l in full.split("\n")]
# ---- segments exactly as Paratext addresses them: (c,"0") = \c (for ch.1 from \id) up to first \v; (c,v) = \v up to next \v/\c
seg = {}; order = []; cur = None; chapter = 1
def _start(k):
    global cur
    cur = k; seg[k] = []; order.append(k)
_start((1, "0"))
for ln in lines:
    ln = ln.rstrip()
    if ln == "": continue
    m = re.match(r"\\c\s+(\d+)", ln)
    if m:
        chapter = int(m.group(1))
        if chapter > 1: _start((chapter, "0"))
        seg[cur].append(ln); continue
    parts = re.split(r"(?=\\v\s+\S+)", ln)          # \v may follow a paragraph marker on the same line
    for i, part in enumerate(parts):
        mv = re.match(r"\\v\s+(\S+)", part)
        if mv: _start((chapter, mv.group(1)))
        if part.strip(): seg[cur].append(part.strip() if i else part)
seg = {k: " ".join(v) + " " for k, v in seg.items()}
verses = {k: t for k, t in seg.items() if k[1] != "0"}
def fv(ch, vs):
    for (c, v) in verses:
        if c == ch and (v == str(vs) or ("-" in v and str(vs).isdigit() and int(v.split("-")[0]) <= int(vs) <= int(re.sub(r"\D", "", v.split("-")[1])))): return (c, v)
def prev(k): return order[order.index(k) - 1]
def body_end(t):
    m = re.search(r" \\(?:s\d?|ms\d?|mr|r|d|sp|qa)\b", t); return m.start() + 1 if m else len(t)
def flex(o): return re.compile(r"\s+".join(re.escape(w) for w in o.split()))
def locate(ch, vs, orig):
    marker = re.match(r"\\[a-z0-9]+\*? ?", orig); plain = (orig[marker.end():] if marker else orig).split("\n")[0]
    if ch == "Intro":
        t = seg[(1, "0")]; m = flex(plain).search(t)
        return ((1, "0"), m.start(), m.group(0), "Introduction") if m else None
    key = fv(ch, vs)
    if key is None: return None
    if not marker:
        t = seg[key]; m = flex(plain).search(t)
        if m:
            pre = t[:m.start()]; loc = "Verse text"
            if pre.rfind("\\f ") > pre.rfind("\\f*"): loc = "Footnote"
            elif pre.rfind("\\x ") > pre.rfind("\\x*"): loc = "Cross-reference"
            elif m.start() >= body_end(t): loc = "Heading"
            return (key, m.start(), m.group(0), loc)
    pk = prev(key); t = seg[pk]; hs = body_end(t) if pk[1] != "0" else 0
    m = flex(plain).search(t, hs)
    if m: return (pk, m.start(), m.group(0), "Heading" if (pk[1] != "0" or pk[0] > 1 or "\\c 1" in t[:m.start()]) else "Introduction")
    return None
out = []; stats = collections.Counter(); rows = list(ROWS)
# ---- automatic: double spaces
for k, t in verses.items():
    tv = t[:body_end(t)]; n = len(re.findall(r"(?<=\S)  +(?=\S)", tv))
    if n:
        m = re.search(r"\S+  +\S+", tv); o = m.group(0); fix = re.sub(r"  +", " ", o)
        if "\\" in o or o[0].isdigit():
            m2 = re.search(rf"[{W}‘“«][^\\]{{3,25}}?(?= )", tv[m.end():]); o = m2.group(0) if m2 else o; fix = ""
        rows.append((k[0], k[1].split("-")[0], "Punctuation", "Punctuation", "Low", "High", o, fix,
            f"Extra spaces. This verse has {n} place{'s' if n > 1 else ''} where two spaces stand instead of one; the flagged words show the first. A find-and-replace of two spaces by one clears all of them.",
            "Not a source matter.", "No"))
# ---- automatic: minority spellings (profile module or JSON list)
if not getattr(RM, "NO_MINORITY", False):
    from corpus import cnt
    auth = {((str(r[0]), str(r[1])), r[6]) for r in ROWS}
    authored = {(k, w) for k in verses for (kk, w) in auth if kk[0] == str(k[0]) and kk[1] == k[1].split("-")[0]}
    mod = PROF.get("minority_module")
    if mod and os.path.exists(os.path.join(PROF["_dir"], mod)):
        sp = importlib.util.spec_from_file_location("minority", os.path.join(PROF["_dir"], mod)); MM = importlib.util.module_from_spec(sp); sp.loader.exec_module(MM)
        rows += MM.rows_for(verses, body_end, lambda p: (cnt(p)[0], cnt(p)[1], 0), authored)
    for f in PROF.get("minority_forms", []):          # {"word": regex, "from": a, "to": b, "type","severity","confidence","reason"}
        for k, t in verses.items():
            tv = t[:body_end(t)]; m = re.search(f["word"], tv)
            if not m or (k, m.group(0)) in authored: continue
            new = re.sub(f["from"], f["to"], m.group(0)); nw, nr = cnt(f["from"])[0], cnt(f["to"])[0]
            if new != m.group(0) and nr >= 3 * max(1, nw):
                rows.append((k[0], k[1].split("-")[0], f.get("type", "Possible typo"), "Typo", f.get("severity", "Low"), f.get("confidence", "Medium"),
                             m.group(0), new, f"{f.get('reason','Minority spelling.')} Whole-Bible verse text: {nr:,} against {nw:,}.", "Spelling matter; not a source question.", "No"))
for r in rows:
    ch, vs, typ, cat, sev, conf, orig, sug, expl, ref, dec = r
    L = locate(ch, vs, orig)
    if not L: stats["fail"] += 1; print("FAIL", ch, vs, orig[:60]); continue
    akey, start, sel, loc = L; stats[loc] += 1
    lkey = fv(ch, vs) if ch != "Intro" else None
    out.append({"Book": BOOK, "Chapter": ch, "Verse": (lkey[1] if lkey else ""), "Issue Type": typ, "Priority Category": cat,
                "Severity": sev, "Confidence": conf, "Original Text": (orig if orig.startswith("\\") else sel),
                "Suggested Correction": sug, "Explanation": expl, "Reference Note": ref, "Reviewer Decision Needed": dec,
                "Status": "Open", "Location": loc, "Paratext Anchor": f"{BOOK} {akey[0]}:{akey[1]}",
                "_akey": akey, "_start": start, "_sel": sel, "_loc": loc, "_key": lkey})
out.sort(key=lambda d: (order.index(d["_akey"]), d["_start"]))
seen = set(); _o = []; overlaps = []
for d in out:
    k = (d["Chapter"], d["Verse"], d["Original Text"], d["Issue Type"])
    if k in seen: continue
    seen.add(k); _o.append(d)
out = _o
# overlapping pins in one segment (Paratext shows them stacked; usually narrow or drop the hand-written one)
by = collections.defaultdict(list)
for d in out: by[d["_akey"]].append(d)
for k, L in by.items():
    for a in L:
        for b in L:
            if a is not b and a["_start"] <= b["_start"] < a["_start"] + len(a["_sel"]) and id(a) < id(b): overlaps.append((k, a["_sel"][:30], b["_sel"][:30]))
stats["fail"] += 0
if __name__ == "__main__":
    print(len(out), "rows |", dict(stats)); print("severity:", dict(collections.Counter(d["Severity"] for d in out)))
    for o in overlaps: print("OVERLAP", o)
