"""q.py c 'pat1' 'pat2'  -> whole-Bible / NT counts
q.py s 'pat' [BOOK,BOOK|-] [limit]  -> occurrences
q.py v 'ISA 7:14' 'RUT 4:19'  -> verses of the target text"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from corpus import C, cnt, show
import project as P
m = sys.argv[1]
if m == "c": print(" | ".join(f"{p}: {cnt(p)[0]}/{cnt(p)[1]}" for p in sys.argv[2:]))
elif m == "v":
    for r in sys.argv[2:]:
        b, cv = r.split(); c, v = cv.split(":"); k = P.verse_keys_for(C[b][2], int(c), v)
        print(r, C[b][2].get(k, "?"))
else:
    bk = sys.argv[3].split(",") if len(sys.argv) > 3 and sys.argv[3] != "-" else None
    print("\n".join(show(sys.argv[2], bk, int(sys.argv[4]) if len(sys.argv) > 4 else 8)))
