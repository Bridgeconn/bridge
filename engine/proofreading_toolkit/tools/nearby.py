"""nearby.py BOOK C:V [--window N] [--find 'regex' ...]
Before reporting anything as MISSING (Possible missed source word, Omission, Verse boundary), check whether
the meaning is carried by a neighbouring verse. Translations often move a clause across a verse boundary,
merge verses, or say in v.5 what the reference says in v.4 — that is not an omission.

Prints, for verses C:V-N … C:V+N (crossing chapter boundaries):
  1. the reference and the target side by side, with each verse's length against the book's usual ratio
     (a short verse next to a long one = content moved, not lost);
  2. key-term anchors: every Biblical Term the team's list places in the verse, with WHERE its approved
     rendering actually occurs in the window (this verse / another verse / not found);
  3. numbers and the reference's proper names: in which target verse their numbers appear;
  4. --find: where each target-language pattern you suspect is missing occurs in the window and in the
     rest of the chapter.
Verdict words follow Bridge's cross-verse states: in-verse, found_another_verse, split_across_verses, not_found.
Only a not_found after reading the window may be reported as missing."""
import sys, os, re, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project as P
from corpus import C
a = sys.argv[1:]
book = a[0].upper(); ch, vs = a[1].split(":"); ch = int(ch); vs = vs.split("-")[0]
N = int(a[a.index("--window") + 1]) if "--window" in a else 3
finds = [a[i + 1] for i, x in enumerate(a) if x == "--find"]
cfg = P.cfg(); W = P.profile()["word_chars"]
Vt = C[book][2]; Ve = P.parse(P.reference(book))[3]
keys = list(Vt); here = P.verse_keys_for(Vt, ch, vs)
if not here: sys.exit(f"{book} {ch}:{vs} not in the target")
i = keys.index(here); win = keys[max(0, i - N): i + N + 1]
def ref_text(k):
    c, v = k
    if "-" in v:
        lo, hi = int(v.split("-")[0]), int(re.sub(r"\D", "", v.split("-")[1]))
        return " ".join(f"[{x}] " + Ve.get((c, str(x)), "") for x in range(lo, hi + 1))
    return Ve.get(k, "")
ratios = [len(t) / len(ref_text(k)) for k, t in Vt.items() if ref_text(k)]
med = statistics.median(ratios) if ratios else 1
print(f"== {book} {ch}:{vs}, window ±{N} — target/reference length relative to the book's usual ratio ({med:.2f})")
for k in win:
    r = ref_text(k); t = Vt[k]; rel = (len(t) / len(r) / med) if r else 0
    flag = "  <-- SHORT" if rel and rel < 0.7 else ("  <-- LONG" if rel > 1.4 else "")
    mark = ">>" if k == here else "  "
    print(f"{mark}{k[0]}:{k[1]}  x{rel:.2f}{flag}\n    REF: {r}\n    TGT: {t}")
# ---- key-term anchors from the team's Biblical Terms list
d = cfg["target_dir"]; pbp, trp = os.path.join(d, "ProjectBiblicalTerms.xml"), os.path.join(d, "TermRenderings.xml")
if os.path.exists(pbp) and os.path.exists(trp):
    pb = open(pbp, encoding="utf-8-sig").read(); tr = open(trp, encoding="utf-8-sig").read()
    rend = {m[0]: [r.strip() for r in re.sub(r"\(.*?\)", "", m[1]).split("||") if r.strip()]
            for m in re.findall(r'<TermRendering Id="([^"]*)"[^>]*>\s*<Renderings>([^<]*)</Renderings>', tr)}
    num = P.ORDER.index(book) + 1
    lo, hi = (int(here[1].split("-")[0]), int(re.sub(r"\D", "", here[1].split("-")[-1]))) if "-" in here[1] else (int(re.sub(r"\D", "", here[1])),) * 2
    targets = {f"{num:03d}{ch:03d}{v:03d}" for v in range(lo, hi + 1)}
    def rx(r): return re.compile(rf"(?<![{W}])" + r"\s+".join(re.escape(w).replace(r"\*", f"[{W}]*") for w in r.split()) + rf"(?![{W}])")
    print("== key terms the team's list places in this verse")
    shown = 0
    for m in re.finditer(r'<Term Id="([^"]*)">(.*?)</Term>', pb, re.S):
        tid, body = m.group(1), m.group(2)
        if not any(v[:9] in targets for v in re.findall(r"<Verse>(\d+)</Verse>", body)): continue
        gloss = (re.search(r"<Gloss>([^<]*)", body) or [0, ""])[1]; R = rend.get(tid, [])
        if not R: print(f"  {gloss or tid}: no approved rendering in the list"); continue
        where = [f"{k[0]}:{k[1]}" for k in win if any(rx(r).search(Vt[k]) for r in R)]
        state = ("in-verse" if f"{here[0]}:{here[1]}" in where else "found_another_verse" if where else "not_found")
        print(f"  {gloss or tid} [{' | '.join(R[:4])}] → {state}" + (f" ({', '.join(where)})" if where else "")); shown += 1
    if not shown: print("  (none listed)")
# ---- numbers and proper names in the reference verse
rv = ref_text(here)
nums = sorted({x.replace(",", "") for x in re.findall(r"\d[\d,]*", rv)})
if nums:
    print("== numbers in the reference verse → target verses that carry them")
    for n in nums: print(f"  {n}: {[f'{k[0]}:{k[1]}' for k in win if n in re.sub(r'[ ,]', '', Vt[k])] or 'not_found (may be written in words)'}")
names = sorted({w for w in re.findall(r"(?<![.?!“‘] )(?<!^)\b[A-Z][a-z]{2,}\b", rv) if w not in ("The", "And", "But", "For", "Then", "Lord", "God", "When", "Now")})
if names: print("== proper names in the reference verse (find their target spelling with q.py, then --find it):", ", ".join(names))
# ---- --find patterns
for p in finds:
    hits = [f"{k[0]}:{k[1]}" for k in win if re.search(p, Vt[k])]
    rest = [f"{k[0]}:{k[1]}" for k in keys if k[0] in (ch, ch - 1, ch + 1) and k not in win and re.search(p, Vt[k])]
    state = "in-verse" if f"{here[0]}:{here[1]}" in hits else ("split_across_verses" if len(hits) > 1 else "found_another_verse" if hits else "not_found")
    print(f"== --find {p}: {state}; window {hits or '-'}; elsewhere in chapters {ch-1}-{ch+1}: {rest[:10] or '-'}")
print("Report as missing only what is not_found after reading the window; if found_another_verse, report a Verse boundary (Low/Medium) only when the move changes the sense, else nothing.")
