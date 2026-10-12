"""One SQLite connection per thread per database file, reused (#113).

`FoundationRepository` and `WorkbenchRepository` used to open a fresh
connection for every method call -- `synchronous = FULL` under WAL, closed on
the way out, which on Windows also checkpointed the WAL every time. One
Stage 5-8 pipeline build did that about 1,800 times. Measured on
`tests/semantic/test_qa_target_hash_contract_stage8_9b.py` (9 tests, serial,
2026-10-12): 95 s with a connection per call and FULL, 90 s with NORMAL and
still a connection per call, 11 s with one connection per thread reused. The
fsync was never the cost; the open/close was.

The contract the repositories had is kept:

- a block that ends without committing discards its work (a closed connection
  rolled back; a reused one is rolled back explicitly on exit);
- a connection is used by one thread only (`check_same_thread=False` is set
  so that `release()` may *close* another thread's connection, never so that
  two threads share one);
- `foreign_keys ON`, `busy_timeout 5000`, WAL, `query_only` when read-only.

What changes: `synchronous = NORMAL`. Under WAL that is durable across an
application crash -- every committed transaction is in the WAL file -- and can
lose the last transactions only to a power cut or an OS crash, which is the
trade `docs/DECISIONS.md` 2026-10-12 records. `OFF` is not used anywhere.

Handles are released, not just reused: the dispatcher releases its thread's
connections after every request (`BridgeEngine.handle_request`), so between
requests nothing holds the database files -- a backup restore or a project
delete can replace them exactly as before. A job thread's connection is closed
when its thread has ended, on the next acquire by anyone, and `release()`
closes the caller's and every dead thread's. A live thread's connection is
never closed from outside: it is mid-work.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Iterator

from . import check_timing


class ConnectionPool:
    def __init__(self, path: str | Path, *, error: type[Exception], timing_step: str = "") -> None:
        self.path = Path(path)
        self._error = error
        self._timing_step = timing_step
        self._lock = threading.Lock()
        # (thread ident, read_only) -> (thread, connection). The thread object
        # is kept so a finished thread's connection can be recognised and closed.
        self._pool: dict[tuple[int, bool], tuple[threading.Thread, sqlite3.Connection]] = {}

    def _open(self, read_only: bool) -> sqlite3.Connection:
        # Timed (check_timing) where the owner asks: `calls` on a check job is
        # how many connections it actually opened.
        step = check_timing.current().step(self._timing_step) if self._timing_step else nullcontext()
        with step:
            conn = sqlite3.connect(str(self.path), timeout=5.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA journal_mode = WAL")
            if read_only:
                conn.execute("PRAGMA query_only = ON")
            if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
                conn.close()
                raise self._error("SQLite foreign-key enforcement could not be enabled")
        return conn

    @contextmanager
    def acquire(self, read_only: bool = False) -> Iterator[sqlite3.Connection]:
        """This thread's connection to the file, opened on first use."""
        thread = threading.current_thread()
        key = (thread.ident or 0, bool(read_only))
        with self._lock:
            self._close_dead_locked()
            entry = self._pool.get(key)
            if entry is None:
                conn = self._open(read_only)
                self._pool[key] = (thread, conn)
            else:
                conn = entry[1]
        try:
            yield conn
        finally:
            # A per-call connection was closed here, which discarded anything
            # the block had not committed. Same contract, now explicit.
            try:
                if conn.in_transaction:
                    conn.rollback()
            except sqlite3.ProgrammingError:
                pass  # released meanwhile; nothing to roll back on

    def release_thread(self) -> None:
        """Close the calling thread's connections (and any dead thread's)."""
        ident = threading.get_ident()
        with self._lock:
            for key in [key for key in self._pool if key[0] == ident]:
                _close_quietly(self._pool.pop(key)[1])
            self._close_dead_locked()

    def release(self) -> None:
        """Close what can be closed safely: the caller's connections and those
        of threads that have ended. A live thread's connection stays; closing
        it under a running query would raise inside that thread."""
        self.release_thread()

    def open_connections(self) -> int:
        with self._lock:
            return len(self._pool)

    def _close_dead_locked(self) -> None:
        for key, (thread, conn) in list(self._pool.items()):
            if not thread.is_alive():
                _close_quietly(conn)
                del self._pool[key]

    def __del__(self) -> None:  # best effort: a dropped repository lets go of its files
        try:
            self.release()
        except Exception:  # noqa: BLE001
            pass


def _close_quietly(conn: sqlite3.Connection) -> None:
    try:
        conn.close()
    except sqlite3.Error:
        pass
