"""The link from an imported book to its Paratext project folder (#356).

An import records the link as ``paratext`` in every sibling's
``.bridge/collection.json`` (#355); that file is its one record. Resolving it
never stops a project from opening: a consumer that finds no linked folder
reports "no Paratext data" with the state string and carries on.

States:

- ``linked``: the folder exists and its ``Settings.xml`` has the link's Guid.
- ``folderMoved``: the folder does not hold this project, but a folder with
  the same Guid exists under Paratext's projects folder (``candidate``).
- ``guidMismatch``: the folder holds a different Paratext project.
- ``folderMissing``: the folder is gone and no candidate was found.
- ``notParatext``: the book was not imported from a Paratext project.

Reading is the reader module's job (``paratext_project``); the only write here
is :func:`relink`, which rewrites ``paratext.folder`` in each sibling's
``collection.json``. Nothing here ever writes into a Paratext folder.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .paratext_install import _registry_values
from .paratext_project import ParatextSettings, read_settings
from .project_import import _COLLECTION_PATH, _read_json, collection_projects
from .tc_project import ProjectError, _write_json_atomic

LINKED = "linked"
FOLDER_MISSING = "folderMissing"
GUID_MISMATCH = "guidMismatch"
FOLDER_MOVED = "folderMoved"
NOT_PARATEXT = "notParatext"

DEFAULT_PROJECTS_DIR = Path(r"C:\My Paratext 9 Projects")


class ParatextLinkError(ProjectError):
    """A relink that would point the book at the wrong Paratext project."""


def paratext_projects_dir(registry: Callable[[], dict[str, str]] = _registry_values) -> Path | None:
    """Paratext 9's projects folder (``Settings_Directory`` in its registry
    key), or the default folder when that exists; None otherwise."""
    value = registry().get("Settings_Directory", "").strip()
    if value and Path(value).is_dir():
        return Path(value)
    return DEFAULT_PROJECTS_DIR if DEFAULT_PROJECTS_DIR.is_dir() else None


def find_project_by_guid(projects_dir: Path | None, guid: str, *, exclude: Path | None = None) -> Path | None:
    """The folder directly under ``projects_dir`` whose ``Settings.xml`` has
    ``guid``. Only each folder's ``Settings.xml`` is read."""
    if projects_dir is None or not guid or not projects_dir.is_dir():
        return None
    wanted = guid.lower()
    try:
        children = sorted(p for p in projects_dir.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return None
    for folder in children:
        if exclude is not None and _same_path(folder, exclude):
            continue
        if not (folder / "Settings.xml").is_file():
            continue
        settings = read_settings(folder)
        if settings is not None and settings.guid.lower() == wanted:
            return folder
    return None


def _same_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return str(a).lower() == str(b).lower()


def read_link(project_root: str | Path) -> dict[str, Any] | None:
    """The ``paratext`` block of this book's ``collection.json``, or None."""
    data = _read_json(Path(project_root) / _COLLECTION_PATH)
    block = data.get("paratext") if isinstance(data, dict) else None
    if isinstance(block, dict) and block.get("guid") and block.get("folder"):
        return block
    return None


@dataclass(frozen=True)
class LinkResolution:
    state: str
    link: dict[str, Any] | None
    settings: ParatextSettings | None = None     # the linked folder's, when state is linked
    candidate: Path | None = None                # when state is folderMoved

    @property
    def guid(self) -> str:
        return str((self.link or {}).get("guid") or "")

    @property
    def folder(self) -> Path | None:
        return Path(str(self.link["folder"])) if self.link else None

    @property
    def linked(self) -> bool:
        return self.state == LINKED


def resolve(project_root: str | Path, *,
            projects_dir: Callable[[], Path | None] | None = None) -> LinkResolution:
    """Where this book's Paratext project is now. Never raises for a missing
    or changed folder: that is a state. ``projects_dir`` defaults to
    :func:`paratext_projects_dir`, looked up at call time."""
    projects_dir = projects_dir or (lambda: paratext_projects_dir())
    link = read_link(project_root)
    if link is None:
        return LinkResolution(NOT_PARATEXT, None)
    folder = Path(str(link["folder"]))
    guid = str(link["guid"])
    settings = read_settings(folder) if folder.is_dir() else None
    if settings is not None and settings.guid.lower() == guid.lower():
        return LinkResolution(LINKED, link, settings=settings)
    candidate = find_project_by_guid(projects_dir(), guid, exclude=folder)
    if candidate is not None:
        return LinkResolution(FOLDER_MOVED, link, candidate=candidate)
    if settings is not None:
        return LinkResolution(GUID_MISMATCH, link)
    return LinkResolution(FOLDER_MISSING, link)


def relink(project_root: str | Path, folder: str | Path, *,
           now: Callable[[], str] | None = None) -> list[Path]:
    """Point every book of the collection at ``folder``.

    The folder must hold a Paratext project with the link's Guid; anything
    else is refused. Rewrites ``paratext.folder`` (and ``relinkedAt``) in this
    book's ``collection.json`` and every sibling's, keeping every other key.
    Returns the files written. A sibling that cannot be written is skipped;
    this book's own copy must be."""
    root = Path(project_root).resolve()
    link = read_link(root)
    if link is None:
        raise ParatextLinkError("This project was not imported from a Paratext project.")
    target = Path(folder).resolve()
    settings = read_settings(target)
    if settings is None:
        raise ParatextLinkError(f"{target} is not a Paratext project folder (no Settings.xml).")
    if settings.guid.lower() != str(link["guid"]).lower():
        raise ParatextLinkError(
            f"{target} holds the Paratext project {settings.name or '?'} ({settings.guid}), "
            f"not the one this book was imported from ({link['guid']})."
        )
    stamp = (now or (lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")))()
    written = [_rewrite_folder(root / _COLLECTION_PATH, target, stamp)]
    for sibling in collection_projects(root):
        path = Path(str(sibling.get("path") or "")) / _COLLECTION_PATH
        if _same_path(path.parent.parent, root) or not path.is_file():
            continue
        try:
            written.append(_rewrite_folder(path, target, stamp))
        except (OSError, ValueError, ParatextLinkError):
            continue
    return written


def _rewrite_folder(path: Path, folder: Path, stamp: str) -> Path:
    data = _read_json(path)
    block = data.get("paratext") if isinstance(data, dict) else None
    if not isinstance(block, dict):
        raise ParatextLinkError(f"{path} has no Paratext link.")
    block = copy.deepcopy(block)
    block["folder"] = str(folder)
    block["relinkedAt"] = stamp
    data["paratext"] = block
    _write_json_atomic(path, data)
    return path
