# Project Charter — troupe configuration subsystem

Curated companion to `.kittify/charter/charter.yaml`. The YAML is authoritative for
policy (`governance`, `directives` TROUPE-001…009, and the `activated_*` keys).
Spec Kitty also injects the **Policy Summary** bullets below into each action's
bootstrap context, so keep them in step with the TROUPE directives.

## Policy Summary

- Preserve user files byte-for-byte: never reformat, reorder or rewrite anything in `troupe.yml`/`troupe.yaml` the user did not ask to change; use format-preserving YAML round-tripping and test that untouched bytes are identical (TROUPE-001).
- When unsure, take the conservative choice that cannot lose or corrupt user data (refuse rather than guess; atomic temp-file + rename writes) and state what you chose and why (TROUPE-002).
- Every error message names the path or file involved (TROUPE-003).
- Fixed constraints: Python 3.12+ with uv; CLI runs as `uv run troupe config …` from the repo root; `eventsourcing` for the event store and projection; config at `<theatre>/.troupe/troupe.yml` (or `.yaml`); macOS/Linux only; no performance targets (TROUPE-004).
- Every behaviour has a test that fails when it breaks; test names state what they prove and bodies check exactly that; test against real files, real CLI output and the real eventsourcing library, not stand-ins (TROUPE-005).
- Done means verified: run `uv run pytest`, `uv run mypy --strict`, `uv run ruff check` and `ruff format --check`, and show the output before claiming success (TROUPE-006).
- Keep each decision in one named place; build for the current stage only, easy to change (TROUPE-007).
- Deliver the whole scope or say what cannot be done; never invent requirements — search the repo/contract/docs first, then ask the product owner with findings, options and a recommendation; where the contract leaves a choice open, make it and record why. Keep spec, code and tests in agreement in the same change; commit small with messages that say why (TROUPE-008, TROUPE-009).

## What this project is

troupe runs teams of AI agents. This repository is its configuration subsystem: a
command-line tool over YAML configuration files that developers edit by hand and
review as diffs. It is built in stages and requirements will change; build for the
current stage in a way that is easy to change.

The most costly failure is losing or corrupting a user's configuration file. Users
value their files staying exactly as they wrote them over speed.

## Quality gates

| Gate | Command |
|---|---|
| Tests | `uv run pytest` |
| Types | `uv run mypy --strict` (code fully typed) |
| Lint / format | `uv run ruff check`, `uv run ruff format --check` |

There is no numeric coverage target: behaviour coverage is the bar — every behaviour
has a test that would fail if that behaviour broke. A test that passes whatever the
code does is worse than no test.

## Review checklist

1. Spec, code and tests agree; a behaviour change updates all three together.
2. Every new or changed behaviour has a test whose name matches what its body asserts.
3. No user file content is changed beyond what was asked.
4. Error messages name the path or file.
5. Each decision lives in one named place.
6. The whole requested scope is delivered, or gaps are stated explicitly.
7. Gate output was actually run and shown.

## Working with the product owner

The product owner decides what to build. Do not invent requirements. Before asking,
look in the repository, the contract and the documents provided; then ask with what
you found, the options and your recommendation. Where the contract leaves a choice
open, make it and record what you chose and why.

## Exceptions and amendments

No silent exceptions: if a requirement or gate cannot be met, say so with the reason,
file a beads issue, and record significant cases as a decision record. Charter
changes are made in `.kittify/charter/` (answers.yaml / charter.yaml / this file) in a
dedicated commit that explains why.

## Doctrine selection and gaps

Built-in directives activated: DIRECTIVE_001 (architectural integrity), 003 (decision
documentation), 010 (specification fidelity), 024 (locality of change), 030 (test and
typecheck gate), 033 (targeted staging), 036 (black-box integration testing), 037
(living documentation sync), 041 (tests as scaffold, not friction). Styleguides:
python-conventions, testing-principles. Toolguide: python-review-checks. No paradigms
are selected — none was asked for.

Doctrine gaps, encoded as project directives rather than forced near-matches:
byte-for-byte preservation of hand-edited files (TROUPE-001), conservative data-safe
defaults (TROUPE-002), path-naming error messages (TROUPE-003), one decision per named
place (TROUPE-007), and the product-owner question protocol (TROUPE-008).

## Choices made where the input was silent

- Test runner: **pytest** (not specified; the standard for uv/Python projects).
- Writes to user configuration are **atomic** (temp file + rename) — the conservative
  data-safety choice.
- If both `troupe.yml` and `troupe.yaml` exist, **refuse with an error naming both**
  rather than pick one silently. This is a provisional default; the product owner
  should confirm it in the first specification.
- No commit-message convention (e.g. Conventional Commits) is imposed; only "small
  steps, messages say why".
- `pr_approvals: 1` is the Spec Kitty default and was left unchanged.
