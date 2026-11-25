# Proofreading toolkit (`bible-qa-universal`)

Bridge-owned code since 2026-11-25 (#505). It is **not** a vendored upstream
tree: it has no upstream repository. Yesu Selva Benz wrote it as a Claude skill
("Bible proofreading QA, any language, any reference Bible"), generalised from
the Telugu IRV Round 2 check, and shared the folder with the team.

## What is here

Copied unchanged from the shared folder on 2026-11-25, line endings included
(`.gitattributes` marks the folder `-text`):

| Path | What it is |
|---|---|
| `SKILL.md` | The procedure, the checks, the rules a finding must follow |
| `guides/` | The meaning and theology checklist; how a language's rules are built |
| `profiles/generic`, `profiles/te` | Language profiles. Telugu has rules, 32 lead patterns and `minority.py` |
| `templates/` | The example config and the findings-file template |
| `tools/` | 15 command-line tools and the two modules they share (`project.py`, `corpus.py`) |

`README.md` is Benz's own description. Read it for what each tool does.

## How Bridge runs it

Bridge does not run the skill in a Claude session. The engine does the steps of
`SKILL.md` section 2 itself and asks its own AI client (an API key or a ChatGPT
sign-in) to be the reader:

- `engine/proofread_tool_main.py` runs one tool per process (`bridge-engine
  --proofread-tool <tool> ...` when frozen). It forces UTF-8 output and accepts
  only the tool names it lists.
- `engine/tc_ai_bridge/proofreading.py` stages copies of the text, writes
  `config.json`, builds the AI's instructions from `SKILL.md`, the guides and
  the profile, and writes each book's `rows_<book>.py`.
- `engine/proofreading_jobs.py` is the run.

## Rules for this folder

- **The tools see staged copies only.** `tools/project.py` reads USFM with its
  own regular expressions. CLAUDE.md gotcha 14 allows that nowhere else in
  Bridge; the exception for this folder is recorded in `docs/DECISIONS.md`
  (2026-11-25, Joel for the team, to be looked at again by the maintainer). It
  holds because the tools run in their own process on files Bridge wrote for
  them, and nothing they parse is ever read back as Scripture.
- **No tool writes a project.** Their outputs go to the run's `output` and
  `work` folders under Bridge's data folder.
- **`build.py` executes `rows_<book>.py`.** Bridge writes that file itself from
  findings the AI returned as data, each string through `repr()`. Text from a
  model is never executed.
- **`corpus.py` keeps a pickle cache in the work folder.** Only the tools write
  there.
- **A change to a file here is a change to Bridge.** Say what changed and why in
  the list below, so a later copy from Benz can be compared.

## Changes from the shared copy

None.

## Found while integrating (2026-11-25, on Windows, Malayalam IRV)

- `sweep.py` and `dump.py` crash with `UnicodeEncodeError` on the first verse
  they print when stdout is the Windows default (`cp1252`). The runner sets
  UTF-8; run by hand they need `python -X utf8`.
- `terms.py` leaves with a message and exit code 1 when the project has no
  `ProjectBiblicalTerms.xml` / `TermRenderings.xml`. That is "skipped", not a
  failure.
- `build.py` exits 0 whether or not a finding failed to be located. The count
  is in its output (`'fail': N`) and each failure is a `FAIL` line.
- `build.py` loads `rows_<book>.py` through the import machinery, which leaves
  a compiled copy in `rows/__pycache__` and trusts it while the file's size and
  modification second are unchanged. A findings file rewritten within the same
  second to the same length is ignored and the old findings are verified. The
  runner writes no bytecode and Bridge clears that folder before each write.
- `queue.py next` hands books out in canonical order, whatever order the scope
  named them in.
- `cost.py`'s estimate is calibrated on a Claude session that re-reads its
  context on every step (43 million cached tokens for Daniel to Malachi). It
  does not describe Bridge's requests, so Bridge shows its own estimate before
  a run.
- `deliver.py` stamps note dates in a fixed +05:30 offset.
- Not wired in the first build: `make_profile.py` and `approve_candidates.py`.
  Drafting a profile for a new language needs a linguist's approval step that
  Bridge has no screen for yet.
