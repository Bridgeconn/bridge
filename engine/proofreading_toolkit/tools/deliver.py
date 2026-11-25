"""deliver.py BOOK : workbook, CSV and Paratext notes for one book (from build.py rows).
Env PT_BASE_OFFSET (seconds) keeps note dates unique across books; queue.py sets it automatically."""
import sys, os, re, csv, hashlib, html, random, collections
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build as B, project as P
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
BOOK, RM, CFG = B.BOOK, B.RM, B.CFG
LANG = P.label(CFG); REF = CFG["reference_name"]
OUT = os.path.join(CFG["output_dir"], BOOK); os.makedirs(OUT, exist_ok=True)
COLS = ["Book", "Chapter", "Verse", "Issue Type", "Priority Category", "Severity", "Confidence", "Original Text", "Suggested Correction",
        "Explanation", "Reference Note", "Reviewer Decision Needed", "Status", "Location", "Paratext Anchor"]
HDR = {c: c for c in COLS}; HDR["Original Text"] = f"Original {LANG}"; HDR["Reference Note"] = f"Source / {REF} Reference Note"
rows = B.out
with open(f"{OUT}/{BOOK}_QA_Issues.csv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f); w.writerow([HDR[c] for c in COLS]); w.writerows([[r[c] for c in COLS] for r in rows])
bt, st, rt, Vt = P.parse(B.tp)
Ve = P.parse(B.ep)[3] if B.ep else {}
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
bold = Font(bold=True); hf = PatternFill("solid", fgColor="1F4E78"); hfont = Font(bold=True, color="FFFFFF")
wb = Workbook(); ws = wb.active; ws.title = "Summary"
ws.append([f"{LANG} — {P.NAMES[BOOK]} — publishing proofreading QA against {REF}"]); ws["A1"].font = Font(bold=True, size=13)
ws.append(["All rows are AI proposals awaiting human review. Scripture text was not modified."]); ws.append([])
ws.append(["Total findings", "=COUNTA(Issues!A:A)-1"])
for s in ["High", "Medium", "Low"]: ws.append([f"Severity: {s}", f'=COUNTIF(Issues!F:F,"{s}")'])
for s in ["Verse text", "Introduction", "Heading", "Footnote"]: ws.append([f"Location: {s}", f'=COUNTIF(Issues!N:N,"{s}")'])
ws.append([]); ws.append(["Issue type", "Findings", "Checker's note"])
for c in ws[ws.max_row]: c.font = bold
TN = getattr(RM, "TYPE_NOTES", {})
for t in sorted({r["Issue Type"] for r in rows} | set(TN)): ws.append([t, f'=COUNTIF(Issues!D:D,"{t}")', TN.get(t, "")])
ws.append([]); ws.append(["Findings by chapter", "Findings"]);
for c in ws[ws.max_row]: c.font = bold
for ch, n in sorted(collections.Counter(str(r["Chapter"]) for r in rows).items(), key=lambda x: (x[0] != "Intro", int(x[0]) if x[0].isdigit() else 0)): ws.append([f"Chapter {ch}" if ch != "Intro" else "Introduction", n])
ws.column_dimensions["A"].width = 34; ws.column_dimensions["B"].width = 10; ws.column_dimensions["C"].width = 100
wi = wb.create_sheet("Issues"); wi.append([HDR[c] for c in COLS])
for c in wi[1]: c.font = hfont; c.fill = hf
for r in rows: wi.append([r[c] for c in COLS])
for col, wd in zip("ABCDEFGHIJKLMNO", [6, 8, 7, 22, 14, 9, 11, 42, 42, 70, 42, 10, 8, 14, 14]): wi.column_dimensions[col].width = wd
for row in wi.iter_rows(min_row=2):
    for c in row: c.alignment = Alignment(wrap_text=True, vertical="top")
wi.freeze_panes = "A2"; wi.auto_filter.ref = wi.dimensions
wv = wb.create_sheet("Source Verses"); wv.append(["Chapter", "Verse", f"{LANG} text", f"{REF} text"])
for c in wv[1]: c.font = bold
for (c_, v), t in Vt.items():
    if "-" in v:
        a, z = int(v.split("-")[0]), int(re.sub(r"\D", "", v.split("-")[1])); e = " ".join(f"[{i}] " + Ve.get((c_, str(i)), "") for i in range(a, z + 1))
    else: e = Ve.get((c_, v), "")
    wv.append([c_, v, t, e])
wv.column_dimensions["C"].width = 80; wv.column_dimensions["D"].width = 80
wr = wb.create_sheet("Rejected Leads"); wr.append(["Lead", "Why it was not reported"])
for a in getattr(RM, "REJECTED", []): wr.append(list(a))
wr.column_dimensions["A"].width = 60; wr.column_dimensions["B"].width = 100
wp = wb.create_sheet("Provenance")
for a in [("Target file", B.tp), ("Target SHA-256", sha(B.tp)), ("Reference file", B.ep or "none"), ("Reference SHA-256", sha(B.ep) if B.ep else ""),
          ("Language profile", os.path.basename(B.PROF["_dir"]) + " — " + B.PROF.get("status", "")), ("Chapters reviewed", getattr(RM, "REVIEWED", "")),
          ("Verification", f"{len(rows)} rows; every Original string located character for character: " + ", ".join(f"{n} {k.lower()}" for k, n in B.stats.items() if k != "fail") + f"; failed {B.stats['fail']}"),
          ("Check date", datetime.now().strftime("%Y-%m-%d")), ("Scripture text modified", "No")]: wp.append(list(a))
wp.column_dimensions["A"].width = 28; wp.column_dimensions["B"].width = 120
wb.save(f"{OUT}/{BOOK}_QA_Report.xlsx")
# ---- Paratext notes
USER = CFG["notes_user"]; TAG = CFG.get("notes_language_tag") or (B.PROF["_lang"]["code"] or "und")
TZ = timezone(timedelta(hours=5, minutes=30)); esc = lambda s: html.escape(str(s), quote=False)
random.seed(BOOK + USER); used = set()
def tid():
    while True:
        t = "".join(random.choices("0123456789abcdef", k=8))
        if t not in used: used.add(t); return t
base = datetime.now(TZ).replace(microsecond=0) + timedelta(seconds=int(os.environ.get("PT_BASE_OFFSET", "0")))
com = []
for n, r in enumerate(rows):
    key = r["_akey"]; vt = B.seg[key]; sel = r["_sel"]; start = r["_start"]
    assert vt[start:start + len(sel)] == sel
    before, after = (vt[:start], vt[start + len(sel):]) if len(vt) <= 700 else (vt[max(0, start - 80):start], vt[start + len(sel):start + len(sel) + 80])
    p = [f"<p><bold>[AI-QA] {esc(r['Priority Category'])} — {esc(r['Issue Type'])}</bold></p>"]
    if r["_loc"] != "Verse text":
        where = {"Introduction": "book introduction", "Heading": f"heading before {r['_key'][0]}:{r['_key'][1]}" if r["_key"] else "heading",
                 "Footnote": "footnote of this verse", "Cross-reference": "cross-reference of this verse"}[r["_loc"]]
        p.append(f"<p><bold>Location:</bold> {where} — pinned on the flagged words</p>")
    p.append(f"<p><bold>Original:</bold> {esc(r['Original Text'])}</p>")
    if r["Suggested Correction"]: p.append(f"<p><bold>Suggested:</bold> {esc(r['Suggested Correction'])}</p>")
    p += [f"<p><bold>Reason:</bold> {esc(r['Explanation'])}</p>", f"<p><bold>Reference ({esc(REF)}):</bold> {esc(r['Reference Note'])}</p>",
          f"<p><bold>Severity:</bold> {r['Severity']} · <bold>Confidence:</bold> {r['Confidence']} · <bold>Reviewer decision needed:</bold> {r['Reviewer Decision Needed']}</p>",
          "<p><bold>AI proposal — human review required. Not an edit.</bold></p>"]
    com.append(f"""  <Comment Thread="{tid()}" User="{esc(USER)}" VerseRef="{BOOK} {key[0]}:{key[1]}" Language="{TAG}" Date="{(base + timedelta(seconds=n)).isoformat()}">
    <SelectedText>{esc(sel)}</SelectedText>
    <StartPosition>{start}</StartPosition>
    <ContextBefore>{esc(before)}</ContextBefore>
    <ContextAfter>{esc(after)}</ContextAfter>
    <Status>todo</Status>
    <Type></Type>
    <ConflictType />
    <Verse>{esc(vt)}</Verse>
    <ReplyToUser />
    <HideInTextWindow>false</HideInTextWindow>
    <Contents>
      {"".join(p)}
    </Contents>
  </Comment>""")
xml = '<?xml version="1.0" encoding="utf-8"?>\n<CommentList>\n' + "\n".join(com) + "\n</CommentList>"
open(f"{OUT}/{BOOK}_notes_only.xml", "wb").write(b"\xef\xbb\xbf" + xml.replace("\n", "\r\n").encode("utf-8"))
print(f"{BOOK}: {len(rows)} findings → {OUT}")
