"""Reviewed dry-run plans for future embedded metadata writes."""

import hashlib
import json
import shutil
import struct
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from sfxworkbench import __version__
from sfxworkbench import audio as audio_mod
from sfxworkbench.apply_logs import (
    default_apply_log_path_for_plan,
    mark_entries_reviewed,
    write_apply_log,
)
from sfxworkbench.db import DEFAULT_DB_PATH, get_connection, is_scoped_path, resolve_scope_root
from sfxworkbench.metadata_backends import build_metadata_backends_report
from sfxworkbench.metadata_fields import replace_metadata_fields
from sfxworkbench.models import (
    MetadataWriteApplyResult,
    MetadataWriteBackend,
    MetadataWriteCommand,
    MetadataWriteFixtureBundle,
    MetadataWriteFixtureFile,
    MetadataWritePlan,
    MetadataWritePlanEntry,
    MetadataWritePlanSummary,
    MetadataWritePreviewResult,
    MetadataWriteReadbackFile,
    MetadataWriteReadbackReport,
    MetadataWriteReadbackSummary,
    MetadataWriteReviewResult,
    MetadataWriteUndoResult,
)
from sfxworkbench.preservation import build_preservation_rules, move_protected_by
from sfxworkbench.ucs import looks_ucs
from sfxworkbench.utils import atomic_write_json

console = Console()

PLAN_SCHEMA_VERSION = 1
_VALID_REVIEW_STATES = {"approved", "rejected", "pending"}
_PROGRESS_MAX_INTERVAL = 100


def _metadata_plan_progress_message(
    *,
    processed: int,
    total: int,
    supported: int,
    unsupported: int,
    current: str | None = None,
) -> str:
    message = f"Processed {processed:,}/{total:,}; supported {supported:,}, unsupported {unsupported:,}"
    if current:
        return f"{message}; current {Path(current).name}"
    return message


def _metadata_apply_progress_message(
    *,
    processed: int,
    total: int,
    applied: int,
    files_written: int,
    files_backed_up: int,
    files_verified: int,
    skipped: int,
    errors: int,
    current: str | None = None,
) -> str:
    message = (
        f"Processed {processed:,}/{total:,}; applied {applied:,} field(s), "
        f"wrote {files_written:,} file(s), backed up {files_backed_up:,}, "
        f"verified {files_verified:,}, skipped {skipped:,}, errors {errors:,}"
    )
    if current:
        return f"{message}; current {Path(current).name}"
    return message


