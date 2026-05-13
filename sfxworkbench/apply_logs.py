"""Shared scaffolding for review/apply/undo workflows.

Three concerns live here:

1. Log paths — every command writes a timestamped JSON envelope to an
   ``apply_logs/`` folder beside the plan being applied.
2. Review helpers — two distinct patterns are used in this codebase:

   * **Per-entry**: ``DeletePlanEntry`` etc. carry a ``review_status`` field
     set to ``"pending" | "approved" | "rejected"``. ``mark_entries_reviewed``
     is the loop that updates those statuses given approve/reject ID sets.
   * **Top-level group index**: ``dedupe``, ``packs`` and ``organize`` keep
     a ``plan["review"]`` dict listing 0-based approved positions instead of
     stamping per-entry statuses. ``mark_groups_approved`` handles that.

3. Apply envelope — ``write_apply_log`` and ``apply_session`` build the
   standard ``{schema_version, generated_at, tool, tool_version, plan_path,
   result}`` JSON every apply function writes when ``dry_run=False``.

Public surface is intentionally small; modules continue to expose their own
``review_*`` / ``apply_*`` functions and just delegate the boilerplate here.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sfxworkbench.utils import atomic_write_json

APPLY_LOG_DIR_NAME = "apply_logs"


def now_iso() -> str:
    """UTC ISO-8601 timestamp used in every apply-log envelope."""
    return datetime.now(UTC).isoformat()


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def apply_log_dir(base_dir: Path | None = None) -> Path:
    """Return the standard folder for apply logs."""
    if base_dir is None:
        return Path(APPLY_LOG_DIR_NAME)
    return Path(base_dir) / APPLY_LOG_DIR_NAME


def default_apply_log_path(prefix: str, *, base_dir: Path | None = None) -> Path:
    """Build a timestamped apply log path under the standard log folder."""
    return apply_log_dir(base_dir) / f"{prefix}_{_now_stamp()}.json"


def default_apply_log_path_for_plan(plan_path: Path, prefix: str) -> Path:
    """Build a timestamped apply log path beside a plan/report file."""
    return default_apply_log_path(prefix, base_dir=Path(plan_path).expanduser().parent)


def mark_entries_reviewed(
    by_id: dict[int, Any],
    *,
    approve: Iterable[int] | None = None,
    reject: Iterable[int] | None = None,
    approve_all: bool = False,
    status_field: str = "review_status",
) -> list[int]:
    """Stamp per-entry ``review_status`` for the per-entry review pattern.

    Mutates the objects in ``by_id`` in place; returns the sorted list of
    invalid (unknown) IDs the caller asked about so they can be surfaced.
    Already-approved/rejected entries hit by ``approve_all`` are re-stamped
    idempotently.
    """
    approve_set = set(approve or [])
    reject_set = set(reject or [])
    if approve_all:
        approve_set.update(by_id)
    known = set(by_id)
    invalid = sorted((approve_set | reject_set) - known)
    for entry_id in sorted(approve_set & known):
        setattr(by_id[entry_id], status_field, "approved")
    for entry_id in sorted(reject_set & known):
        setattr(by_id[entry_id], status_field, "rejected")
    return invalid


def mark_groups_approved(
    plan: dict,
    *,
    requested_1based: Iterable[int] | None = None,
    approve_all: bool = False,
    items_key: str,
    approved_key: str,
) -> tuple[list[int], list[int], int]:
    """Stamp ``plan["review"]`` for the top-level-index review pattern.

    Used by dedupe / packs / organize where individual entries don't carry a
    status field. Stores 0-based positions under
    ``plan["review"][approved_key]`` and a ``status`` of ``"approved"`` if
    every group is approved, else ``"partially_approved"``.

    Returns ``(approved_0based, invalid_1based, total)``.
    """
    total = len(plan.get(items_key, []))
    requested = set(requested_1based or [])
    invalid = sorted(group for group in requested if group < 1 or group > total)
    if approve_all:
        approved = set(range(total))
    else:
        approved = {group - 1 for group in requested if 1 <= group <= total}
    existing = plan.get("review", {})
    approved.update(existing.get(approved_key, []))
    approved_sorted = sorted(approved)
    plan["review"] = {
        "status": "approved" if total and len(approved_sorted) == total else "partially_approved",
        "approved_at": now_iso(),
        approved_key: approved_sorted,
    }
    return approved_sorted, invalid, total


def build_apply_log_envelope(
    *,
    plan_path: Path,
    tool_version: str,
    result: Any,
    schema_version: int = 1,
    tool: str = "sfxworkbench",
    extra: dict | None = None,
) -> dict:
    """Construct the standard apply-log JSON envelope."""
    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "generated_at": now_iso(),
        "tool": tool,
        "tool_version": tool_version,
        "plan_path": str(plan_path),
        "result": result,
    }
    if extra:
        payload.update(extra)
    return payload


def write_apply_log(
    log_path: Path,
    *,
    plan_path: Path,
    tool_version: str,
    result: Any,
    schema_version: int = 1,
    tool: str = "sfxworkbench",
    extra: dict | None = None,
) -> None:
    """Write the standard apply-log envelope to ``log_path`` atomically."""
    payload = build_apply_log_envelope(
        plan_path=plan_path,
        tool_version=tool_version,
        result=result,
        schema_version=schema_version,
        tool=tool,
        extra=extra,
    )
    atomic_write_json(log_path, payload)


@contextmanager
def apply_session(
    *,
    plan_path: Path,
    dry_run: bool,
    log_path: Path | None,
    log_prefix: str,
    tool_version: str,
    result: Any,
    schema_version: int = 1,
    tool: str = "sfxworkbench",
    extra_factory: Any | None = None,
) -> Iterator[Path | None]:
    """Manage apply-log path resolution and writing.

    Yields the resolved ``log_path`` (or ``None`` if dry-run with no explicit
    path) so callers can stash it on their result. After the body exits
    successfully and ``dry_run`` is False, writes the envelope.

    ``extra_factory`` is an optional zero-arg callable invoked at write time
    to provide extra envelope keys (e.g. quarantine entry dumps); evaluated
    after the body so it sees the final result.

    If the ``with`` block raises, the log is NOT written — partial-state apply
    logs would mislead an undo and the matching apply functions already record
    expected per-entry failures in ``result.errors``.
    """
    resolved = log_path
    if resolved is None and not dry_run:
        resolved = default_apply_log_path_for_plan(plan_path, log_prefix)
    yield resolved
    if resolved is not None and not dry_run:
        extra = extra_factory() if callable(extra_factory) else None
        write_apply_log(
            resolved,
            plan_path=plan_path,
            tool_version=tool_version,
            result=result,
            schema_version=schema_version,
            tool=tool,
            extra=extra,
        )
