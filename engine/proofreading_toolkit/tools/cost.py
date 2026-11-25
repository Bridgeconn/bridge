"""Cost and token estimate per book.
Claude cannot read its own token meter while it works, so the estimate is calibrated from a measured run:
the Telugu IRV check of Daniel–Malachi (204,328 characters of target verse text) used 43.3M cache-read,
0.92M cache-write, 0.15M output tokens. Scale = target characters of the book. Replace with ACTUAL figures
(queue.py done BOOK --usage in,cache_write,cache_read,out) whenever you have them, e.g. from the API response
usage fields or the Anthropic Console."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project as P
CAL_DEFAULT = {"basis": "Telugu IRV Daniel–Malachi, Nov 2026, claude-opus-5-5", "target_chars": 204328,
               "input": 262, "cache_write": 924003, "cache_read": 43312560, "output": 152125}
RATES_DEFAULT = {"input": 5.0, "cache_write": 6.25, "cache_read": 0.5, "output": 25.0}
def rates(): return P.cfg().get("price_per_million_tokens_usd", RATES_DEFAULT)
def calibration(): return P.cfg().get("calibration", CAL_DEFAULT)
def chars(book): return len("".join(P.parse(P.target(book))[3].values()))
def usd(tok):
    r = rates(); return sum(tok.get(k, 0) * r.get(k, 0) / 1e6 for k in ("input", "cache_write", "cache_read", "output"))
def estimate(book):
    cal = calibration(); f = chars(book) / cal["target_chars"]
    tok = {k: int(cal[k] * f) for k in ("input", "cache_write", "cache_read", "output")}
    return tok, usd(tok)
if __name__ == "__main__":
    scope = P.expand_scope(sys.argv[1] if len(sys.argv) > 1 else "all"); tot = 0; tt = 0
    for b in scope:
        tok, d = estimate(b); tot += d; tt += sum(tok.values()); print(f"{b}\t{sum(tok.values()):>12,} tokens\t${d:,.2f}")
    print(f"TOTAL {len(scope)} books\t{tt:,} tokens\t${tot:,.2f}  (estimate; model {P.cfg().get('model')}; prices are assumptions in config.json)")