# Conservative first-pass mapping. These are the only accepted tag fields this
# slice is willing to route toward BWF MetaEdit. Everything else remains visible
# in the plan as unsupported rather than disappearing.
BWF_METAEDIT_FIELD_MAP = {
    "description": ("bext", "Description"),
    "originator": ("bext", "Originator"),
    "originator_reference": ("bext", "OriginatorReference"),
    "keyword": ("riff_info", "IKEY"),
    "keywords": ("riff_info", "IKEY"),
}
BWF_METAEDIT_COMMAND_FIELDS = {
    "Description": "Description",
    "Originator": "Originator",
    "OriginatorReference": "OriginatorReference",
    "IKEY": "IKEY",
}
BWF_METAEDIT_FIELD_LIMITS = {
    "Description": 256,
    "Originator": 32,
    "OriginatorReference": 32,
}
BWF_METAEDIT_MULTIVALUE_KEYS = {"IKEY"}
BWF_METAEDIT_LIST_SEPARATORS = {
    "IKEY": "; ",
}
MUTAGEN_FIELD_MAP = {
    "description": ("tag", "description"),
    "originator": ("tag", "organization"),
    "originator_reference": ("tag", "encodedby"),
    "category": ("tag", "genre"),
    "subcategory": ("tag", "ww:subcategory"),
    "ucs_category": ("tag", "ww:ucs_category"),
    "ucs_subcategory": ("tag", "ww:ucs_subcategory"),
    "take_number": ("tag", "ww:take_number"),
    "channel_position": ("tag", "ww:channel_position"),
    "keyword": ("tag", "keywords"),
    "keywords": ("tag", "keywords"),
}
MUTAGEN_FIELD_MAP_BY_EXTENSION = {
    ".flac": MUTAGEN_FIELD_MAP,
    ".ogg": MUTAGEN_FIELD_MAP,
    ".opus": MUTAGEN_FIELD_MAP,
    ".mp3": {
        "originator": ("tag", "organization"),
        "originator_reference": ("tag", "encodedby"),
        "category": ("tag", "genre"),
    },
    ".m4a": {
        "description": ("tag", "description"),
        "category": ("tag", "genre"),
    },
    ".aif": {},
    ".aiff": {},
}
MUTAGEN_MULTIVALUE_KEYS = {"keywords"}
MULTIVALUE_TARGET_KEYS = BWF_METAEDIT_MULTIVALUE_KEYS | MUTAGEN_MULTIVALUE_KEYS
BWF_METAEDIT_EXTENSIONS = {".wav", ".rf64"}
MUTAGEN_EXTENSIONS = {".aif", ".aiff", ".mp3", ".flac", ".ogg", ".opus", ".m4a"}
ALL_EMBEDDED_WRITE_EXTENSIONS = BWF_METAEDIT_EXTENSIONS | MUTAGEN_EXTENSIONS
FIXTURE_MANIFEST_NAME = "metadata_write_fixture_manifest.json"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _default_plan_path() -> Path:
    return Path(f"metadata_write_plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _default_apply_log_path(plan_path: Path) -> Path:
    return default_apply_log_path_for_plan(plan_path, "metadata_write_apply_log")


def _default_backup_dir(plan_path: Path) -> Path:
    return plan_path.parent / f"sfxworkbench_metadata_write_backups_{_now_stamp()}"


def _decode_evidence(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return [raw]
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _md5(path: Path, block: int = 65536) -> str | None:
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(block):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _backup_target(path: Path, backup_dir: Path) -> Path:
    target = backup_dir.joinpath(*path.resolve().parts[1:])
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    parent = target.parent
    for i in range(1, 1000):
        candidate = parent / f"{stem}__{i}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not find non-conflicting backup target for {path}")


def _refresh_indexed_audio_row(conn, path: Path, *, file_id: int | None = None) -> None:
    stat = path.stat()
    audio_info = audio_mod.read_audio_info(path)
    stem = path.stem
    metadata_sources = json.dumps(audio_info.metadata_sources if audio_info else [])
    params = (
        path.name,
        stem,
        path.suffix.lower(),
        stat.st_size,
        stat.st_mtime,
        _md5(path),
        audio_info.sample_rate if audio_info else None,
        audio_info.bit_depth if audio_info else None,
        audio_info.channels if audio_info else None,
        audio_info.duration_s if audio_info else None,
        audio_info.subtype if audio_info else None,
        int(audio_info.has_bext) if audio_info else 0,
        int(audio_info.has_ixml) if audio_info else 0,
        int(audio_info.has_riff_info) if audio_info else 0,
        int(audio_info.has_adm) if audio_info else 0,
        int(audio_info.has_cue_markers) if audio_info else 0,
        int(audio_info.has_sampler) if audio_info else 0,
        metadata_sources,
        int(looks_ucs(stem)),
        audio_info.error if audio_info else None,
        _now_iso(),
        file_id if file_id is not None else str(path),
    )
    where = "id = ?" if file_id is not None else "path = ?"
    conn.execute(
        f"""
        UPDATE files
        SET filename = ?,
            stem = ?,
            extension = ?,
            size_bytes = ?,
            mtime = ?,
            md5 = ?,
            sample_rate = ?,
            bit_depth = ?,
            channels = ?,
            duration_s = ?,
            subtype = ?,
            has_bext = ?,
            has_ixml = ?,
            has_riff_info = ?,
            has_adm = ?,
            has_cue_markers = ?,
            has_sampler = ?,
            metadata_sources = ?,
            is_ucs = ?,
            scan_error = ?,
            scanned_at = ?
        WHERE {where}
        """,
        params,
    )
    row = conn.execute("SELECT id FROM files WHERE id = ? OR path = ?", (file_id, str(path))).fetchone()
    if row is not None:
        replace_metadata_fields(conn, file_id=row["id"], path=path, audio_info=audio_info, updated_at=params[-2])


def _summarize_plan(plan: MetadataWritePlan) -> MetadataWritePlanSummary:
    file_ids = {entry.file_id for entry in plan.entries}
    return MetadataWritePlanSummary(
        files_considered=len(file_ids),
        accepted_tags_considered=len(plan.entries),
        candidate_entries=len(plan.entries),
        supported_entries=sum(1 for entry in plan.entries if entry.supported),
        conflict_entries=sum(1 for entry in plan.entries if entry.action == "conflict"),
        skip_existing_entries=sum(1 for entry in plan.entries if entry.action == "skip_existing"),
        replace_entries=sum(
            1 for entry in plan.entries if entry.action in {"replace_bext", "replace_riff_info", "replace_tag"}
        ),
        unsupported_entries=sum(1 for entry in plan.entries if not entry.supported),
        approved_entries=sum(1 for entry in plan.entries if entry.review_status == "approved"),
        rejected_entries=sum(1 for entry in plan.entries if entry.review_status == "rejected"),
        backend_available=plan.backend.available,
    )


def _auto_backend_for_extension(extension: str) -> str | None:
    ext = extension.lower()
    if ext in BWF_METAEDIT_EXTENSIONS:
        return "bwfmetaedit"
    if ext in MUTAGEN_EXTENSIONS:
        return "mutagen"
    return None


def _selected_backend_for_extension(extension: str, backend: str) -> str | None:
    if backend == "auto":
        return _auto_backend_for_extension(extension)
    if backend == "bwfmetaedit" and extension.lower() in BWF_METAEDIT_EXTENSIONS:
        return "bwfmetaedit"
    if backend == "mutagen" and extension.lower() in MUTAGEN_EXTENSIONS:
        return "mutagen"
    return None


def _target_for_field(
    field: str, backend: str, *, extension: str | None = None
) -> tuple[str | None, str | None, str, bool]:
    if backend == "bwfmetaedit":
        target = BWF_METAEDIT_FIELD_MAP.get(field)
        if target is None:
            return None, None, "unsupported_field", False
        action = "write_bext" if target[0] == "bext" else "write_riff_info"
        return target[0], target[1], action, True
    if backend == "mutagen":
        field_map = MUTAGEN_FIELD_MAP_BY_EXTENSION.get((extension or "").lower(), MUTAGEN_FIELD_MAP)
        target = field_map.get(field)
        if target is None:
            return None, None, "unsupported_field", False
        return target[0], target[1], "write_tag", True
    return None, None, "unsupported_backend", False


def _backend_by_name(backends: list[MetadataWriteBackend]) -> dict[str, MetadataWriteBackend]:
    return {backend.name: backend for backend in backends}


def _auto_backend(backends: list[MetadataWriteBackend]) -> MetadataWriteBackend:
    available_backends = [backend for backend in backends if backend.available]
    return MetadataWriteBackend(
        name="auto",
        display_name="Auto",
        available=bool(available_backends),
        supported_extensions=sorted(ALL_EMBEDDED_WRITE_EXTENSIONS),
        notes=[
            "Routes WAV/RF64 to BWF MetaEdit and standard tagged formats to Mutagen.",
            "Backend availability is still validated per entry during preview.",
        ],
    )


def _entry_backend(plan: MetadataWritePlan, entry: MetadataWritePlanEntry) -> MetadataWriteBackend | None:
    backends = _backend_by_name(plan.backends or [plan.backend])
    return backends.get(entry.backend)


def _entry_backend_error(plan: MetadataWritePlan, entry: MetadataWritePlanEntry) -> str | None:
    backend = _entry_backend(plan, entry)
    if backend is None:
        return f"backend not present in plan: {entry.backend}"
    if not backend.available:
        return f"backend unavailable: {backend.name}"
    return None


def _target_for_row(field: str, extension: str, backend: str) -> tuple[str, str | None, str | None, str, bool]:
    selected_backend = _selected_backend_for_extension(extension, backend)
    if selected_backend is None:
        return backend, None, None, "unsupported_extension", False
    target_namespace, target_key, action, supported = _target_for_field(field, selected_backend, extension=extension)
    return selected_backend, target_namespace, target_key, action, supported


def _existing_embedded_value(
    path: Path, backend: str, target_namespace: str | None, target_key: str | None
) -> str | None:
    if target_key is None:
        return None
    if backend == "mutagen" and target_namespace == "tag":
        try:
            existing_fields = read_mutagen_fields(path, [target_key])
        except Exception:
            return None
        existing = existing_fields.get(target_key)
        if isinstance(existing, list):
            values = [str(value).strip() for value in existing if str(value).strip()]
            return "; ".join(values) if values else None
        if existing is None or not str(existing).strip():
            return None
        return str(existing)
    if backend != "bwfmetaedit":
        return None
    try:
        if target_namespace == "bext":
            existing_fields = read_bext_core_fields(path)
        elif target_namespace == "riff_info":
            existing_fields = read_riff_info_fields(path)
        else:
            return None
    except Exception:
        return None
    existing = existing_fields.get(target_key)
    if existing is None or not existing.strip():
        return None
    return existing


def _mark_single_value_conflicts(entries: list[MetadataWritePlanEntry]) -> list[dict]:
    grouped: dict[tuple[int, str, str | None, str | None], list[MetadataWritePlanEntry]] = {}
    for entry in entries:
        if not entry.supported or entry.target_key is None or entry.target_key in MULTIVALUE_TARGET_KEYS:
            continue
        key = (entry.file_id, entry.backend, entry.target_namespace, entry.target_key)
        grouped.setdefault(key, []).append(entry)

    errors: list[dict] = []
    for (_file_id, backend, target_namespace, target_key), group in sorted(grouped.items()):
        values = {entry.value for entry in group}
        if len(values) <= 1:
            continue
        for entry in group:
            entry.action = "conflict"
            entry.supported = False
        first = group[0]
        errors.append(
            {
                "path": first.path,
                "backend": backend,
                "target_namespace": target_namespace,
                "target_key": target_key,
                "entry_ids": [entry.entry_id for entry in group],
                "values": sorted(values),
                "error": "conflicting accepted tags for single-value metadata target",
            }
        )
    return errors


def _validate_mutagen_value(entry: MetadataWritePlanEntry) -> str | None:
    if entry.target_namespace != "tag" or entry.target_key is None:
        return None
    if not entry.value.strip():
        return f"{entry.target_key} cannot be blank"
    return None


def _validate_entry_value(entry: MetadataWritePlanEntry) -> str | None:
    if entry.backend == "bwfmetaedit":
        return _validate_bwf_value(entry)
    if entry.backend == "mutagen":
        return _validate_mutagen_value(entry)
    return None


def _base_mutagen_command() -> list[str]:
    return ["internal:mutagen", "--simulate"]


def render_mutagen_commands(
    entries: list[MetadataWritePlanEntry], plan: MetadataWritePlan
) -> list[MetadataWriteCommand]:
    """Render planned Mutagen writes grouped per target file."""
    grouped: dict[int, list[MetadataWritePlanEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.file_id, []).append(entry)

    commands: list[MetadataWriteCommand] = []
    for file_id in sorted(grouped):
        file_entries = grouped[file_id]
        fields: dict[str, str | list[str]] = {}
        entry_count = 0
        allow_overwrite = any(entry.action == "replace_tag" for entry in file_entries)
        command = _base_mutagen_command()
        for entry in sorted(file_entries, key=lambda item: (item.target_key or "", item.entry_id)):
            if entry.target_key is None:
                continue
            entry_count += 1
            if entry.target_key in MUTAGEN_MULTIVALUE_KEYS:
                existing = fields.setdefault(entry.target_key, [])
                if isinstance(existing, list):
                    existing.append(entry.value)
                else:
                    fields[entry.target_key] = [existing, entry.value]
            else:
                fields[entry.target_key] = entry.value
            command.append(f"--set={entry.target_key}={entry.value}")
        command.append(file_entries[0].path)
        commands.append(
            MetadataWriteCommand(
                file_id=file_id,
                path=file_entries[0].path,
                command=command,
                fields=fields,
                entry_count=entry_count,
                allow_overwrite=allow_overwrite,
            )
        )
    return commands


def render_metadata_write_commands(
    entries: list[MetadataWritePlanEntry], plan: MetadataWritePlan
) -> list[MetadataWriteCommand]:
    bwf_entries = [entry for entry in entries if entry.backend == "bwfmetaedit"]
    mutagen_entries = [entry for entry in entries if entry.backend == "mutagen"]
    return render_bwfmetaedit_commands(bwf_entries, plan) + render_mutagen_commands(mutagen_entries, plan)


def _command_backend(command: MetadataWriteCommand) -> str:
    if command.command and command.command[0] == "internal:mutagen":
        return "mutagen"
    return "bwfmetaedit"


def _bwfmetaedit_write_command(command: list[str], target_path: Path) -> list[str]:
    if not command:
        raise RuntimeError("empty BWF MetaEdit command")
    if command[0] == "internal:mutagen":
        raise RuntimeError("internal Mutagen command cannot be executed as BWF MetaEdit")
    if Path(command[-1]) != target_path:
        raise RuntimeError("BWF MetaEdit command does not target the expected audio path")
    executable_command = [part for part in command if part != "--simulate"]
    if executable_command == command:
        raise RuntimeError("BWF MetaEdit fixture command is missing --simulate guard")
    return executable_command


def run_bwfmetaedit_command(command: list[str], target_path: Path, timeout: int = 30) -> dict:
    """Execute a BWF MetaEdit command after validating its target path."""
    executable_command = _bwfmetaedit_write_command(command, target_path)
    result = subprocess.run(executable_command, capture_output=True, text=True, timeout=timeout, check=False)
    report = {
        "command": executable_command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or f"exit {result.returncode}").strip()
        raise RuntimeError(f"BWF MetaEdit write failed: {detail}")
    return report


def _validate_bwf_value(entry: MetadataWritePlanEntry) -> str | None:
    if entry.backend != "bwfmetaedit" or entry.target_key is None:
        return None
    if entry.target_namespace == "riff_info":
        if not entry.value.strip():
            return f"{entry.target_key} cannot be blank"
        return None
    if entry.target_namespace != "bext":
        return None
    encoded = entry.value.encode("ascii", errors="ignore")
    if encoded.decode("ascii") != entry.value:
        return f"{entry.target_key} must be ASCII for BWF MetaEdit/BEXT"
    max_bytes = BWF_METAEDIT_FIELD_LIMITS.get(entry.target_key)
    if max_bytes is not None and len(encoded) > max_bytes:
        return f"{entry.target_key} exceeds {max_bytes} ASCII bytes"
    return None


def _base_bwfmetaedit_command(plan: MetadataWritePlan, *, allow_overwrite: bool = False) -> list[str]:
    backend = _backend_by_name(plan.backends or [plan.backend]).get("bwfmetaedit", plan.backend)
    executable = backend.executable or backend.name
    command = [executable, "--simulate"]
    if not allow_overwrite:
        command.append("--reject-overwrite")
    command.append("--specialchars")
    return command


def _render_bwfmetaedit_field_value(key: str, value: str | list[str]) -> str:
    if isinstance(value, list):
        separator = BWF_METAEDIT_LIST_SEPARATORS.get(key, "; ")
        return separator.join(str(item) for item in value)
    return value


def render_bwfmetaedit_commands(
    entries: list[MetadataWritePlanEntry], plan: MetadataWritePlan
) -> list[MetadataWriteCommand]:
    """Render simulated BWF MetaEdit commands grouped per target file."""
    grouped: dict[int, list[MetadataWritePlanEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.file_id, []).append(entry)

    commands: list[MetadataWriteCommand] = []
    for file_id in sorted(grouped):
        file_entries = grouped[file_id]
        fields: dict[str, str | list[str]] = {}
        entry_count = 0
        allow_overwrite = any(entry.action in {"replace_bext", "replace_riff_info"} for entry in file_entries)
        command = _base_bwfmetaedit_command(plan, allow_overwrite=allow_overwrite)
        for entry in sorted(file_entries, key=lambda item: (item.target_key or "", item.entry_id)):
            if entry.target_key is None:
                continue
            command_field = BWF_METAEDIT_COMMAND_FIELDS.get(entry.target_key)
            if command_field is None:
                continue
            entry_count += 1
            if entry.target_key in BWF_METAEDIT_MULTIVALUE_KEYS:
                existing = fields.setdefault(entry.target_key, [])
                if isinstance(existing, list):
                    existing.append(entry.value)
                else:
                    fields[entry.target_key] = [existing, entry.value]
            else:
                fields[entry.target_key] = entry.value
        for key, value in fields.items():
            command_field = BWF_METAEDIT_COMMAND_FIELDS.get(key)
            if command_field is None:
                continue
            rendered_value = _render_bwfmetaedit_field_value(key, value)
            command.append(f"--{command_field}={rendered_value}")
        command.append(file_entries[0].path)
        commands.append(
            MetadataWriteCommand(
                file_id=file_id,
                path=file_entries[0].path,
                command=command,
                fields=fields,
                entry_count=entry_count,
                allow_overwrite=allow_overwrite,
            )
        )
    return commands


def _load_mutagen_file(path: Path):
    try:
        from mutagen import File as MutagenFile
    except ImportError as e:
        raise RuntimeError("mutagen is not installed; install sfxworkbench[metadata]") from e
    tagged = MutagenFile(str(path), easy=True)
    if tagged is None:
        raise RuntimeError("mutagen could not identify file")
    return tagged


def write_mutagen_fields(path: Path, fields: dict[str, str | list[str]]) -> None:
    """Write simple text metadata fields with Mutagen."""
    tagged = _load_mutagen_file(path)
    for key, value in fields.items():
        tagged[key] = [str(item) for item in value] if isinstance(value, list) else [value]
    tagged.save()


def read_mutagen_fields(path: Path, fields: list[str]) -> dict[str, str | list[str]]:
    """Read simple text metadata fields with Mutagen."""
    tagged = _load_mutagen_file(path)
    result: dict[str, str | list[str]] = {}
    for field in fields:
        values = tagged.get(field)
        if values is None:
            continue
        if isinstance(values, list):
            result[field] = [str(value) for value in values] if field in MUTAGEN_MULTIVALUE_KEYS else str(values[0])
        else:
            result[field] = str(values)
    return result


def _compare_expected_fields(
    expected_fields: dict[str, str | list[str]], actual_fields: dict[str, str | list[str]]
) -> tuple[list[str], dict]:
    matched_fields: list[str] = []
    mismatched_fields: dict[str, dict[str, str | list[str] | None]] = {}
    for field, expected in expected_fields.items():
        actual = actual_fields.get(field)
        if actual == expected:
            matched_fields.append(field)
        else:
            mismatched_fields[field] = {"expected": expected, "actual": actual}
    return sorted(matched_fields), mismatched_fields


def _split_multivalue_field(key: str, value: str) -> list[str]:
    separator = BWF_METAEDIT_LIST_SEPARATORS.get(key, "; ")
    return [item.strip() for item in value.split(separator.strip()) if item.strip()]


def build_metadata_write_plan(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    root: Path | None = None,
    backend: str = "auto",
    bwfmetaedit: str | Path | None = None,
    limit: int = 0,
    replace_existing: bool = False,
    progress_callback: Callable[[str, int, int | None, str], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> MetadataWritePlan:
    """Build a reviewed dry-run embedded metadata write plan from accepted tags.

    Plan construction probes every accepted-tag row against the actual audio
    file via Mutagen / bwfmetaedit to detect existing values. On a library
    with 100k accepted tags this is 100k file opens — wire
    ``progress_callback`` to keep the TUI animated and ``cancel_requested``
    to let the user back out of a misclick.
    """
    if limit < 0:
        raise ValueError("--limit must be 0 or greater")
    if backend not in {"auto", "bwfmetaedit", "mutagen"}:
        raise ValueError("Supported metadata write backends are: auto, bwfmetaedit, mutagen")
    resolved_root = resolve_scope_root(root) if root is not None else None
    if resolved_root is not None and not resolved_root.exists():
        raise ValueError(f"path not found: {resolved_root}")

    from sfxworkbench.scan import ensure_metadata_info

    ensure_metadata_info(db_path, resolved_root, progress_callback=progress_callback, cancel_requested=cancel_requested)
    backend_report = build_metadata_backends_report(bwfmetaedit=bwfmetaedit)
    backend_info = (
        _auto_backend(backend_report.backends)
        if backend == "auto"
        else _backend_by_name(backend_report.backends)[backend]
    )
    conn = get_connection(db_path)
    rows = conn.execute(
        """
        SELECT f.id AS file_id, f.path, f.filename, f.extension, f.size_bytes, f.mtime, f.md5,
               t.field, t.value, t.source, t.method, t.confidence, t.evidence
        FROM accepted_tags t
        JOIN files f ON f.id = t.file_id
        ORDER BY f.path, t.field, t.value, t.source
        """
    ).fetchall()
    conn.close()

    if resolved_root is not None:
        rows = [row for row in rows if is_scoped_path(row["path"], resolved_root)]
    if limit:
        rows = rows[:limit]

    from sfxworkbench.utils import progress_interval

    entries: list[MetadataWritePlanEntry] = []
    total_rows = len(rows)
    plan_report_every = min(progress_interval(total_rows), _PROGRESS_MAX_INTERVAL)
    supported_count = 0
    unsupported_count = 0
    if progress_callback is not None:
        progress_callback(
            "probing",
            0,
            total_rows,
            _metadata_plan_progress_message(
                processed=0,
                total=total_rows,
                supported=0,
                unsupported=0,
            ),
        )
    for entry_id, row in enumerate(rows, start=1):
        # Per-row work: a Mutagen open + namespace lookup. Cheap-but-not-free.
        # Cancel polled every 50 for sub-second response; progress reported
        # at the log-scaled interval.
        if entry_id > 1 and entry_id % 50 == 0:
            if cancel_requested is not None and cancel_requested():
                break
        entry_backend, target_namespace, target_key, action, supported = _target_for_row(
            row["field"], row["extension"] or "", backend
        )
        existing_value = _existing_embedded_value(Path(row["path"]), entry_backend, target_namespace, target_key)
        if existing_value is not None:
            if replace_existing and entry_backend == "bwfmetaedit":
                action = "replace_bext" if target_namespace == "bext" else "replace_riff_info"
                supported = True
            elif replace_existing and entry_backend == "mutagen":
                action = "replace_tag"
                supported = True
            else:
                action = "skip_existing"
                supported = False
        entries.append(
            MetadataWritePlanEntry(
                entry_id=entry_id,
                file_id=row["file_id"],
                path=row["path"],
                filename=row["filename"],
                size_bytes=row["size_bytes"],
                mtime=row["mtime"],
                md5=row["md5"],
                field=row["field"],
                value=row["value"],
                source=row["source"],
                method=row["method"],
                confidence=row["confidence"],
                evidence=_decode_evidence(row["evidence"]),
                backend=entry_backend,
                target_namespace=target_namespace,
                target_key=target_key,
                action=action,
                existing_value=existing_value,
                supported=supported,
            )
        )
        if supported:
            supported_count += 1
        else:
            unsupported_count += 1
        if progress_callback is not None and (entry_id % plan_report_every == 0 or entry_id == total_rows):
            progress_callback(
                "probing",
                entry_id,
                total_rows,
                _metadata_plan_progress_message(
                    processed=entry_id,
                    total=total_rows,
                    supported=supported_count,
                    unsupported=unsupported_count,
                    current=row["path"],
                ),
            )

    errors = _mark_single_value_conflicts(entries)
    if progress_callback is not None and errors:
        progress_callback(
            "probing",
            total_rows,
            total_rows,
            (
                _metadata_plan_progress_message(
                    processed=total_rows,
                    total=total_rows,
                    supported=supported_count,
                    unsupported=unsupported_count,
                )
                + f"; conflicts {len(errors):,}"
            ),
        )

    plan = MetadataWritePlan(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=str(resolved_root) if resolved_root is not None else None,
        db_path=str(db_path),
        replace_existing=replace_existing,
        backend=backend_info,
        backends=backend_report.backends,
        summary=MetadataWritePlanSummary(),
        entries=entries,
        errors=errors,
    )
    plan.summary = _summarize_plan(plan)
    if progress_callback is not None:
        progress_callback(
            "complete",
            total_rows,
            total_rows,
            (
                _metadata_plan_progress_message(
                    processed=total_rows,
                    total=total_rows,
                    supported=plan.summary.supported_entries,
                    unsupported=plan.summary.unsupported_entries,
                )
                + f"; conflicts {len(errors):,}"
            ),
        )
    return plan


def write_metadata_write_plan(
    plan: MetadataWritePlan,
    output_path: Path | None = None,
    quiet: bool = False,
) -> Path:
    output = output_path or _default_plan_path()
    atomic_write_json(output, plan)
    if not quiet:
        console.print(f"Metadata write plan written to [cyan]{output}[/cyan]")
    return output


def load_metadata_write_plan(plan_path: Path) -> MetadataWritePlan:
    return MetadataWritePlan.model_validate(json.loads(plan_path.read_text()))


def review_metadata_write_plan(
    plan_path: Path,
    output_path: Path | None = None,
    approve_all: bool = False,
    entries: list[int] | None = None,
    reject_entries: list[int] | None = None,
    quiet: bool = False,
) -> MetadataWriteReviewResult:
    """Mark selected embedded-write plan entries as approved or rejected."""
    plan = load_metadata_write_plan(plan_path)
    by_id = {entry.entry_id: entry for entry in plan.entries}
    invalid = mark_entries_reviewed(by_id, approve=entries, reject=reject_entries, approve_all=approve_all)
    plan.summary = _summarize_plan(plan)

    output = output_path or plan_path
    atomic_write_json(output, plan)
    result = MetadataWriteReviewResult(
        plan_path=str(plan_path),
        output_path=str(output),
        total_entries=len(plan.entries),
        approved_entries=plan.summary.approved_entries,
        rejected_entries=plan.summary.rejected_entries,
        invalid_entries=invalid,
    )
    if not quiet:
        console.print(
            f"Approved [yellow]{result.approved_entries:,}[/yellow] and rejected "
            f"[yellow]{result.rejected_entries:,}[/yellow] of "
            f"[yellow]{result.total_entries:,}[/yellow] embedded metadata write entrie(s)."
        )
        if invalid:
            console.print(f"[red]Ignored invalid entry number(s): {', '.join(str(i) for i in invalid)}[/red]")
    return result


def _validate_plan_entry(conn, entry: MetadataWritePlanEntry) -> str | None:
    path = Path(entry.path)
    row = conn.execute(
        "SELECT path, size_bytes, mtime, md5 FROM files WHERE id = ?",
        (entry.file_id,),
    ).fetchone()
    if row is None:
        return "indexed file row is missing"
    if row["path"] != entry.path:
        return f"path changed: expected {entry.path}, got {row['path']}"
    if entry.size_bytes is not None and row["size_bytes"] != entry.size_bytes:
        return f"size changed: expected {entry.size_bytes}, got {row['size_bytes']}"
    if entry.mtime is not None and row["mtime"] != entry.mtime:
        return "mtime changed"
    if entry.md5 is not None and row["md5"] != entry.md5:
        return "md5 changed"
    if not path.exists():
        return "file does not exist"
    stat = path.stat()
    if entry.size_bytes is not None and stat.st_size != entry.size_bytes:
        return f"file size changed: expected {entry.size_bytes}, got {stat.st_size}"
    if entry.mtime is not None and stat.st_mtime != entry.mtime:
        return "file mtime changed"
    if entry.md5 is not None:
        current_md5 = _md5(path)
        if current_md5 != entry.md5:
            return "file md5 changed"
    return None


def preview_metadata_write_plan(
    plan_path: Path,
    db_path: Path | None = None,
    require_reviewed: bool = False,
    quiet: bool = False,
) -> MetadataWritePreviewResult:
    """Validate a reviewed embedded metadata write plan without mutating audio."""
    plan = load_metadata_write_plan(plan_path)
    effective_db = db_path or Path(plan.db_path)
    result = MetadataWritePreviewResult(planned=len(plan.entries), target=plan.target)
    result.errors.extend(plan.errors)
    if plan.target != "embedded_metadata":
        result.errors.append({"path": str(plan_path), "error": f"unsupported metadata target: {plan.target}"})
        return result
    if plan.backend.name != "auto" and not plan.backend.available:
        result.errors.append({"path": str(plan_path), "error": f"backend unavailable: {plan.backend.name}"})
        return result
    approved_entries = [entry for entry in plan.entries if entry.review_status == "approved"]
    if require_reviewed and not approved_entries:
        result.errors.append({"path": str(plan_path), "error": "plan has no approved entries"})
        return result

    conn = get_connection(effective_db)
    renderable_entries: list[MetadataWritePlanEntry] = []
    for entry in plan.entries:
        if require_reviewed and entry.review_status != "approved":
            result.skipped += 1
            continue
        if entry.review_status == "rejected":
            result.skipped += 1
            continue
        if entry.review_status not in _VALID_REVIEW_STATES:
            result.errors.append({"entry_id": entry.entry_id, "path": entry.path, "error": "invalid review status"})
            continue
        if not entry.supported:
            result.skipped += 1
            continue
        backend_error = _entry_backend_error(plan, entry)
        if backend_error is not None:
            result.errors.append({"entry_id": entry.entry_id, "path": entry.path, "error": backend_error})
            continue
        value_error = _validate_entry_value(entry)
        if value_error is not None:
            result.errors.append({"entry_id": entry.entry_id, "path": entry.path, "error": value_error})
            continue
        validation_error = _validate_plan_entry(conn, entry)
        if validation_error is not None:
            result.errors.append({"entry_id": entry.entry_id, "path": entry.path, "error": validation_error})
            continue
        result.would_write += 1
        renderable_entries.append(entry)
    result.commands = render_metadata_write_commands(renderable_entries, plan)
    conn.close()
    if not quiet:
        show_metadata_write_preview_result(result)
    return result


def _fixture_filename(command: MetadataWriteCommand) -> str:
    source = Path(command.path)
    return f"{command.file_id:06d}_{source.name}"


def build_metadata_write_fixture_bundle(
    plan_path: Path,
    output_dir: Path,
    db_path: Path | None = None,
    require_reviewed: bool = True,
    write_fixture_metadata: bool = False,
    quiet: bool = False,
) -> MetadataWriteFixtureBundle:
    """Copy target files to a fixture bundle and render commands against the copies."""
    preview = preview_metadata_write_plan(plan_path, db_path=db_path, require_reviewed=require_reviewed, quiet=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = output_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    bundle = MetadataWriteFixtureBundle(
        generated_at=_now_iso(),
        tool_version=__version__,
        plan_path=str(plan_path),
        output_dir=str(output_dir),
        errors=list(preview.errors),
    )

    for command in preview.commands:
        source = Path(command.path)
        fixture_path = audio_dir / _fixture_filename(command)
        copied_command = list(command.command)
        if copied_command:
            copied_command[-1] = str(fixture_path)
        if not source.exists():
            bundle.errors.append({"path": str(source), "error": "source file missing during fixture copy"})
            continue
        shutil.copy2(source, fixture_path)
        backend = _command_backend(command)
        fixture = MetadataWriteFixtureFile(
            file_id=command.file_id,
            source_path=str(source),
            fixture_path=str(fixture_path),
            backend=backend,
            command=copied_command,
            expected_fields=command.fields,
        )
        if write_fixture_metadata and backend == "mutagen":
            try:
                write_mutagen_fields(fixture_path, command.fields)
                fixture.metadata_written = True
            except RuntimeError as e:
                fixture.errors.append(str(e))
                bundle.errors.append({"path": str(fixture_path), "error": str(e)})
            except Exception as e:
                fixture.errors.append(f"mutagen write failed: {e}")
                bundle.errors.append({"path": str(fixture_path), "error": f"mutagen write failed: {e}"})
        elif write_fixture_metadata and backend == "bwfmetaedit":
            try:
                fixture.write_result = run_bwfmetaedit_command(copied_command, fixture_path)
                fixture.metadata_written = True
            except RuntimeError as e:
                fixture.errors.append(str(e))
                bundle.errors.append({"path": str(fixture_path), "error": str(e)})
            except Exception as e:
                fixture.errors.append(f"BWF MetaEdit write failed: {e}")
                bundle.errors.append({"path": str(fixture_path), "error": f"BWF MetaEdit write failed: {e}"})
        bundle.files.append(fixture)

    manifest_path = output_dir / FIXTURE_MANIFEST_NAME
    atomic_write_json(manifest_path, bundle)
    if not quiet:
        console.print(f"Metadata write fixture bundle written to [cyan]{manifest_path}[/cyan]")
    return bundle


def _resolve_fixture_manifest(path: Path) -> Path:
    if path.is_dir():
        return path / FIXTURE_MANIFEST_NAME
    return path


def load_metadata_write_fixture_bundle(path: Path) -> MetadataWriteFixtureBundle:
    manifest_path = _resolve_fixture_manifest(path)
    return MetadataWriteFixtureBundle.model_validate(json.loads(manifest_path.read_text()))


def _decode_bext_text(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("ascii", errors="ignore").rstrip()


def _decode_riff_info_text(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("utf-8", errors="ignore").rstrip()


def read_bext_core_fields(path: Path) -> dict[str, str]:
    """Read the small BEXT core field subset used by metadata write previews."""
    fields: dict[str, str] = {}
    with open(path, "rb") as f:
        header = f.read(12)
        if len(header) < 12:
            raise ValueError("file is too small to be RIFF/WAVE")
        riff_id, _, wave_id = struct.unpack_from("<4sI4s", header)
        if riff_id not in (b"RIFF", b"RF64") or wave_id != b"WAVE":
            raise ValueError("file is not RIFF/RF64 WAVE")
        while True:
            chunk_header = f.read(8)
            if len(chunk_header) < 8:
                break
            chunk_id, chunk_size = struct.unpack_from("<4sI", chunk_header)
            chunk_data = f.read(chunk_size)
            if chunk_size % 2:
                f.seek(1, 1)
            if chunk_id != b"bext":
                continue
            if len(chunk_data) < 320:
                raise ValueError("bext chunk is too small for core fields")
            fields["Description"] = _decode_bext_text(chunk_data[0:256])
            fields["Originator"] = _decode_bext_text(chunk_data[256:288])
            fields["OriginatorReference"] = _decode_bext_text(chunk_data[288:320])
            return fields
    return fields


def read_riff_info_fields(path: Path) -> dict[str, str]:
    """Read RIFF INFO text fields used by metadata write previews."""
    fields: dict[str, str] = {}
    with open(path, "rb") as f:
        header = f.read(12)
        if len(header) < 12:
            raise ValueError("file is too small to be RIFF/WAVE")
        riff_id, _, wave_id = struct.unpack_from("<4sI4s", header)
        if riff_id not in (b"RIFF", b"RF64") or wave_id != b"WAVE":
            raise ValueError("file is not RIFF/RF64 WAVE")
        while True:
            chunk_header = f.read(8)
            if len(chunk_header) < 8:
                break
            chunk_id, chunk_size = struct.unpack_from("<4sI", chunk_header)
            chunk_data = f.read(chunk_size)
            if chunk_size % 2:
                f.seek(1, 1)
            if chunk_id != b"LIST" or len(chunk_data) < 4 or chunk_data[:4] != b"INFO":
                continue
            offset = 4
            while offset + 8 <= len(chunk_data):
                sub_id, sub_size = struct.unpack_from("<4sI", chunk_data, offset)
                offset += 8
                sub_data = chunk_data[offset : offset + sub_size]
                offset += sub_size + (sub_size % 2)
                key = sub_id.decode("ascii", errors="ignore")
                if len(key) == 4:
                    fields[key] = _decode_riff_info_text(sub_data)
    return fields


def read_bwfmetaedit_fields(path: Path, expected_keys: list[str]) -> dict[str, str | list[str]]:
    """Read BEXT and RIFF INFO fields for BWF MetaEdit-backed write readback."""
    fields: dict[str, str | list[str]] = {}
    bext_fields = read_bext_core_fields(path)
    info_fields = read_riff_info_fields(path)
    for key in expected_keys:
        if key in bext_fields:
            fields[key] = bext_fields[key]
        elif key in info_fields:
            value = info_fields[key]
            fields[key] = _split_multivalue_field(key, value) if key in BWF_METAEDIT_MULTIVALUE_KEYS else value
    return fields


def compare_metadata_write_fixture_readback(manifest_path: Path, quiet: bool = False) -> MetadataWriteReadbackReport:
    """Compare copied fixture WAV BEXT fields against a fixture manifest."""
    resolved_manifest = _resolve_fixture_manifest(manifest_path)
    bundle = load_metadata_write_fixture_bundle(resolved_manifest)
    files: list[MetadataWriteReadbackFile] = []
    report_errors = list(bundle.errors)

    for fixture in bundle.files:
        errors: list[str] = []
        actual_fields: dict[str, str] = {}
        fixture_path = Path(fixture.fixture_path)
        if not fixture_path.exists():
            errors.append("fixture file missing")
        else:
            try:
                if fixture.backend == "mutagen" or (fixture.command and fixture.command[0] == "internal:mutagen"):
                    actual_fields = read_mutagen_fields(fixture_path, list(fixture.expected_fields))
                else:
                    actual_fields = read_bwfmetaedit_fields(fixture_path, list(fixture.expected_fields))
            except ValueError as e:
                errors.append(str(e))
            except RuntimeError as e:
                errors.append(str(e))
            except Exception as e:
                errors.append(str(e))
        errors.extend(fixture.errors)
        matched_fields, mismatched_fields = _compare_expected_fields(fixture.expected_fields, actual_fields)
        files.append(
            MetadataWriteReadbackFile(
                file_id=fixture.file_id,
                source_path=fixture.source_path,
                fixture_path=fixture.fixture_path,
                expected_fields=fixture.expected_fields,
                actual_fields=actual_fields,
                matched_fields=sorted(matched_fields),
                mismatched_fields=mismatched_fields,
                errors=errors,
            )
        )

    report = MetadataWriteReadbackReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        manifest_path=str(resolved_manifest),
        summary=MetadataWriteReadbackSummary(
            files_checked=len(files),
            matched_files=sum(1 for item in files if not item.errors and not item.mismatched_fields),
            mismatched_files=sum(1 for item in files if item.mismatched_fields),
            error_files=sum(1 for item in files if item.errors),
        ),
        files=files,
        errors=report_errors,
    )
    if not quiet:
        show_metadata_write_readback_report(report)
    return report


def apply_metadata_write_plan(
    plan_path: Path,
    db_path: Path | None = None,
    require_reviewed: bool = True,
    dry_run: bool = True,
    backup_dir: Path | None = None,
    log_path: Path | None = None,
    quiet: bool = False,
    config_path: Path | None = None,
    safe_folders: list[Path] | None = None,
    backup: bool = True,
    target_paths: tuple[str, ...] | None = None,
    progress_callback: Callable[[str, int, int | None, str], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> MetadataWriteApplyResult:
    """Apply reviewed Mutagen metadata writes to original files, with backups.

    Backup behavior (added in PR #13 follow-up):

    - ``backup=False``: no backup is taken. The readback safety net can't
      restore on mismatch; only use this when you have an external snapshot.
    - ``backup=True`` (default) and ``backup_dir`` is given: legacy mode —
      backups copy into ``backup_dir`` mirroring source paths. Existing
      callers and tests rely on this; pass an explicit ``--backup-dir`` to
      opt in.
    - ``backup=True`` (default) and no ``backup_dir``: ExifTool-style sibling
      backups — each source ``foo.wav`` gets a ``foo.wav.original-<UTC>Z``
      sibling created via :func:`sfxworkbench.backups.make_original_backup`.
      Cleanup via ``sfx maintenance clean-backups``.
    """
    preview = preview_metadata_write_plan(plan_path, db_path=db_path, require_reviewed=require_reviewed, quiet=True)
    plan = load_metadata_write_plan(plan_path)
    rules = build_preservation_rules(config_path=config_path, safe_folders=safe_folders)
    effective_db = db_path or Path(plan.db_path)
    use_sibling_backup = backup and backup_dir is None
    result = MetadataWriteApplyResult(
        planned=preview.planned,
        skipped=preview.skipped,
        backup_dir=str(backup_dir) if backup_dir is not None else ("sibling" if use_sibling_backup else None),
        dry_run=dry_run,
        target=preview.target,
        errors=list(preview.errors),
    )

    from sfxworkbench.utils import progress_interval

    selection: frozenset[str] | None = frozenset(target_paths) if target_paths is not None else None
    conn = get_connection(effective_db) if not dry_run else None
    total_commands = len(preview.commands)
    report_every = min(progress_interval(total_commands), _PROGRESS_MAX_INTERVAL)
    if progress_callback is not None:
        progress_callback(
            "writing",
            0,
            total_commands,
            _metadata_apply_progress_message(
                processed=0,
                total=total_commands,
                applied=0,
                files_written=0,
                files_backed_up=0,
                files_verified=0,
                skipped=0,
                errors=0,
            ),
        )
    cancelled = False
    try:
        for command_index, command in enumerate(preview.commands):
            # Each metadata write is expensive (MD5, copy backup, mutagen
            # write, readback verify). Cancel polled every 10 commands for
            # sub-second response; the TUI throttles frequent progress emits.
            if command_index > 0 and command_index % 10 == 0:
                if cancel_requested is not None and cancel_requested():
                    cancelled = True
                    break
            if progress_callback is not None and command_index > 0 and command_index % report_every == 0:
                progress_callback(
                    "writing",
                    command_index,
                    total_commands,
                    _metadata_apply_progress_message(
                        processed=command_index,
                        total=total_commands,
                        applied=result.applied,
                        files_written=result.files_written,
                        files_backed_up=result.files_backed_up,
                        files_verified=result.files_verified,
                        skipped=result.skipped,
                        errors=len(result.errors),
                        current=command.path,
                    ),
                )
            if selection is not None and command.path not in selection:
                # Tier 3.8: count selection-filtered commands toward
                # ``result.skipped`` so the apply diagnostic balances —
                # otherwise ``planned - applied - skipped`` would leave the
                # filtered commands unaccounted for.
                result.skipped += command.entry_count or len(command.fields)
                continue
            entry_count = command.entry_count or len(command.fields)
            backend = _command_backend(command)
            source = Path(command.path)
            protected_match = move_protected_by(source, rules)
            if protected_match is not None:
                result.errors.append(
                    {"path": str(source), "error": "protected by safe folder", "safe_folder": protected_match}
                )
                continue
            if dry_run:
                result.applied += entry_count
                result.files_written += 1
                continue
            try:
                source_stat = source.stat()
                target: Path | None
                if backup_dir is not None:
                    target = _backup_target(source, backup_dir)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                elif use_sibling_backup:
                    from sfxworkbench.backups import make_original_backup

                    target = make_original_backup(source)
                else:
                    target = None
                backup_entry = {
                    "path": str(source),
                    "backup_path": str(target) if target is not None else None,
                    "pre_apply_size": source_stat.st_size,
                    "pre_apply_mtime": source_stat.st_mtime,
                    "pre_apply_md5": _md5(source),
                }
                if target is not None:
                    result.files_backed_up += 1
                result.backups.append(backup_entry)
                if backend == "mutagen":
                    write_mutagen_fields(source, command.fields)
                    actual_fields = read_mutagen_fields(source, list(command.fields))
                else:
                    write_result = run_bwfmetaedit_command(command.command, source)
                    result.write_results.append({"path": str(source), **write_result})
                    actual_fields = read_bwfmetaedit_fields(source, list(command.fields))
                post_stat = source.stat()
                backup_entry.update(
                    {
                        "post_apply_size": post_stat.st_size,
                        "post_apply_mtime": post_stat.st_mtime,
                        "post_apply_md5": _md5(source),
                    }
                )
                matched_fields, mismatched_fields = _compare_expected_fields(command.fields, actual_fields)
                result.readback.append(
                    {
                        "path": str(source),
                        "expected_fields": command.fields,
                        "actual_fields": actual_fields,
                        "matched_fields": matched_fields,
                        "mismatched_fields": mismatched_fields,
                    }
                )
                if mismatched_fields:
                    # Verify-on-readback safety net (PR #7). If a backup exists
                    # (sibling or backup_dir mode), restore the original;
                    # otherwise just record the mismatch and let the user
                    # decide.
                    if target is not None:
                        try:
                            shutil.copy2(target, source)
                            result.files_restored += 1
                            restore_note = "; original restored from backup"
                        except OSError as restore_exc:
                            restore_note = f"; BACKUP RESTORE FAILED: {restore_exc}"
                    else:
                        restore_note = "; NO BACKUP AVAILABLE — file may be in inconsistent state"
                    result.errors.append(
                        {
                            "path": str(source),
                            "error": f"metadata readback mismatch{restore_note}",
                            "fields": mismatched_fields,
                            "backup_path": str(target) if target is not None else None,
                        }
                    )
                    continue
                result.files_verified += 1
                if conn is not None:
                    _refresh_indexed_audio_row(conn, source, file_id=command.file_id)
                result.applied += entry_count
                result.files_written += 1
            except Exception as e:
                result.errors.append({"path": str(source), "error": str(e)})
        if conn is not None:
            conn.commit()
    finally:
        if conn is not None:
            conn.close()

    result.cancelled = cancelled
    if progress_callback is not None:
        processed_commands = (
            total_commands
            if not cancelled
            else min(
                result.files_written + result.skipped + len(result.errors),
                total_commands,
            )
        )
        progress_callback(
            "cancelled" if cancelled else "complete",
            processed_commands,
            total_commands,
            _metadata_apply_progress_message(
                processed=processed_commands,
                total=total_commands,
                applied=result.applied,
                files_written=result.files_written,
                files_backed_up=result.files_backed_up,
                files_verified=result.files_verified,
                skipped=result.skipped,
                errors=len(result.errors),
            ),
        )
    if log_path is None and not dry_run:
        log_path = _default_apply_log_path(plan_path)
    if log_path is not None:
        result.log_path = str(log_path)
        write_apply_log(
            log_path,
            plan_path=plan_path,
            tool_version=__version__,
            result=result,
            schema_version=PLAN_SCHEMA_VERSION,
            extra={"db_path": str(effective_db)},
        )
    if not quiet:
        show_metadata_write_apply_result(result)
    return result


def undo_metadata_write_apply_log(
    log_path: Path,
    db_path: Path | None = None,
    dry_run: bool = True,
    quiet: bool = False,
) -> MetadataWriteUndoResult:
    """Restore original files from a metadata write apply log."""
    payload = json.loads(log_path.read_text())
    raw_result = payload.get("result", {})
    backups = raw_result.get("backups", []) if isinstance(raw_result, dict) else []
    effective_db = db_path
    if effective_db is None and payload.get("db_path"):
        effective_db = Path(payload["db_path"])
    result = MetadataWriteUndoResult(
        planned=len(backups),
        log_path=str(log_path),
        dry_run=dry_run,
        target=raw_result.get("target", "embedded_metadata") if isinstance(raw_result, dict) else "embedded_metadata",
    )

    conn = get_connection(effective_db) if effective_db is not None and not dry_run else None
    try:
        for backup in backups:
            if not isinstance(backup, dict):
                result.errors.append({"error": "invalid backup entry"})
                continue
            target_raw = backup.get("path")
            source_raw = backup.get("backup_path")
            if not target_raw:
                result.errors.append({"error": "backup entry missing original path"})
                continue
            if not source_raw:
                result.errors.append({"path": str(target_raw), "error": "backup entry missing backup path"})
                continue
            target = Path(str(target_raw))
            source = Path(str(source_raw))
            if not source.exists():
                result.errors.append({"path": str(source), "error": "backup file missing"})
                continue
            if not target.exists():
                result.errors.append({"path": str(target), "error": "target file missing"})
                continue
            expected_md5 = backup.get("post_apply_md5")
            if expected_md5:
                current_md5 = _md5(target)
                if current_md5 != expected_md5:
                    result.errors.append({"path": str(target), "error": "target changed since apply log was written"})
                    continue
            size = source.stat().st_size
            if dry_run:
                result.restored += 1
                result.bytes_restored += size
                continue
            try:
                shutil.copy2(source, target)
                stat = target.stat()
                if conn is not None:
                    _refresh_indexed_audio_row(conn, target)
                result.restored += 1
                result.bytes_restored += stat.st_size
            except Exception as e:
                result.errors.append({"path": str(target), "error": str(e)})
        if conn is not None:
            conn.commit()
    finally:
        if conn is not None:
            conn.close()

    result.skipped = max(result.planned - result.restored - len(result.errors), 0)
    if not quiet:
        show_metadata_write_undo_result(result)
    return result


def show_metadata_write_plan(plan: MetadataWritePlan) -> None:
    table = Table(title="Embedded metadata write plan", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Backend", plan.backend.display_name)
    table.add_row("Backend available", str(plan.backend.available))
    table.add_row("Candidate entries", f"{plan.summary.candidate_entries:,}")
    table.add_row("Supported entries", f"{plan.summary.supported_entries:,}")
    table.add_row("Conflicts", f"{plan.summary.conflict_entries:,}")
    table.add_row("Skip existing", f"{plan.summary.skip_existing_entries:,}")
    table.add_row("Replace entries", f"{plan.summary.replace_entries:,}")
    table.add_row("Unsupported entries", f"{plan.summary.unsupported_entries:,}")
    table.add_row("Approved entries", f"{plan.summary.approved_entries:,}")
    console.print(table)


def show_metadata_write_preview_result(result: MetadataWritePreviewResult) -> None:
    table = Table(title="Embedded metadata write preview", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Dry run", str(result.dry_run))
    table.add_row("Planned", f"{result.planned:,}")
    table.add_row("Would write", f"{result.would_write:,}")
    table.add_row("Skipped", f"{result.skipped:,}")
    table.add_row("Errors", f"{len(result.errors):,}")
    console.print(table)


def show_metadata_write_readback_report(report: MetadataWriteReadbackReport) -> None:
    table = Table(title="Embedded metadata fixture readback", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Files checked", f"{report.summary.files_checked:,}")
    table.add_row("Matched files", f"{report.summary.matched_files:,}")
    table.add_row("Mismatched files", f"{report.summary.mismatched_files:,}")
    table.add_row("Error files", f"{report.summary.error_files:,}")
    console.print(table)


def show_metadata_write_apply_result(result: MetadataWriteApplyResult) -> None:
    table = Table(title="Embedded metadata write apply", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Dry run", str(result.dry_run))
    table.add_row("Planned", f"{result.planned:,}")
    table.add_row("Applied entries", f"{result.applied:,}")
    table.add_row("Files written", f"{result.files_written:,}")
    table.add_row("Files backed up", f"{result.files_backed_up:,}")
    table.add_row("Files verified", f"{result.files_verified:,}")
    table.add_row("Skipped", f"{result.skipped:,}")
    table.add_row("Errors", f"{len(result.errors):,}")
    console.print(table)


def show_metadata_write_undo_result(result: MetadataWriteUndoResult) -> None:
    table = Table(title="Embedded metadata write undo", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Dry run", str(result.dry_run))
    table.add_row("Planned", f"{result.planned:,}")
    table.add_row("Restored", f"{result.restored:,}")
    table.add_row("Skipped", f"{result.skipped:,}")
    table.add_row("Bytes restored", f"{result.bytes_restored:,}")
    table.add_row("Errors", f"{len(result.errors):,}")
    console.print(table)
