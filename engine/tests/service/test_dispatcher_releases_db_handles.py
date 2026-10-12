"""#113: the dispatcher reuses its database connections within a request and
releases them after it, so between requests nothing holds the files; and a
project that is replaced lets go of its files."""
from __future__ import annotations

import shutil

from bridge_service import BridgeEngine
from tests.support.projects import call, fixture_project  # noqa: F401  (pytest fixture)


def test_the_dispatcher_releases_its_handles_after_every_request(fixture_project):
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(fixture_project)})["success"] is True
    project = engine.project
    # project.open itself used the workbench many times and released at the end.
    assert project.workbench._pool.open_connections() == 0
    # A direct use outside a request holds one, as a job thread would.
    with project.workbench._connect() as conn:
        conn.execute("SELECT 1").fetchone()
    assert project.workbench._pool.open_connections() == 1
    # Any request releases this thread's handles on the way out.
    assert call(engine, "ping", {})["success"] is True
    assert project.workbench._pool.open_connections() == 0


def test_opening_another_project_lets_the_previous_files_go(fixture_project, tmp_path):
    second = tmp_path / "rut-second"
    shutil.copytree(fixture_project, second)
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(fixture_project)})["success"] is True
    first = engine.project
    with first.workbench._connect() as conn:
        conn.execute("SELECT 1").fetchone()
    assert first.workbench._pool.open_connections() == 1

    assert call(engine, "project.open", {"path": str(second)})["success"] is True
    assert engine.project is not first
    assert first.workbench._pool.open_connections() == 0
    # The point of letting go: the folder can be removed or replaced.
    shutil.rmtree(fixture_project)
    assert not fixture_project.exists()
