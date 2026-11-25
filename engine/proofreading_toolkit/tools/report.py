"""report.py : rebuild the live run report after every book.
<output_dir>/QA_Run_Report.xlsx — Overview, By book, By chapter, By verse, By issue type, High & Medium — and RUN_REPORT.md."""
import sys, os, csv, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project as P
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
C = P.cfg(); OUT = C["output_dir"]
st = json.load(open(os.path.join(OUT, "run_state.json"), encoding="utf-8")) if os.path.exists(os.path.join(OUT, "run_state.json")) else {"books": {}}
rows = []
for b in P.ORDER:
    p = os.path.join(OUT, b, f"{b}_QA_Issues.csv")
    if os.path.exists(p):
        R = list(csv.reader(open(p, encoding="utf-8-sig"))); hdr = R[0]
        for r in R[1:]: rows.append(dict(zip(["Book", "Chapter", "Verse", "Type", "Category", "Severity", "Confidence", "Original", "Suggested", "Explanation", "RefNote", "Decision", "Status", "Location", "Anchor"], r)))
H = Font(bold=True, color="FFFFFF"); HF = PatternFill("solid", fgColor="1F4E78"); B = Font(bold=True)
def sheet(wb, title, cols, data, widths):
    ws = wb.create_sheet(title); ws.append(cols)
    for c in ws[1]: c.font = H; c.fill = HF; c.alignment = Alignment(wrap_text=True)
    for d in data: ws.append(d)
    for i, w in enumerate(widths): ws.column_dimensions[chr(65 + i)].width = w
    ws.freeze_panes = "A2"; ws.auto_filter.ref = ws.dimensions; return ws
sevc = lambda L: [sum(1 for r in L if r["Severity"] == s) for s in ("High", "Medium", "Low")]
wb = Workbook(); ws = wb.active; ws.title = "Overview"
books = st["books"]; done = {b: v for b, v in books.items() if v["status"] == "done"}
lang = st.get("language", {})
ov = [("Language", f"{lang.get('name')} ({lang.get('code')}, {lang.get('script')} script)"), ("Reference Bible", st.get("reference", C["reference_name"])),
      ("Model", st.get("model", C.get("model"))), ("Scope", st.get("scope", "")), ("Run control", st.get("control", "")),
      ("Books in scope", len(books)), ("Books done", len(done)), ("Books pending", sum(1 for v in books.values() if v["status"] in ("pending", "running"))),
      ("Total findings", len(rows)), ("High / Medium / Low", " / ".join(map(str, sevc(rows)))),
      ("Tokens so far", f"{sum(v.get('tokens', 0) for v in done.values()):,}"), ("Cost so far (USD)", round(sum(v.get("usd", 0) for v in done.values()), 2)),
      ("Estimated cost of books still to run (USD)", round(sum(v["est_usd"] for v in books.values() if v["status"] != "done"), 2)),
      ("Cost basis", "estimate calibrated on a measured run unless a book shows 'actual'; prices are the assumptions in config.json"),
      ("Note", "Every finding is an AI proposal for human review. No Scripture file was changed.")]
ws.append([f"Publishing proofreading QA — run report"]); ws["A1"].font = Font(bold=True, size=14)
for k, v in ov: ws.append([k, v]); ws.cell(ws.max_row, 1).font = B
ws.column_dimensions["A"].width = 42; ws.column_dimensions["B"].width = 90
byb = collections.defaultdict(list)
for r in rows: byb[r["Book"]].append(r)
data = []
for b in P.ORDER:
    if b not in books and b not in byb: continue
    v = books.get(b, {}); L = byb.get(b, [])
    data.append([b, P.NAMES[b], v.get("status", "done"), len(L), *sevc(L), sum(r["Location"] == "Introduction" for r in L), sum(r["Location"] == "Heading" for r in L),
                 sum(r["Location"] == "Footnote" for r in L), len({r["Chapter"] for r in L if r["Chapter"] != "Intro"}), v.get("tokens", v.get("est_tokens")),
                 v.get("usd", v.get("est_usd")), v.get("cost_basis", "estimate (not run yet)"), v.get("started", ""), v.get("finished", ""), v.get("minutes", "")])
sheet(wb, "By book", ["Code", "Book", "Status", "Findings", "High", "Medium", "Low", "Intro", "Headings", "Footnotes", "Chapters with findings", "Tokens", "Cost USD", "Cost basis", "Started", "Finished", "Minutes"],
      data, [7, 16, 9, 9, 6, 8, 7, 7, 9, 9, 10, 13, 9, 22, 18, 18, 8])
ch = collections.defaultdict(list)
for r in rows: ch[(r["Book"], r["Chapter"])].append(r)
sheet(wb, "By chapter", ["Book", "Chapter", "Findings", "High", "Medium", "Low", "Verses with findings"],
      [[b, c, len(L), *sevc(L), len({r["Verse"] for r in L})] for (b, c), L in ch.items()], [7, 9, 9, 6, 8, 7, 12])
vv = collections.defaultdict(list)
for r in rows: vv[(r["Book"], r["Chapter"], r["Verse"])].append(r)
rank = {"High": 0, "Medium": 1, "Low": 2}
sheet(wb, "By verse", ["Book", "Chapter", "Verse", "Findings", "Highest severity", "Issue types"],
      [[b, c, v, len(L), min((r["Severity"] for r in L), key=lambda x: rank.get(x, 3)), "; ".join(sorted({r["Type"] for r in L}))] for (b, c, v), L in vv.items()], [7, 9, 7, 9, 12, 70])
ty = collections.Counter(r["Type"] for r in rows)
sheet(wb, "By issue type", ["Issue type", "Findings", "High", "Medium", "Low"], [[t, n, *sevc([r for r in rows if r["Type"] == t])] for t, n in ty.most_common()], [32, 10, 7, 8, 8])
hm = [r for r in rows if r["Severity"] in ("High", "Medium")]
w = sheet(wb, "High & Medium", ["Book", "Chapter", "Verse", "Severity", "Issue type", "Original", "Suggested", "Explanation"],
          [[r["Book"], r["Chapter"], r["Verse"], r["Severity"], r["Type"], r["Original"], r["Suggested"], r["Explanation"]] for r in hm], [7, 8, 7, 9, 18, 40, 40, 80])
for row in w.iter_rows(min_row=2):
    for c in row: c.alignment = Alignment(wrap_text=True, vertical="top")
wb.save(os.path.join(OUT, "QA_Run_Report.xlsx"))
md = [f"# QA run report — {lang.get('name')} against {st.get('reference', C['reference_name'])}", "", *[f"- **{k}:** {v}" for k, v in ov[:13]], "",
      "| Book | Status | Findings | H | M | L | Cost USD |", "|---|---|---|---|---|---|---|"]
md += [f"| {d[1]} | {d[2]} | {d[3]} | {d[4]} | {d[5]} | {d[6]} | {d[12]} |" for d in data]
open(os.path.join(OUT, "RUN_REPORT.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
print(f"report: {len(rows)} findings, {len(done)}/{len(books)} books done → QA_Run_Report.xlsx, RUN_REPORT.md")
