"""Mechanical sweeps for one book, any language. Output is LEADS for the reader, not findings.
usage: python3 -I sweep.py BOOK
Universal checks (from Unicode and USFM) + the language profile's own lead patterns + the project's
Paratext data (SpellingStatus.xml wrong words, BookNames.xml) + comparison with the reference Bible."""
import sys, os, re, unicodedata, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project as P
from corpus import C, cnt
book = sys.argv[1].upper(); prof = P.profile(); c = P.cfg(); W = prof["word_chars"]
s, raw, V = C[book]
body = s[s.index("\\c 1"):] if "\\c 1" in s else s
print(f"== {book} ({P.NAMES[book]}) — language profile: {os.path.basename(prof['_dir'])}")

# ---------- 1. universal script / encoding checks (work for every script)
def is_mark(ch): return unicodedata.category(ch) in ("Mn", "Mc")
print("NFC normalised:", unicodedata.normalize("NFC", s) == s)
hits = collections.defaultdict(list)
for k, t in V.items():
    for i, ch in enumerate(t):
        if is_mark(ch):
            if i == 0 or not (t[i-1].isalpha() or is_mark(t[i-1]) or t[i-1] in "\u200c\u200d"): hits["mark with no base letter"].append((k, t[max(0,i-3):i+3]))
            elif t[i-1] == ch: hits["same mark typed twice"].append((k, t[max(0,i-3):i+3]))
            if "VIRAMA" in unicodedata.name(ch, "") and i + 1 < len(t) and is_mark(t[i+1]) and "VIRAMA" not in unicodedata.name(t[i+1], ""):
                hits["virama followed by vowel sign"].append((k, t[max(0,i-3):i+3]))
    for w in re.findall(r"\S+", t):
        scr = {unicodedata.name(ch, "X ").split()[0] for ch in w if ch.isalpha()}
        if len(scr) > 1: hits["mixed scripts in one word"].append((k, w))
    if prof["_lang"]["script"] not in ("Latin", None) and re.search(r"[A-Za-z]", t): hits["Latin letters in verse text"].append((k, re.search(r"[A-Za-z]+", t).group(0)))
    for name, rx in (("ZWJ/ZWNJ", "[\u200c\u200d]"), ("no-break / zero-width space", "[\u00a0\u200b\u2060\ufeff]"),
                     ("space before punctuation", r" [,.;:?!](?!\d)"), ("doubled punctuation", r"[,;:]{2,}|\.\.(?!\.)"),
                     ("straight quote", "[\"']"), ("digit", r"\d")):
        for m in re.finditer(rx, t): hits[name].append((k, t[max(0,m.start()-6):m.end()+6])); break
for name, L in hits.items(): print(f"{name}: {len(L)}", [f"{k[0]}:{k[1]} {w}" for k, w in L[:8]])
ds = re.findall(r"\S+  +\S+", body); print("double spaces:", len(ds), ds[:5])
if prof.get("digits", {}).get("native"):
    vt = " ".join(V.values()); nd = len(re.findall(f"[{prof['digits']['native']}]", vt)); ad = len(re.findall(r"[0-9]", vt))
    print(f"native digits {nd} / ASCII digits {ad} (profile policy: {prof['digits']['policy']})")

# ---------- 2. punctuation, quotes, markers
ends = [f"{k[0]}:{k[1]}" for k, t in V.items() if not re.search(prof["verse_end_ok"], t)]
print("verses with no end punctuation:", len(ends), ends[:20])
for a, b in prof["quote_pairs"]: print(f"quotes {a}{b}: {body.count(a)} / {body.count(b)}")
for a, b in (("\\f ", "\\f*"), ("\\x ", "\\x*"), ("\\wj ", "\\wj*")): print(f"marker pair {a.strip()}: {body.count(a)} / {body.count(b)}")
print("verse bridges:", [f"{c_}:{v}" for c_, v in V if "-" in v])
order = [(c_, int(re.sub(r"\D.*", "", v) or 0)) for c_, v in V]
print("verse order problems:", [f"{a[0]}:{a[1]}" for a, b in zip(order, order[1:]) if b <= a and b[0] == a[0]][:10])
print("empty verses:", [f"{k[0]}:{k[1]}" for k, t in V.items() if not t.strip()])

# ---------- 3. language profile lead patterns
if prof.get("lead_patterns"):
    print("== language-specific leads (profile)")
    for name, pat in prof["lead_patterns"].items():
        h = [(k, m.group(0)) for k, t in V.items() for m in re.finditer(pat, t) if m.group(0) not in prof.get("exceptions", [])]
        if h: print(f"  {name}: {len(h)} in book | {cnt(pat)[0]} in whole Bible", [f"{k[0]}:{k[1]} {w}" for k, w in h[:6]])

# ---------- 4. repeated words / phrases
print("== repeated word")
for k, t in V.items():
    for m in re.finditer(rf"(?<![{W}])([{W}]{{2,}})[ ,]+\1(?![{W}])", t): print(f"  {k[0]}:{k[1]} {m.group(0)}")
