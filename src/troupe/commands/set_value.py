"""``troupe config set PATH VALUE``: change one value byte-surgically, record it (FR-010..023).

``--in-include`` (include-overrides FR-010) is passed through to ``apply_set``: a new key under
included content goes into the included file instead of becoming an override in the including
file. Recording is the same with or without it (FR-013): one event per changed leaf, with the
usual lineage; converting an include to mapping form changes no leaf, so it records nothing.

``--expand-alias`` (spec FR-005, C7-C10; research R-8, R-10) is passed through to ``apply_set``:
every alias on PATH is expanded into a copy of its anchored node and VALUE is set in the copy,
as one write of one file and one verification. Without it a PATH reached through an alias or a
merge key is refused (exit 3, FR-004). Recording is unchanged (C11): one event per resolved leaf
whose value changed, so a set at an anchor records every alias path that sees it, and an
expand-and-set normally records only PATH (the copy has the same values).

Order (plan "Engineering Alignment"; research R-04, R-12, R-17):

1. Parse PATH and VALUE: a usage error (exit 2) happens before anything is loaded, imported or
   reconciled.
2. Open the session: lock, load, import or reconcile. Reconcile events are saved here, so they
   are kept even if the steps below refuse or fail (D-7).
3. ``apply_set``: decide placement, render, verify in memory. Refusals (exit 3) and path errors
   (exit 5) happen here, before any write; a no-op returns no files.
4. Write the changed file(s) atomically.
5. Only after a successful write, append one event per changed leaf (``leaves.diff`` of the tree
   before and the verified tree after). The tree before is the reconciled one, so ``old`` is
   the current file value (FR-007). A failed write appends nothing. These events are the set's
   own change: they share one ``cli_lineage`` built from the resolved actor and ``--reason``
   (FR-004, FR-008, FR-009), separate from any import or reconcile change of step 2 (FR-010).
   A no-op, refused or failed set records nothing, so its reason is not kept (FR-014).

``--include`` (step 7, S-12, S-13) is passed through to ``apply_set``: include-looking strings
in VALUE are written untagged, as includes, instead of ``!literal``; a new include that cannot be
read or fetched, or one on a path the schema marks ``format: uri``, is refused (exit 3).

Remote includes and the schema (step 7; research R-7, R-10): ``apply_set`` gets the session's
theatre, schema and fetched remote texts (``SetContext``), so its in-memory reloads read the
same snapshot of remote content without fetching a URL twice, and a result that would not match
the schema is refused (exit 3, S-9) before anything is written. Remote content is never written
(S-4): ``apply_set`` refuses it, and ``write_files`` refuses it once more.

Steps 3-5 run inside the session, under the theatre lock, so the write-back and its events
are one unit that no reconcile can observe half-done (FR-015).

Success prints nothing.
"""

import argparse

from troupe.errors import WriteRefused
from troupe.leaves import diff, flatten
from troupe.lineage import Actor, cli_lineage
from troupe.paths import parse_path
from troupe.session import open_session
from troupe.theatre import Theatre
from troupe.values import parse_value
from troupe.writeback.apply import SetContext, apply_set
from troupe.writeback.fileio import write_files


def run(theatre: Theatre, args: argparse.Namespace, actor: Actor) -> str:
    """Set ``args.path`` to ``args.value``; return the (empty) stdout text.

    The set's own events are attributed to ``actor``, via ``cli``, with ``args.reason``.
    ``args.in_include`` selects the included file for a new key (``set --in-include``);
    ``args.expand_alias`` expands the aliases on PATH before setting (``set --expand-alias``);
    ``args.include`` writes include-looking strings in VALUE as includes (``set --include``).

    Raises:
        UsageError: If PATH has an empty segment or VALUE is not one YAML flow node (exit 2).
        LoadError: If the configuration cannot be loaded (exit 4).
        WriteRefused: If the change cannot be written as contracted, or writing failed (exit 3).
        PathError: If PATH cannot be reached or created (exit 5).
    """
    path: str = args.path
    raw_value: str = args.value
    reason: str | None = args.reason
    in_include: bool = args.in_include
    expand_alias: bool = args.expand_alias
    include: bool = args.include
    segments = parse_path(path)
    value = parse_value(raw_value)
    with open_session(theatre, reconcile=True) as session:
        plan = apply_set(
            session.tree,
            segments,
            path,
            value,
            raw_value,
            in_include=in_include,
            expand_alias=expand_alias,
            include=include,
            context=SetContext(session.theatre, session.schema, session.fetched),
        )
        if plan.tree is None:
            return ""
        changes = diff(flatten(session.tree), flatten(plan.tree))
        try:
            write_files(plan.files)
        except OSError as err:
            names = ", ".join(str(file.path) for file in plan.files)
            raise WriteRefused(f"{path}: cannot write {names}: {err.strerror or err}") from err
        session.history.record(changes, cli_lineage(actor, reason))
    return ""
