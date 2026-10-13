"""Roles and the one ``authorize()`` rule (#236, requirement 4).

Three roles, one table, one function, shared by the desktop dispatcher
and the future hub (#80), so the two can never disagree about who may do
what:

- ``project_admin``: everything, including managing users and projects.
- ``editor``: reads, runs checks and analyses, and writes (edits,
  decisions, alignments, corrections).
- ``reporter``: reads and reports only.

Every engine method is classified by ``METHOD_ACTIONS`` into one action --
``read``, ``run_checks``, ``write``, ``manage_projects``, ``manage_users``
-- and the dispatcher asks ``authorize()`` before the method runs. The table
is total on purpose: a method missing from it is refused, and a test pins
the table against ``Methods`` so a new method cannot slip in unclassified.

Local single-user mode is implicit ``project_admin`` (the ``users.role``
column defaults to it, TEAM_ARCHITECTURE.md section 5). The ``project``
argument is unused today: roles are per installation until the hub gives a
user a role per project; the signature is the hub's so callers do not change.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Mapping


class Role(str, Enum):
    PROJECT_ADMIN = "project_admin"
    EDITOR = "editor"
    REPORTER = "reporter"


class Action(str, Enum):
    READ = "read"
    RUN_CHECKS = "run_checks"
    WRITE = "write"
    MANAGE_PROJECTS = "manage_projects"
    MANAGE_USERS = "manage_users"


ROLE_ACTIONS: dict[Role, frozenset[Action]] = {
    Role.REPORTER: frozenset({Action.READ}),
    Role.EDITOR: frozenset({Action.READ, Action.RUN_CHECKS, Action.WRITE}),
    Role.PROJECT_ADMIN: frozenset(Action),
}

ROLE_LABELS: dict[Role, str] = {
    Role.PROJECT_ADMIN: "project admin",
    Role.EDITOR: "editor",
    Role.REPORTER: "reporter",
}


class AuthorizationError(RuntimeError):
    """The caller's role does not allow the action. Mapped to the protocol
    error code ``forbidden``; the message is written for the screen."""


def parse_role(value: Any, default: Role = Role.PROJECT_ADMIN) -> Role:
    """A stored or wire role value as a Role; an unknown or empty value is
    the default, so a row written before #236 (no role column) is an admin,
    which is what a single-user installation always was."""
    try:
        return Role(str(value or "").strip())
    except ValueError:
        return default


def allowed(role: Role, action: Action) -> bool:
    return action in ROLE_ACTIONS.get(role, frozenset())


def authorize(user: Mapping[str, Any] | None, project: Any, action: Action | str) -> None:
    """Raise AuthorizationError unless ``user``'s role allows ``action``.

    ``user`` is the dict the workspace returns (``userId``, ``displayName``,
    ``role``); None is a caller the engine does not know, which is refused
    for anything but a read. ``project`` is accepted for the hub's per-project
    roles and ignored today.
    """
    wanted = Action(action) if not isinstance(action, Action) else action
    if user is None:
        if wanted is Action.READ:
            return
        raise AuthorizationError("No user is signed in; only reading is allowed.")
    role = parse_role(user.get("role"))
    if allowed(role, wanted):
        return
    name = str(user.get("displayName") or user.get("userId") or "This user")
    raise AuthorizationError(
        f"{name} is a {ROLE_LABELS[role]} and cannot {ACTION_VERBS[wanted]}."
    )


ACTION_VERBS: dict[Action, str] = {
    Action.READ: "read this project",
    Action.RUN_CHECKS: "run checks or analyses",
    Action.WRITE: "change the text, alignments or decisions",
    Action.MANAGE_PROJECTS: "import, rename, archive or remove projects",
    Action.MANAGE_USERS: "manage users",
}


def action_for_method(method: str) -> Action:
    """The action a protocol method needs; an unclassified method is refused
    (a KeyError here is a programming error the pinning test catches first)."""
    return METHOD_ACTIONS[method]


_READ = (
    "ping", "engine.info",
    "project.open", "project.list", "project.listBookProgress", "project.scan", "project.report",
    "project.collectionReport", "project.inspectImport", "project.import.status",
    "report.generate", "report.status", "report.get", "report.cancel", "report.export",
    "triage.status", "triage.results",
    "chapter.verses", "chapter.verseData",
    "housestyle.list", "housestyle.nameSuggestions", "housestyle.export",
    "collection.qaStatus",
    "languageQa.status", "languageQa.pause", "languageQa.history", "languageQa.verse",
    "languageQa.checkerSettings.get", "languageQa.learned.list", "languageQa.scopeFind", "languageQa.batches",
    "languageQa.flags.list", "languageQa.words.list", "languageQa.bookWords", "languageQa.occurrences",
    "languageQa.reference", "languageQa.related",
    "checks.status",
    "verse.get", "verse.history", "check.listForVerse", "check.validateSelection",
    "alignment.get", "alignment.getRange", "alignment.gapScan", "alignment.crossVerse.propose",
    "alignment.autoAlign.verdict", "alignment.autoAlign.status", "alignment.autoAlign.estimate",
    "alignment.status", "alignment.backups",
    "lexicon.getEntry", "settings.get", "terminology.list",
    "ai.review.status", "ai.review.listForChapter",
    "passageSemantic.status", "passageSemantic.getProjectMetadata", "passageSemantic.getCurrentPassage",
    "passageSemantic.getStaleSummary", "passageSemantic.getMigrationReport",
    "sourceSemantic.getRange", "sourceSemantic.getUnit", "sourceSemantic.getCoverageAccounts",
    "sourceSemantic.getDiagnostics",
    "targetSemantic.getRange", "targetSemantic.getUnit", "targetSemantic.getDiagnostics",
    "targetSemantic.getSearchSpans", "targetSemantic.getCapabilities",
    "semanticLocation.status", "semanticLocation.getRange", "semanticLocation.getRelationship",
    "semanticLocation.getCandidates", "semanticLocation.getDiagnostics",
    "meaningAnalysis.status", "meaningAnalysis.getRange", "meaningAnalysis.getAssessment",
    "meaningAnalysis.getComponents", "meaningAnalysis.getDiagnostics",
    "qaAudit.status", "qaAudit.getRange", "qaAudit.getSourceCoverage", "qaAudit.getTargetSupport",
    "qaAudit.getFinding", "qaAudit.getDiagnostics",
    "qaReview.getQueue", "qaReview.getFinding",
    "correction.getEligibility", "correction.getReviewContext", "correction.getProposal",
    "correction.listForFinding", "correction.getProposalHistory", "correction.getApplicationStatus",
    "correction.getVerification",
    "reviewHistory.getEntityHistory",
    "analysisJob.status", "analysisJob.getRecent", "analysisJob.getScopeStatus",
    "paratext.getState", "issueResolution.list", "logos.getState",
    "navigation.status", "navigation.poll", "navigation.bridgeChanged", "navigation.resolve",
    "users.list", "users.setCurrent",
)

_RUN_CHECKS = (
    "checks.start", "checks.cancel", "checks.retry", "verse.runChecks",
    "collection.runChecks", "collection.pauseChecks", "collection.cancelChecks",
    "triage.run", "triage.cancel",
    "alignment.autoAlign.start", "alignment.autoAlign.cancel", "alignment.autoAlign.retry",
    "alignment.crossVerse.aiPropose", "alignment.window.autoAlign", "alignment.aiPropose",
    "ai.review.start", "ai.review.cancel", "ai.review.retry",
    "analysisJob.start", "analysisJob.cancel",
    "passageSemantic.rebuildCurrentPassage", "sourceSemantic.buildRange", "targetSemantic.buildRange",
    "semanticLocation.runRange", "meaningAnalysis.runRange", "qaAudit.runRange",
)

_WRITE = (
    "verse.decide", "verse.edit", "check.saveSelection", "check.clearSelection",
    "alignment.crossVerse.link", "alignment.crossVerse.unlink", "alignment.null.set", "alignment.null.clear",
    "alignment.autoAlign.revert", "alignment.realign", "alignment.unalign", "alignment.save",
    "alignment.complete", "alignment.undo", "alignment.restore", "alignment.aiApplyProposal",
    "housestyle.record", "housestyle.setState", "housestyle.import",
    "languageQa.inline", "languageQa.setPack", "languageQa.checkerSettings.set",
    "languageQa.learned.forget", "languageQa.learned.restore", "languageQa.scopeApply", "languageQa.batchUndo",
    "languageQa.flags.add", "languageQa.flags.update", "languageQa.flags.delete", "languageQa.words.add",
    "terminology.record", "export.aligned", "export.nonAligned",
    "triage.override", "triage.clear",
    "qaReview.decideFinding", "qaReview.addNote",
    "correction.createProposal", "correction.editProposal", "correction.rejectProposal",
    "correction.regenerateProposal", "correction.applyProposal", "correction.reanalyzeAffected",
    "correction.verifyApplication", "correction.acknowledgeCorrected",
    "semanticReview.decideLocation", "semanticReview.decideMeaning",
    "issueResolution.save", "issueResolution.queueParatext", "issueResolution.retryParatext",
    "paratext.setReference", "logos.setReference", "settings.set",
)

_MANAGE_PROJECTS = (
    "project.import", "project.import.start", "project.import.cancel",
    "project.forget", "project.delete", "project.rename", "project.archive", "project.unarchive",
)

# #237: anyone may see who exists and sign in as themselves at startup; only
# a project_admin changes the list.
_MANAGE_USERS: tuple[str, ...] = (
    "users.create", "users.rename", "users.deactivate", "users.setRole",
)

METHOD_ACTIONS: dict[str, Action] = {
    **{m: Action.READ for m in _READ},
    **{m: Action.RUN_CHECKS for m in _RUN_CHECKS},
    **{m: Action.WRITE for m in _WRITE},
    **{m: Action.MANAGE_PROJECTS for m in _MANAGE_PROJECTS},
    **{m: Action.MANAGE_USERS for m in _MANAGE_USERS},
}

# The request keys a caller may not use to name its own actor (#183, DECISIONS
# 2026-10-12): the engine attributes every write itself.
ACTOR_WIRE_KEYS: tuple[str, ...] = ("actorId", "actor", "requestedBy")


LEGACY_HUMAN_ACTOR = "human"
LEGACY_HUMAN_LABEL = "legacy:human"


def display_actor_id(actor_id: Any) -> str:
    """#237: a row written before identity existed (#78) carries the literal
    actor id "human". Readers show it as `legacy:human` and never rewrite or
    reassign it: that row genuinely has no known author."""
    value = str(actor_id or "").strip()
    return LEGACY_HUMAN_LABEL if value == LEGACY_HUMAN_ACTOR else value


def refuse_named_actor(params: Mapping[str, Any] | None) -> None:
    """Raise AuthorizationError when a request names its actor."""
    if not isinstance(params, Mapping):
        return
    named = [key for key in ACTOR_WIRE_KEYS if key in params]
    if named:
        raise AuthorizationError(
            f"The request names its actor ({', '.join(named)}); Bridge attributes every write to the "
            "signed-in user itself and refuses a request that claims otherwise."
        )
