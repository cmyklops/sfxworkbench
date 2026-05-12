"""Report-only related sound group detection."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from sfxworkbench import __version__
from sfxworkbench.db import get_connection
from sfxworkbench.models import RelatedGroupsReport, RelatedGroupsSummary, RelatedSoundFile, RelatedSoundGroup

console = Console()

_SEPARATOR_RE = re.compile(r"[\s._-]+")
_TRAILING_NUMBER_RE = re.compile(
    r"^(?P<base>.+?)(?:[\s._-]*(?:take|tk)?[\s._-]*)?(?P<number>\d{1,4})$",
    re.IGNORECASE,
)
_TRAILING_CHANNEL_RE = re.compile(
    r"^(?P<base>.+?)[\s._-]+(?P<channel>l|r|left|right|mid|side|ms|mono|stereo|ortf|xy)$",
    re.IGNORECASE,
)


@dataclass
class _GroupBucket:
    parent_path: Path
    inferred_stem: str
    reason: str
    files: list[RelatedSoundFile] = field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _group_key(value: str) -> str:
    return _SEPARATOR_RE.sub(" ", value).strip().casefold()


def _has_enough_letters(value: str) -> bool:
    return len(re.sub(r"[^A-Za-z]", "", value)) >= 3


def _infer_related_key(stem: str) -> tuple[str, str, str, str] | None:
    channel_match = _TRAILING_CHANNEL_RE.match(stem)
    if channel_match:
        base = channel_match.group("base").strip(" -_.")
        if _has_enough_letters(base):
            marker = channel_match.group("channel").upper()
            return _group_key(base), base, "channel_set", marker

    number_match = _TRAILING_NUMBER_RE.match(stem)
    if number_match:
        base = number_match.group("base").strip(" -_.")
        marker = number_match.group("number")
        if base and _has_enough_letters(base):
            return _group_key(base), base, "numbered_sequence", marker

    return None


def _load_rows(root: Path, db_path: Path):
    conn = get_connection(db_path)
    rows = conn.execute(
        """
        SELECT path, filename, stem, sample_rate, bit_depth, channels, duration_s, md5
        FROM files
        WHERE (path = ? OR path LIKE ?)
          AND scan_error IS NULL
        ORDER BY path
        """,
        (str(root), str(root) + "/%"),
    ).fetchall()
    conn.close()
    return rows


def _unique_ints(files: list[RelatedSoundFile], field_name: str) -> list[int]:
    return sorted({value for item in files if (value := getattr(item, field_name)) is not None})


def _confidence(reason: str, markers: list[str]) -> str:
    if reason == "channel_set":
        marker_set = {marker.upper() for marker in markers}
        if {"L", "R"} <= marker_set or {"LEFT", "RIGHT"} <= marker_set:
            return "high"
        return "medium"
    numeric = sorted(int(marker) for marker in markers if marker.isdigit())
    if len(numeric) >= 3:
        return "high"
    return "medium"


def _marker_sort_key(value: str | None) -> tuple[int, int | str]:
    if value is None:
        return (2, "")
    if value.isdigit():
        return (0, int(value))
    return (1, value.casefold())


def audit_related_groups(root: Path, db_path: Path, min_files: int = 2, limit: int = 200) -> RelatedGroupsReport:
    """Build a report of obvious related sound groups from indexed filenames."""
    if min_files < 2:
        raise ValueError("--min-files must be at least 2")
    if limit < 0:
        raise ValueError("--limit must be 0 or greater")

    root = root.resolve()
    rows = _load_rows(root, db_path)
    buckets: dict[tuple[str, str, str], _GroupBucket] = {}

    for row in rows:
        path = Path(row["path"])
        if not _is_relative_to(path, root):
            continue
        inferred = _infer_related_key(row["stem"] or path.stem)
        if inferred is None:
            continue
        key, inferred_stem, reason, marker = inferred
        bucket_key = (str(path.parent), key, reason)
        bucket = buckets.setdefault(
            bucket_key,
            _GroupBucket(parent_path=path.parent, inferred_stem=inferred_stem, reason=reason),
        )
        bucket.files.append(
            RelatedSoundFile(
                path=str(path),
                filename=row["filename"],
                marker=marker,
                sample_rate=row["sample_rate"],
                bit_depth=row["bit_depth"],
                channels=row["channels"],
                duration_s=row["duration_s"],
                md5=row["md5"],
            )
        )

    candidate_buckets = [bucket for bucket in buckets.values() if len(bucket.files) >= min_files]
    candidate_buckets.sort(
        key=lambda bucket: (-len(bucket.files), str(bucket.parent_path), bucket.inferred_stem.casefold())
    )
    selected = candidate_buckets if limit == 0 else candidate_buckets[:limit]

    groups: list[RelatedSoundGroup] = []
    for group_id, bucket in enumerate(selected, start=1):
        files = sorted(
            bucket.files, key=lambda item: (_marker_sort_key(item.marker), item.filename.casefold(), item.path)
        )
        markers = sorted({file.marker for file in files if file.marker is not None}, key=_marker_sort_key)
        groups.append(
            RelatedSoundGroup(
                group_id=group_id,
                parent_path=str(bucket.parent_path),
                inferred_stem=bucket.inferred_stem,
                reason=bucket.reason,
                confidence=_confidence(bucket.reason, markers),
                file_count=len(files),
                sample_rates=_unique_ints(files, "sample_rate"),
                bit_depths=_unique_ints(files, "bit_depth"),
                channels=_unique_ints(files, "channels"),
                markers=markers,
                files=files,
            )
        )

    grouped_files = sum(len(bucket.files) for bucket in candidate_buckets)
    mixed_format_groups = sum(
        1
        for bucket in candidate_buckets
        if len(_unique_ints(bucket.files, "sample_rate")) > 1
        or len(_unique_ints(bucket.files, "bit_depth")) > 1
        or len(_unique_ints(bucket.files, "channels")) > 1
    )
    summary = RelatedGroupsSummary(
        indexed_files_considered=len(rows),
        candidate_groups=len(candidate_buckets),
        reported_groups=len(groups),
        grouped_files=grouped_files,
        numbered_sequence_groups=sum(1 for bucket in candidate_buckets if bucket.reason == "numbered_sequence"),
        channel_set_groups=sum(1 for bucket in candidate_buckets if bucket.reason == "channel_set"),
        mixed_format_groups=mixed_format_groups,
    )

    return RelatedGroupsReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=str(root),
        db_path=str(db_path),
        min_files=min_files,
        limit=limit,
        summary=summary,
        groups=groups,
    )


def write_related_groups_report(report: RelatedGroupsReport, output_path: Path, quiet: bool = False) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.model_dump(), indent=2), encoding="utf-8")
    if not quiet:
        console.print(f"Related groups report written to [cyan]{output_path}[/cyan]")


def show_related_groups_report(report: RelatedGroupsReport) -> None:
    summary = report.summary
    console.print(
        f"Found [yellow]{summary.candidate_groups:,}[/yellow] related group candidate(s) "
        f"covering [yellow]{summary.grouped_files:,}[/yellow] file(s)."
    )
    if not report.groups:
        return

    table = Table(title="Related sound groups", show_lines=False)
    table.add_column("Group", justify="right")
    table.add_column("Files", justify="right")
    table.add_column("Reason")
    table.add_column("Stem")
    table.add_column("Folder")
    for group in report.groups[:20]:
        table.add_row(
            str(group.group_id),
            str(group.file_count),
            group.reason,
            group.inferred_stem,
            group.parent_path,
        )
    console.print(table)
