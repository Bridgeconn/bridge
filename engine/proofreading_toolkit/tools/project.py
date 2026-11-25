"""Shared core: configuration, book discovery, language profile, USFM parsing.
Every tool imports this. Nothing here ever writes to the target or reference folders."""
import json, os, re, glob, sys, unicodedata, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ORDER = ("GEN EXO LEV NUM DEU JOS JDG RUT 1SA 2SA 1KI 2KI 1CH 2CH EZR NEH EST JOB PSA PRO ECC SNG ISA JER LAM "
         "EZK DAN HOS JOL AMO OBA JON MIC NAM HAB ZEP HAG ZEC MAL MAT MRK LUK JHN ACT ROM 1CO 2CO GAL EPH PHP COL "
         "1TH 2TH 1TI 2TI TIT PHM HEB JAS 1PE 2PE 1JN 2JN 3JN JUD REV").split()
OT, NT = ORDER[:39], ORDER[39:]
NAMES = dict(zip(ORDER, ["Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy", "Joshua", "Judges", "Ruth",
    "1 Samuel", "2 Samuel", "1 Kings", "2 Kings", "1 Chronicles", "2 Chronicles", "Ezra", "Nehemiah", "Esther", "Job",
    "Psalms", "Proverbs", "Ecclesiastes", "Song of Songs", "Isaiah", "Jeremiah", "Lamentations", "Ezekiel", "Daniel",
    "Hosea", "Joel", "Amos", "Obadiah", "Jonah", "Micah", "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah",
    "Malachi", "Matthew", "Mark", "Luke", "John", "Acts", "Romans", "1 Corinthians", "2 Corinthians", "Galatians",
    "Ephesians", "Philippians", "Colossians", "1 Thessalonians", "2 Thessalonians", "1 Timothy", "2 Timothy", "Titus",
    "Philemon", "Hebrews", "James", "1 Peter", "2 Peter", "1 John", "2 John", "3 John", "Jude", "Revelation"]))
HEAD_RX = re.compile(r"\\(?:s\d?|ms\d?|mr|r|d|sp|qa|sr|mt\d?|is\d?|cl|cp)\b")

# ---------------------------------------------------------------- configuration
def cfg_path():
    return os.environ.get("QA_CONFIG", os.path.join(ROOT, "config.json"))

def cfg():
    p = cfg_path()
    if not os.path.exists(p):
        sys.exit(f"No config at {p}. Copy templates/config.example.json to config.json and fill it in.")
    c = json.load(open(p, encoding="utf-8"))
    c.setdefault("reference_name", "Reference")
    c.setdefault("output_dir", os.path.join(ROOT, "output"))
    c.setdefault("work_dir", os.path.join(ROOT, "work"))
    os.makedirs(c["output_dir"], exist_ok=True); os.makedirs(c["work_dir"], exist_ok=True)
    return c

# ---------------------------------------------------------------- book discovery (by \id, not by file name)
_cache = {}
def book_files(folder):
    """Map USFM book code -> file path for every .SFM/.USFM/.usfm/.sfm/.ptx file in folder (read from \\id)."""
    if folder in _cache: return _cache[folder]
    m = {}
    for p in sorted(glob.glob(os.path.join(folder, "*"))):
        if not re.search(r"\.(sfm|usfm|ptx|txt)$", p, re.I): continue
        try: head = open(p, encoding="utf-8-sig", errors="replace").read(400)
        except OSError: continue
        g = re.search(r"\\id\s+([0-9A-Z]{3})", head)
        if g and g.group(1) in ORDER and g.group(1) not in m: m[g.group(1)] = p
    _cache[folder] = m
    return m

def target(code):
    f = book_files(cfg()["target_dir"]).get(code)
    if not f: sys.exit(f"{code}: no target file with \\id {code} in {cfg()['target_dir']}")
    return f

def reference(code):
    f = book_files(cfg()["reference_dir"]).get(code)
    if not f: raise FileNotFoundError(f"{code}: no reference file with \\id {code} in {cfg()['reference_dir']}")
    return f

def books_available():
    t = book_files(cfg()["target_dir"]); r = book_files(cfg()["reference_dir"])
    return [b for b in ORDER if b in t], [b for b in ORDER if b in r]

# ---------------------------------------------------------------- scope
def expand_scope(scope):
    """'all' | 'OT' | 'NT' | 'GEN,EXO,PSA' | 'GEN-DEU' | 'MAT-JHN,ROM' -> ordered list of codes."""
    out = []
    for part in [p.strip().upper() for p in scope.split(",") if p.strip()]:
        if part in ("ALL", "*"): out += ORDER
        elif part == "OT": out += OT
        elif part == "NT": out += NT
        elif "-" in part:
            a, b = part.split("-", 1); out += ORDER[ORDER.index(a):ORDER.index(b) + 1]
        else:
            if part not in ORDER: sys.exit(f"Unknown book code {part}")
            out.append(part)
    seen = set(); return [b for b in ORDER if b in out and not (b in seen or seen.add(b))]

