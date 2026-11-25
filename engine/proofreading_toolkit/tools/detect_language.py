"""Print the detected language, script, books found and the profile that will be used."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project as P
lang = P.detect_language(); prof = P.profile(); t, r = P.books_available()
print(f"Language: {lang['name']} | code: {lang['code']} (from {lang['source']}) | script: {lang['script']}")
print(f"Profile used: {os.path.basename(prof['_dir'])} — {prof.get('status','')}")
print(f"Target books: {len(t)} | Reference ({P.cfg()['reference_name']}) books: {len(r)}")
miss = [b for b in t if b not in r]
if miss: print("Target books with no reference file:", " ".join(miss))
