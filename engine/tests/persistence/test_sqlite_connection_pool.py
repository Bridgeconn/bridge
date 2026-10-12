"""#113: one SQLite connection per thread per file, reused and released."""
from __future__ import annotations

import shutil
import sqlite3
import threading

from tc_ai_bridge.sqlite_pool import ConnectionPool
from tc_ai_bridge.workbench_repository import WorkbenchRepository


class Boom(Exception):
    pass


def _pool(tmp_path) -> ConnectionPool:
    return ConnectionPool(tmp_path / "pool.sqlite3", error=Boom)


def test_the_same_thread_gets_the_same_connection_and_another_thread_its_own(tmp_path):
    pool = _pool(tmp_path)
    with pool.acquire() as first:
        first.execute("CREATE TABLE t(x)")
        first.commit()
    with pool.acquire() as again:
        pass
    assert again is first
    assert pool.open_connections() == 1

    seen = {}

    def worker():
        with pool.acquire() as conn:
            seen["conn"] = conn
            conn.execute("SELECT 1").fetchone()

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert seen["conn"] is not first
    # The worker has ended: its connection is closed on the next acquire by anyone.
    with pool.acquire():
        pass
    assert pool.open_connections() == 1


def test_pragmas_are_the_product_ones_with_normal_under_wal(tmp_path):
    pool = _pool(tmp_path)
    with pool.acquire() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pool.acquire(read_only=True) as ro:
        assert ro.execute("PRAGMA query_only").fetchone()[0] == 1
    assert pool.open_connections() == 2  # read-only is its own connection


def test_a_block_that_ends_without_committing_discards_its_work(tmp_path):
    """A per-call connection was closed on exit, which rolled back; the reused
    one must not leak an open transaction into the next caller."""
    pool = _pool(tmp_path)
    with pool.acquire() as conn:
        conn.execute("CREATE TABLE t(x)")
        conn.commit()
    with pool.acquire() as conn:
        conn.execute("INSERT INTO t VALUES (1)")
        assert conn.in_transaction
    with pool.acquire() as conn:
        assert not conn.in_transaction
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0


def test_release_thread_closes_and_the_next_acquire_reopens(tmp_path):
    pool = _pool(tmp_path)
    with pool.acquire() as first:
        pass
    pool.release_thread()
    assert pool.open_connections() == 0
    with pool.acquire() as second:
        assert second is not first
        second.execute("SELECT 1").fetchone()
    # The old handle is closed, not merely forgotten.
    try:
        first.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        pass
    else:
        raise AssertionError("the released connection is still open")


def test_a_released_repository_lets_the_file_be_deleted(tmp_path):
    """What the per-request release is for: a delete or a restore can replace
    the files, as it could when every call closed its connection."""
    root = tmp_path / "project"
    repo = WorkbenchRepository(root / "bridge-workbench.sqlite3")
    with repo._connect() as conn:
        conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()
    assert repo._pool.open_connections() == 1
    repo.release_connections()
    assert repo._pool.open_connections() == 0
    shutil.rmtree(root)
    assert not root.exists()