# ---------------------------------------------------------------- USFM parsing
def strip_notes(t):
    t = re.sub(r"\\f .*?\\f\*", "", t, flags=re.S); t = re.sub(r"\\x .*?\\x\*", "", t, flags=re.S)
    t = re.sub(r"\\[a-z0-9+]+\*?", "", t); t = re.sub(r"\|[^\\ ]*?=\"[^\"]*\"", "", t)   # \w word|lemma="..."
    return re.sub(r"\s+", " ", t).strip()

def parse(path):
    """-> (book, full_text, raw{(c,v):usfm incl. headings}, verses{(c,v):clean text}).
    Works whether \\v starts a line or follows a paragraph marker on the same line."""
    s = open(path, encoding="utf-8-sig").read().replace("\r\n", "\n")
    book = re.search(r"\\id\s+(\S+)", s).group(1)
    raw = collections.OrderedDict(); c = 0; cur = None
    for tok in re.split(r"(\\c\s+\d+|\\v\s+\S+)", s):
        m = re.match(r"\\c\s+(\d+)", tok)
        if m: c = int(m.group(1)); cur = None; continue
        m = re.match(r"\\v\s+(\S+)", tok)
        if m: cur = (c, m.group(1)); raw[cur] = ""; continue
        if cur: raw[cur] += tok
    V = collections.OrderedDict()
    for k, t in raw.items():
        keep = [ln for ln in t.split("\n") if not HEAD_RX.match(ln.strip())]
        V[k] = strip_notes(" ".join(keep))
    return book, s, raw, V

def verse_keys_for(V, c, v):
    """Find the target key that holds verse v of chapter c (handles bridges like 3-4)."""
    for (cc, vv) in V:
        if cc == c and (vv == str(v) or ("-" in vv and str(v).isdigit() and
                        int(vv.split("-")[0]) <= int(v) <= int(re.sub(r"\D", "", vv.split("-")[1]) or 0))):
            return (cc, vv)
    return None

# ---------------------------------------------------------------- language and profile
def detect_script(text, sample=40000):
    cnt = collections.Counter()
    for ch in text[:sample]:
        if ch.isalpha():
            try: cnt[unicodedata.name(ch).split()[0]] += 1
            except ValueError: pass
    return cnt.most_common(1)[0][0].title() if cnt else "Unknown"

def detect_language():
    """Language from Paratext Settings.xml, then \\ide/\\h hints, then script. Returns dict."""
    c = cfg(); out = {"code": None, "name": None, "script": None, "source": None}
    st = os.path.join(c["target_dir"], "Settings.xml")
    if os.path.exists(st):
        x = open(st, encoding="utf-8-sig").read()
        iso = re.search(r"<LanguageIsoCode>([^<:]*)", x); nm = re.search(r"<Language>([^<]*)", x)
        if iso and iso.group(1): out.update(code=iso.group(1), source="Settings.xml")
        if nm: out["name"] = nm.group(1)
    files = book_files(c["target_dir"])
    if files:
        s = open(next(iter(files.values())), encoding="utf-8-sig").read()
        body = s[s.find("\\c 1"):] if "\\c 1" in s else s
        out["script"] = detect_script(strip_notes(body))
    if c.get("language") and c["language"] != "auto": out.update(code=c["language"], source="config.json")
    return out

def profile():
    """Load profiles/<code>/profile.json, falling back to profiles/generic with the detected script."""
    lang = detect_language(); code = (lang["code"] or "generic").split("-")[0].lower()
    d = os.path.join(ROOT, "profiles", code)
    if not os.path.exists(os.path.join(d, "profile.json")): d = os.path.join(ROOT, "profiles", "generic")
    p = json.load(open(os.path.join(d, "profile.json"), encoding="utf-8"))
    p["_dir"] = d; p["_lang"] = lang
    if not p.get("word_chars"):            # generic profile: build the letter class from the detected script
        p["word_chars"] = script_class(lang["script"])
    return p

def script_class(script):
    """Character class (for regex) of all letters and marks of one Unicode script, plus ZWJ/ZWNJ."""
    if not script or script == "Unknown": return r"\w"
    rng = []; start = None
    for cp in range(0x20, 0x20000):
        ch = chr(cp)
        try: ok = unicodedata.name(ch).split()[0] == script.upper() and unicodedata.category(ch)[0] in "LM"
        except ValueError: ok = False
        if ok and start is None: start = cp
        if not ok and start is not None: rng.append((start, cp - 1)); start = None
    cls = "".join(f"\\u{a:04x}-\\u{b:04x}" if a != b else f"\\u{a:04x}" for a, b in rng if b < 0x10000)
    return (cls or r"\w") + r"\u200c\u200d"

def label(c=None):
    c = c or cfg(); return c.get("language_label") or (detect_language()["name"] or "Target")
