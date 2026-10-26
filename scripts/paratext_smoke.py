"""Read-only smoke run of the Paratext reader against a real project folder (#354).

    python scripts/paratext_smoke.py "C:\\My Paratext 9 Projects\\IRVTam" --ref "JOS 3:4"

Prints the settings Bridge reads, the book scan (files, skips with reasons,
warnings), each notes file's parse time, thread counts per user, the
build_notes_index time and the threads at ``--ref``. It only reads: nothing is
written to the folder or anywhere else, and the output is for an issue
comment, never for committed data.
"""
from __future__ import annotations

import argparse
import collections
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "engine"))

from tc_ai_bridge import paratext_project as pp  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--ref", action="append", default=[], help='a reference to show, e.g. "JOS 3:4"')
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    folder = pp.detect_paratext_folder(args.folder)
    if folder is None:
        print(f"Not a Paratext project folder: {args.folder}")
        return 1
    started = time.perf_counter()
    settings = pp.read_settings(folder)
    print(f"# {folder}")
    print(f"settings: {(time.perf_counter() - started) * 1000:.0f} ms")
    print(f"  name={settings.name!r} fullName={settings.full_name!r} guid={settings.guid}")
    print(f"  language={settings.language_name!r} iso={settings.language_iso.raw!r} -> {pp.language_fields(settings)}")
    print(f"  versification={settings.versification} ({settings.versification_name}) naming={settings.naming.to_json()}")
    print(f"  booksPresent={len(settings.books_present)} normalization={settings.normalization!r} "
          f"quotes={settings.quotes.get('Quotes', '')!r}")
    for warning in settings.warnings:
        print(f"  warning: {warning}")

    started = time.perf_counter()
    scan = pp.scripture_candidates(folder, settings)
    print(f"\nscan: {len(scan.files)} book files, {len(scan.skipped)} skipped, "
          f"{(time.perf_counter() - started) * 1000:.0f} ms")
    print("  books: " + " ".join(code for code, _ in scan.files))
    for path, reason in scan.skipped:
        print(f"  skipped {path.name}: {reason}")
    for warning in scan.warnings:
        print(f"  warning: {warning}")

    started = time.perf_counter()
    index = pp.build_notes_index(folder)
    elapsed = time.perf_counter() - started
    print(f"\nbuild_notes_index: {elapsed:.2f} s, {len(index.threads)} threads, "
          f"{sum(len(t.comments) for t in index.threads.values())} comments, {len(index.unanchored)} unanchored")
    print("  per file (size, parse time):")
    for name, (size, _, _) in sorted(index.files.items(), key=lambda item: -item[1][0]):
        note = f"  SKIPPED: {index.skipped_files[name]}" if name in index.skipped_files else ""
        print(f"    {name}: {size / 1e6:.2f} MB, {index.timings.get(name, 0):.2f} s{note}")
    kinds = collections.Counter(t.kind for t in index.threads.values())
    statuses = collections.Counter(t.status or "(unset)" for t in index.threads.values())
    print(f"  kinds: {dict(kinds)}")
    print(f"  statuses: {dict(statuses)}")
    started_by = collections.Counter(t.comments[0].user for t in index.threads.values())
    took_part = collections.Counter(user for t in index.threads.values() for user in t.users)
    print("  threads per user (started / took part):")
    for user, count in took_part.most_common():
        print(f"    {user}: {started_by.get(user, 0)} / {count}")

    for ref_text in args.ref:
        ref = pp.parse_ref(ref_text)
        if ref is None:
            print(f"\n{ref_text}: not a reference")
            continue
        threads = index.threads_for(ref.book, ref.chapter, ref.verse, include_deleted=True)
        print(f"\n{ref_text}: {len(threads)} thread(s)")
        for thread in threads:
            print(f"  thread {thread.id} kind={thread.kind} status={thread.status or '(unset)'} "
                  f"selected={thread.selected_text!r}")
            for comment in thread.comments:
                first_line = comment.contents.split("\n", 1)[0]
                print(f"    {comment.date} {comment.user}: {first_line[:160]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
