"""make_profile.py [code] [--force] : draft a language profile from the project's own text.
Measures what the translation actually uses — script, letters, punctuation, quotation marks, digits, verse-final
marks — and finds CANDIDATE minority spellings: rare words that differ by one letter from a word used far more often.
Writes profiles/<code>/profile.json (status: DRAFT) and profiles/<code>/candidates.tsv. Claude then adds the language's
grammar, spelling, sandhi, register and punctuation rules (rules{}) and figures-of-speech notes; a native linguist
approves them and the status line records the review. Nothing is reported as an error until approved."""
import sys, os, re, json, collections, unicodedata
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project as P
from corpus import C
lang = P.detect_language(); code = (sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else (lang["code"] or "xx")).split("-")[0].lower()
d = os.path.join(P.ROOT, "profiles", code); os.makedirs(d, exist_ok=True); pf = os.path.join(d, "profile.json")
if os.path.exists(pf) and "--force" not in sys.argv: sys.exit(f"{pf} exists; use --force to redraft (your rules would be overwritten).")
text = " ".join(t for b in C for t in C[b][2].values())
script = P.detect_script(text); W = P.script_class(script)
punct = collections.Counter(ch for ch in text if unicodedata.category(ch).startswith("P"))
ends = collections.Counter(t.strip()[-1] for b in C for t in C[b][2].values() if t.strip())
quotes = [(a, b) for a, b in [("“", "”"), ("‘", "’"), ("«", "»"), ("„", "“"), ("‹", "›"), ("「", "」"), ("『", "』"), ('"', '"')] if punct[a] > 20]
digits = collections.Counter(unicodedata.name(ch).split()[0] for ch in text if ch.isdigit())
words = collections.Counter(re.findall(rf"[{W}]+", text))
# candidate minority spellings: rare word (<=5% of the pair) one edit away from a common word (>=20 uses)
common = {w: n for w, n in words.items() if n >= 20 and len(w) >= 4}
dele = collections.defaultdict(set)
for w in common:
    for i in range(len(w)): dele[w[:i] + w[i+1:]].add(w)
cand = []
for w, n in words.items():
    if n > 5 or len(w) < 4 or w in common: continue
    near = set(dele.get(w, ()))                                    # insertion in common word
    for i in range(len(w)): near |= dele.get(w[:i] + w[i+1:], set()) if w[:i] + w[i+1:] not in common else {w[:i] + w[i+1:]}
    near |= {c for i in range(len(w)) for c in dele.get(w[:i] + w[i+1:], ())}
    best = max(near, key=lambda c: common.get(c, 0), default=None)
    if best and common.get(best, 0) >= 20 * n and best != w and len(w) >= 5 and w[0] == best[0] and w[-1:] == best[-1:]:
        cand.append((w, best, n, common[best]))      # same first and last letter: spelling variant, not a different word
cand.sort(key=lambda x: -x[3])
prof = json.load(open(os.path.join(P.ROOT, "profiles", "generic", "profile.json"), encoding="utf-8"))
prof.update(code=code, name=lang["name"] or code, script=script, word_chars=W,
            status=f"DRAFT made by make_profile.py from the project text — rules not yet reviewed by a native linguist.",
            quote_pairs=[list(q) for q in quotes] or prof["quote_pairs"],
            verse_end_ok="[" + re.escape("".join(ch for ch, n in ends.most_common(12) if not ch.isalnum() and n >= 5)) + "]$",
            measured={"letters_distinct": len({ch for ch in text if ch.isalpha()}), "punctuation": dict(punct.most_common(30)),
                      "verse_final_characters": dict(ends.most_common(15)), "digit_scripts": dict(digits), "word_types": len(words)},
            candidate_minority=cand[:300])
prof["rules"] = {"TO_FILL": ["Claude drafts: spelling, grammar/agreement, case or particles, word division (sandhi / clitics / compounds), register, "
                 "punctuation and quotation, numbers, names and key terms — from its knowledge of the language and any style guide the team supplies.",
                 "Native linguist reviews every rule; mark the status line 'reviewed by <name>, <date>'."]}
json.dump(prof, open(pf, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
with open(os.path.join(d, "candidates.tsv"), "w", encoding="utf-8") as f:
    f.write("rare form\tcommon form\trare count\tcommon count\tapprove (y/n)\n")
    for a, b, n, m in cand: f.write(f"{a}\t{b}\t{n}\t{m}\t\n")
print(f"Draft profile {pf}: script {script}, quotes {quotes}, {len(cand)} candidate minority spellings (see candidates.tsv)")
