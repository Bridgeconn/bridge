"""merge_notes.py [live notes file] : rebuild the cumulative Paratext notes file in output_dir.
Keeps every comment of the live file (replies and resolutions survive) and adds each book's notes not yet present."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project as P
c = P.cfg(); root = c["output_dir"]; live = sys.argv[1] if len(sys.argv) > 1 else None
name = f"Notes_{c['notes_user']}.xml"
def blocks(p): return re.findall(r"  <Comment .*?</Comment>", open(p, encoding="utf-8-sig").read().replace("\r\n", "\n"), re.S)
def sig(b):
    g = lambda pat: (re.search(pat, b, re.S) or [None, ""])[1].strip()
    return (g(r'VerseRef="([^"]*)"'), g(r"<SelectedText>(.*?)</SelectedText>"), g(r"<bold>(\[AI-QA[^<]*)</bold>"), g(r"Original:</bold>(.*?)</p>"))
out = []; seen = set(); threads = set(); rep = []
if live and os.path.exists(live):
    for b in blocks(live): out.append(b); seen.add(sig(b)); threads.add(re.search(r'Thread="([^"]*)"', b)[1])
kept = len(out)
for bk in P.ORDER:
    p = os.path.join(root, bk, f"{bk}_notes_only.xml")
    if not os.path.exists(p): continue
    n = 0
    for b in blocks(p):
        t = re.search(r'Thread="([^"]*)"', b)[1]
        if sig(b) in seen: continue
        assert t not in threads, f"thread id collision {t} in {bk}"
        out.append(b); seen.add(sig(b)); threads.add(t); n += 1
    rep.append(f"{bk} +{n}")
xml = '<?xml version="1.0" encoding="utf-8"?>\n<CommentList>\n' + "\n".join(out) + "\n</CommentList>"
open(os.path.join(root, name), "wb").write(b"\xef\xbb\xbf" + xml.replace("\n", "\r\n").encode("utf-8"))
print(f"{name}: kept {kept} from live file | added {', '.join(rep)} | total {len(out)}")
