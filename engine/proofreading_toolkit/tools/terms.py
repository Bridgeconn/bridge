"""terms.py BOOK : the project's Paratext Biblical Terms list. Leads only.
Every listed term occurrence in the book with no approved rendering in the verse; terms rendered more than one way."""
import sys, os, re, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project as P
from corpus import C
book = sys.argv[1].upper(); c = P.cfg(); W = P.profile()["word_chars"]; d = c["target_dir"]
pb, tr = os.path.join(d, "ProjectBiblicalTerms.xml"), os.path.join(d, "TermRenderings.xml")
if not (os.path.exists(pb) and os.path.exists(tr)): sys.exit("No ProjectBiblicalTerms.xml / TermRenderings.xml in the target folder: term check skipped.")
pb = open(pb, encoding="utf-8-sig").read(); tr = open(tr, encoding="utf-8-sig").read()
num = P.ORDER.index(book) + 1
rend = {m[0]: [r.strip() for r in re.sub(r"\(.*?\)", "", m[1]).split("||") if r.strip()]
        for m in re.findall(r'<TermRendering Id="([^"]*)"[^>]*>\s*<Renderings>([^<]*)</Renderings>', tr)}
def rx(r): return re.compile(rf"(?<![{W}])" + r"\s+".join(re.escape(w).replace(r"\*", f"[{W}]*") for w in r.split()) + rf"(?![{W}])")
V = C[book][2]; miss = []; used = collections.defaultdict(collections.Counter); norend = collections.Counter()
for m in re.finditer(r'<Term Id="([^"]*)">(.*?)</Term>', pb, re.S):
    tid, body = m.group(1), m.group(2); gloss = (re.search(r"<Gloss>([^<]*)", body) or [0, ""])[1]
    refs = [r for r in re.findall(r"<Verse>(\d+)</Verse>", body) if int(r[:3]) == num]
    if not refs: continue
    if not rend.get(tid): norend[f"{tid} ({gloss})"] += len(refs); continue
    for r in refs:
        k = P.verse_keys_for(V, int(r[3:6]), int(r[6:9]))
        if not k: continue
        hit = [p for p in rend[tid] if rx(p).search(V[k])]
        if hit: used[f"{tid} ({gloss})"][hit[0]] += 1
        else: miss.append(f"{k[0]}:{k[1]}\t{tid} ({gloss})\tapproved: {' | '.join(rend[tid][:6])}\t{V[k][:100]}")
print(f"== {book}: listed term occurrences with no approved rendering in the verse: {len(miss)}"); print("\n".join(miss))
print("\n== terms rendered more than one way in this book")
for k, v in used.items():
    if len(v) > 1: print(k, dict(v))
print("\n== terms listed for this book with no approved rendering at all:", len(norend))
