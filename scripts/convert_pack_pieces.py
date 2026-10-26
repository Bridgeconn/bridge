"""Rewrite each pack's IRV snapshot and corpus lexicon so they load in small pieces.

    python scripts/convert_pack_pieces.py                 # convert in place, verified
    python scripts/convert_pack_pieces.py --against REV   # verify only, against a git revision

Both files were one JSON document, and one json.loads of 1-27 MB held the GIL
long enough to stall the dispatcher (ping 250-900 ms during a Language QA
scan). Nothing is recomputed: each file is re-encoded from its own contents,
and checked before anything is written.

- irv_state.json.gz (every indic-qa pack): format 1 -> format 2, the same
  encoded state as JSON lines in bounded pieces (indic_qa_adapter.read_state).
  The format-2 bytes must decode to exactly what the format-1 document
  decodes to: the same types, values and dict insertion order, and the same
  provenance. A file already in format 2 is left alone.
- lexicon.json.gz (a pack.json `lexicon`): the same JSON document, laid out a
  member per line and a large member over lines of bounded entries
  (lexicon.LEXICON_PIECE). Only whitespace between tokens changes: json.load
  of the new text must equal the old, in the same order, and so must the line
  reader's parse. The human-confirmed pairs are compared on their own too.

--against REV reads each file from that git revision instead and checks the
current file decodes identically to it; nothing is written.
"""
from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "engine"))

from tc_ai_bridge.language_packs import indic_qa_adapter as adapter, lexicon  # noqa: E402
from tc_ai_bridge.language_packs.registry import packs_dir  # noqa: E402

FIELDS = ("bookCount", "data", "bookPairs", "bookFormUse")


def same(a, b, where="state") -> str | None:
    """Where `a` and `b` differ in type, value or dict order; None if nowhere."""
    if type(a) is not type(b):
        return f"{where}: {type(a).__name__} != {type(b).__name__}"
    if isinstance(a, dict):
        if list(a) != list(b):
            return f"{where}: keys or their order differ"
        for key in a:
            found = same(a[key], b[key], f"{where}[{key!r}]")
            if found:
                return found
        return None
    if isinstance(a, (list, tuple)):
        if len(a) != len(b):
            return f"{where}: length {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            found = same(x, y, f"{where}[{i}]")
            if found:
                return found
        return None
    if isinstance(a, (set, frozenset)):
        if a != b or any(type(x) is not type(y) for x, y in zip(sorted(a, key=repr), sorted(b, key=repr))):
            return f"{where}: set differs"
        return None
    return None if a == b else f"{where}: {a!r} != {b!r}"


def decode_v1(raw_bytes: bytes) -> tuple[dict, dict]:
    raw = json.loads(gzip.decompress(raw_bytes))
    assert raw.get("format") == 1, raw.get("format")
    return {k: adapter.decode_state(raw[k]) for k in FIELDS if k in raw}, raw.get("provenance") or {}


def decode_file(data: bytes) -> tuple[dict, dict]:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / adapter.IRV_STATE
        path.write_bytes(data)
        return adapter.read_state(path)


def check(name: str, old: bytes, new: bytes) -> None:
    old_fields, old_prov = decode_v1(old)
    new_fields, new_prov = decode_file(new)
    # The fields' own order is not state (each becomes a checker attribute).
    problem = (None if sorted(old_fields) == sorted(new_fields) else "fields differ") or next(
        (p for p in (same(old_fields[k], new_fields[k], k) for k in old_fields) if p), None) or same(
        old_prov, new_prov, "provenance")
    if problem:
        raise SystemExit(f"{name}: format 2 does not decode to the format-1 state: {problem}")
    if not new.startswith(b"\x1f\x8b") or not gzip.decompress(new).startswith(b'{"format":2,'):
        raise SystemExit(f"{name}: not a format-2 file")
    entries = sum(len(v) for f in new_fields.values() for v in (f.values() if isinstance(f, dict) else [f])
                  if hasattr(v, "__len__"))
    print(f"{name}: identical ({', '.join(sorted(new_fields))}; {entries} nested entries; "
          f"{len(old)} -> {len(new)} bytes)")


def check_lexicon(name: str, old: bytes, new: bytes) -> None:
    old_text, new_text = gzip.decompress(old).decode("utf-8"), gzip.decompress(new).decode("utf-8")
    before = json.loads(old_text)
    for label, after in (("json.loads", json.loads(new_text)), ("line reader", lexicon.parse_lexicon_text(new_text)[0])):
        problem = same(before, after, "lexicon")
        if problem:
            raise SystemExit(f"{name}: the rewritten lexicon differs ({label}): {problem}")
    if not new_text.startswith("{\n"):
        raise SystemExit(f"{name}: lexicon not in the line layout")
    loaded = lexicon.load_lexicon(_temp(new))
    loaded.candidates("")  # parses the deferred buckets
    if loaded.buckets != before["buckets"] or list(loaded.buckets) != list(before["buckets"]):
        raise SystemExit(f"{name}: the lazily parsed buckets differ")
    human = sorted(w for w, p in before.get("provenance", {}).items() if p == "human")
    assert human == sorted(w for w, p in loaded.provenance.items() if p == "human")
    assert {w: before["deprecated"][w] for w in human} == {w: loaded.deprecated[w] for w in human}
    print(f"{name}: lexicon identical ({len(before)} members, {len(before['forms'])} forms, "
          f"{len(before['buckets'])} buckets, {len(human)} human-confirmed pairs; "
          f"{old_text.count(chr(10)) + 1} -> {new_text.count(chr(10)) + 1} lines; {len(old)} -> {len(new)} bytes)")


_TEMP = tempfile.TemporaryDirectory()


def _temp(data: bytes) -> Path:
    path = Path(_TEMP.name) / "lexicon.json.gz"
    path.write_bytes(data)
    return path


def lexicon_paths() -> list[Path]:
    out = []
    for meta in sorted(packs_dir().glob("*/pack.json")):
        name = json.loads(meta.read_text(encoding="utf-8")).get("lexicon")
        if name and (meta.parent / name).is_file():
            out.append(meta.parent / name)
    return out


def git_show(rev: str, path: Path) -> bytes:
    rel = path.relative_to(REPO).as_posix()
    return subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=REPO, check=True, capture_output=True).stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--against", metavar="REV", help="verify the current files against REV's files")
    args = parser.parse_args()
    for path in lexicon_paths():
        name = path.parent.name
        if args.against:
            check_lexicon(name, git_show(args.against, path), path.read_bytes())
            continue
        old = path.read_bytes()
        if gzip.decompress(old).startswith(b"{\n"):
            print(f"{name}: lexicon already in the line layout")
            continue
        target = _temp(b"")
        lexicon.write_lexicon_json(target, json.loads(gzip.decompress(old)))
        new = target.read_bytes()
        check_lexicon(name, old, new)
        path.write_bytes(new)
    paths = sorted(packs_dir().glob(f"*/{adapter.IRV_STATE}"))
    if not paths:
        raise SystemExit("no irv_state.json.gz under the packs folder")
    for path in paths:
        name = path.parent.name
        if args.against:
            check(name, git_show(args.against, path), path.read_bytes())
            continue
        old = path.read_bytes()
        if gzip.decompress(old).startswith(b'{"format":2,'):
            print(f"{name}: already format 2")
            continue
        raw = json.loads(gzip.decompress(old))
        fields = {k: raw[k] for k in FIELDS if k in raw}
        new = gzip.compress(adapter.encode_state_file(fields, raw.get("provenance") or {}), 9, mtime=0)
        check(name, old, new)
        path.write_bytes(new)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
