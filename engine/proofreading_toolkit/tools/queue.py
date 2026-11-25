"""Run queue: select a scope, run every book in it one after another, pause/stop/resume at any time.
  queue.py start <scope> [--new]   scope = all | OT | NT | GEN,EXO | GEN-DEU | MAT-JHN,ROM
  queue.py next                    -> prints NEXT <BOOK> <PT_BASE_OFFSET>, or PAUSED / STOPPED / FINISHED (exit 0/3/4/5)
  queue.py done <BOOK> [--usage in,cache_write,cache_read,out]   record a finished book (estimate used if no usage)
  queue.py skip <BOOK> <reason>
  queue.py pause | stop | resume   (or create a file named PAUSE or STOP in the output folder)
  queue.py status
State lives in <output_dir>/run_state.json, so a run survives a closed laptop or a new session."""
import sys, os, json, csv, glob, time
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project as P, cost
C = P.cfg(); OUT = C["output_dir"]; SP = os.path.join(OUT, "run_state.json")
now = lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def load(): return json.load(open(SP, encoding="utf-8")) if os.path.exists(SP) else None
def save(s): json.dump(s, open(SP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
def control(s):
    for f in ("STOP", "PAUSE"):
        if os.path.exists(os.path.join(OUT, f)): s["control"] = f.lower()
    return s.get("control", "run")
a = sys.argv[1:] or ["status"]; cmd = a[0]; s = load()
if cmd == "start":
    if s and any(b["status"] in ("pending", "running") for b in s["books"].values()) and "--new" not in a:
        sys.exit(f"A run is already in progress ({s['scope']}). Use 'queue.py resume', or 'queue.py start {a[1]} --new' to replace it.")
    books = P.expand_scope(a[1]); tgt, ref = P.books_available()
    missing = [b for b in books if b not in tgt]; books = [b for b in books if b in tgt]
    est = {b: cost.estimate(b) for b in books}
    s = {"scope": a[1], "created": now(), "control": "run", "language": P.detect_language(), "reference": C["reference_name"],
         "model": C.get("model"), "books": {b: {"status": "pending", "offset": 3600 * (i + 1), "no_reference": b not in ref,
         "est_tokens": sum(est[b][0].values()), "est_usd": round(est[b][1], 2)} for i, b in enumerate(books)}}
    save(s); [os.remove(os.path.join(OUT, f)) for f in ("PAUSE", "STOP") if os.path.exists(os.path.join(OUT, f))]
    tot = sum(v["est_usd"] for v in s["books"].values())
    print(f"Run created: {len(books)} books ({a[1]}). Estimated cost before starting: ${tot:,.2f} (assumed prices; see config.json).")
    if missing: print("Not in the target folder, left out:", " ".join(missing))
elif cmd == "next":
    if not s: sys.exit("No run. Use 'queue.py start <scope>'.")
    st = control(s); save(s)
    if st == "stop": print("STOPPED"); sys.exit(4)
    if st == "pause": print("PAUSED"); sys.exit(3)
    for b, v in s["books"].items():
        if v["status"] == "running": print(f"NEXT {b} {v['offset']} (resuming an unfinished book)"); sys.exit(0)
    for b, v in s["books"].items():
        if v["status"] == "pending":
            v["status"] = "running"; v["started"] = now(); save(s); print(f"NEXT {b} {v['offset']}"); sys.exit(0)
    print("FINISHED"); sys.exit(5)
elif cmd == "done":
    b = a[1].upper(); v = s["books"][b]
    p = os.path.join(OUT, b, f"{b}_QA_Issues.csv")
    rows = list(csv.reader(open(p, encoding="utf-8-sig")))[1:] if os.path.exists(p) else []
    sev = {x: sum(1 for r in rows if r[5] == x) for x in ("High", "Medium", "Low")}
    if "--usage" in a:
        i, cw, cr, o = map(int, a[a.index("--usage") + 1].split(",")); tok = {"input": i, "cache_write": cw, "cache_read": cr, "output": o}
        v.update(tokens=sum(tok.values()), usd=round(cost.usd(tok), 2), cost_basis="actual")
    else:
        tok, d = cost.estimate(b); v.update(tokens=sum(tok.values()), usd=round(d, 2), cost_basis="estimate")
    v.update(status="done", finished=now(), findings=len(rows), **sev)
    try: v["minutes"] = round((datetime.strptime(v["finished"], "%Y-%m-%d %H:%M:%S") - datetime.strptime(v["started"], "%Y-%m-%d %H:%M:%S")).seconds / 60, 1)
    except Exception: pass
    save(s); print(f"{b} done: {len(rows)} findings (H{sev['High']} M{sev['Medium']} L{sev['Low']}), ${v['usd']} ({v['cost_basis']})")
elif cmd == "skip":
    s["books"][a[1].upper()].update(status="skipped", reason=" ".join(a[2:]), finished=now()); save(s); print("skipped")
elif cmd in ("pause", "stop", "resume"):
    s["control"] = {"pause": "pause", "stop": "stop", "resume": "run"}[cmd]
    if cmd == "resume":
        for f in ("PAUSE", "STOP"):
            if os.path.exists(os.path.join(OUT, f)): os.remove(os.path.join(OUT, f))
    save(s); print(f"control = {s['control']}" + (" (takes effect after the book in progress is saved)" if cmd != "resume" else ""))
else:
    if not s: sys.exit("No run.")
    B = s["books"]; done = [v for v in B.values() if v["status"] == "done"]
    print(f"Scope {s['scope']} | control {control(s)} | done {len(done)}/{len(B)} | findings {sum(v.get('findings',0) for v in done):,} | "
          f"cost so far ${sum(v.get('usd',0) for v in done):,.2f} | remaining (est.) ${sum(v['est_usd'] for v in B.values() if v['status']!='done'):,.2f}")
    for b, v in B.items(): print(f"  {b} {v['status']}" + (f" {v.get('findings')} findings ${v.get('usd')}" if v["status"] == "done" else ""))