print("== repeated 4-word phrase in a verse or the next verse")
ks = list(V)
for i, k in enumerate(ks):
    w = V[k].split(); nxt = V[ks[i+1]] if i + 1 < len(ks) and ks[i+1][0] == k[0] else ""
    for j in range(len(w) - 3):
        ph = " ".join(w[j:j+4])
        if V[k].count(ph) > 1 or (nxt and ph in nxt): print(f"  {k[0]}:{k[1]} «{ph}»" + (" (also next verse)" if nxt and ph in nxt else "")); break

# ---------- 5. against the reference Bible
print(f"== against the reference ({c['reference_name']})")
try:
    Ve = P.parse(P.reference(book))[3]; rat = []
    for (ch, v), t in V.items():
        vs = [v] if "-" not in v else [str(i) for i in range(int(v.split("-")[0]), int(re.sub(r"\D", "", v.split("-")[1])) + 1)]
        e = " ".join(Ve.get((ch, x), "") for x in vs)
        if e.strip(): rat.append((len(t) / max(1, len(e)), f"{ch}:{v}"))
    rat.sort(); med = rat[len(rat)//2][0]
    print(f"  length ratio (characters) median {med:.2f}; shortest", [f"{k} {r/med:.2f}x" for r, k in rat[:6]], "longest", [f"{k} {r/med:.2f}x" for r, k in rat[-6:]])
    print("  verses in reference missing from target:", [f"{a}:{b}" for a, b in Ve if not P.verse_keys_for(V, a, b)][:30])
    print("  verse numbers in target not in reference (check what fills them):", [f"{a}:{b}" for a, b in V if "-" not in b and (a, b) not in Ve][:30])
    se = open(P.reference(book), encoding="utf-8-sig").read()
    cntm = lambda x, rx: len(re.findall(rx, x))
    RH, RQ, RF = r"\\s\d? ", r"\\q\d?\b", r"\\f "
    print(f"  headings target {cntm(body, RH)} / reference {cntm(se, RH)} | poetry lines {cntm(body, RQ)} / {cntm(se, RQ)} | footnotes {cntm(body, RF)} / {cntm(se, RF)}")
except FileNotFoundError as ex: print("  ", ex)

# ---------- 6. project's Paratext data
ss = os.path.join(c["target_dir"], "SpellingStatus.xml")
if os.path.exists(ss):
    x = open(ss, encoding="utf-8-sig").read()
    wrong = re.findall(r'<Status Word="([^"]+)" State="W"\s*/?>\s*(?:<Correction>([^<]*)</Correction>)?', x)
    print(f"== words the team marked wrong in Paratext ({len(wrong)} listed) found in this book")
    for a, b in wrong:
        n = len(re.findall(rf"(?<![{W}]){re.escape(a)}(?![{W}])", s))
        if n: print(f"  {a} → {b or '?'}: {n}")
bn = os.path.join(c["target_dir"], "BookNames.xml")
if os.path.exists(bn):
    x = open(bn, encoding="utf-8-sig").read(); names = set()
    for m in re.finditer(r'abbr="([^"]*)" short="([^"]*)" long="([^"]*)"', x): names.update(y.strip().rstrip(".") for y in m.groups() if y.strip())
    intro = s[:s.index("\\c 1")] if "\\c 1" in s else ""
    refs = re.findall(rf"((?:[1-3] ?)?[{W}][{W}. ]*?)\.? ?\d+[:.]\d+", intro + " ".join(re.findall(r"\\(?:r|xt|ior|fr|ft) [^\n\\]*", s)))
    odd = sorted({r.strip() for r in refs if r.strip().rstrip(".") and not any(r.strip().rstrip(".").endswith(n) for n in names)})
    print("== reference-like strings whose book name is not in BookNames.xml:", odd[:30])

# ---------- 7. introduction
if "\\c 1" in s:
    intro = s[:s.index("\\c 1")]; last = max(ch for ch, _ in V)
    vmax = {ch: max(int(re.sub(r"\D", "", v.split("-")[-1]) or 0) for cc, v in V if cc == ch) for ch in range(1, last + 1)}
    print("== introduction")
    for m in re.finditer(r"(\d+):(\d+)", intro):
        ch, v = int(m.group(1)), int(m.group(2))
        if ch > last or v > vmax.get(ch, 0): print("  reference outside this book (check it names another book):", m.group(0), "…", intro[max(0, m.start()-25):m.start()].replace("\n", " "))
    print("  outline lines:", re.findall(r"\\io\d? ([^\n]*)", intro))

# ---------- 8. candidate minority spellings from the profile builder (if any)
cand = prof.get("candidate_minority", [])
if cand:
    print("== candidate minority spellings found in this book (from make_profile.py; need approval)")
    for rare, common, nr, nc in cand:
        n = len(re.findall(rf"(?<![{W}]){re.escape(rare)}(?![{W}])", body))
        if n: print(f"  {rare} ({nr}x in Bible) vs {common} ({nc}x): {n} here")
