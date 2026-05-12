"""Report-only folder organization previews."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from sfxworkbench import __version__
from sfxworkbench.apply_logs import default_apply_log_path_for_plan
from sfxworkbench.db import get_connection
from sfxworkbench.junk import AUDIO_EXTENSIONS, is_junk_dir
from sfxworkbench.models import (
    NestingApplyResult,
    NestingCandidate,
    NestingMove,
    NestingPlan,
    NestingPlanEntry,
    OrganizeAuditReport,
    OrganizeAuditSummary,
    OrganizeEntry,
    OrganizeReviewResult,
    RenameEntry,
    RenamePlan,
    RenameResult,
)
from sfxworkbench.preservation import PreservationRules, build_preservation_rules, move_protected_by
from sfxworkbench.rename import _update_directory_rows, _update_file_row, apply_rename_plan, undo_rename_log

console = Console()

_SUPPORTED_PATTERNS = {
    "strip-leading-numbers",
    "common-prefix-folders",
    "numeric-series-folders",
    "redundant-nesting",
    "vendor-product-folders",
}
_DOTTED_OR_DASHED_PREFIX_RE = re.compile(r"^\s*\d{1,3}\s*[-_.]\s*(.+?)\s*$")
_SORT_SPACE_PREFIX_RE = re.compile(r"^\s*(?:0\d+|\d)\s+(.+?)\s*$")
_DOUBLE_SPACE_PREFIX_RE = re.compile(r"^\s*\d{1,3}\s{2,}(.+?)\s*$")
_SEPARATOR_RE = re.compile(r"[\s._-]+")
_SURROUNDING_DELIMITERS = (("[", "]"), ("(", ")"))
_VENDOR_PRODUCT_DELIMITER_RE = re.compile(r"\s+-\s+")
_COMPACT_YEAR_SUFFIX_RE = re.compile(r"^(?P<prefix>[A-Za-z][A-Za-z0-9]*?[A-Za-z])(?P<suffix>\d{2,4})$")
_PREFIX_DELIMITER_RE = re.compile(r"^(?P<prefix>[A-Za-z][A-Za-z0-9]*?)(?P<sep>\+{2,}|[_\s.-]+)(?P<suffix>.+)$")
_COMMON_PREFIX_MIN_GROUP_SIZE = 3
_NUMERIC_SERIES_CATALOG = {
    "6000": ("Sound Ideas", "The General Series 6000"),
    "7000": ("Sound Ideas", "Series 7000 Ambience II"),
    "8000": ("Sound Ideas", "Series 8000 Science Fiction"),
    "9000": ("Sound Ideas", "Series 9000 Open and Close"),
    "10000": ("Sound Ideas", "Series 10000 Ambience III"),
    "11000": ("Sound Ideas", "Series 11000 Sports"),
    "12000": ("Sound Ideas", "Series 12000 Anchors Away"),
    "14000": ("Sound Ideas", "Series 14000 Ambience IV"),
    "15000": ("Sound Ideas", "Series 15000 Ambience Stereo"),
}
_CATEGORY_KEYWORDS = {
    "Ambience": {
        "amb",
        "ambience",
        "ambient",
        "background",
        "bg",
        "city",
        "forest",
        "interior",
        "roomtone",
        "rural",
        "traffic",
    },
    "Animals": {"animal", "bird", "birds", "cat", "creature", "dog", "frog", "horse", "insect", "snake"},
    "Crowds": {"applause", "cheer", "crowd", "crowds", "group", "people", "walla"},
    "Doors": {"cabinet", "door", "doors", "drawer", "gate", "hatch", "latch", "lock", "open", "close"},
    "Foley": {"cloth", "foley", "footstep", "footsteps", "movement", "prop", "rustle"},
    "Impacts": {"bang", "crash", "hit", "impact", "impacts", "slam", "smash", "thud"},
    "Machinery": {"engine", "factory", "industrial", "machine", "machinery", "motor", "servo"},
    "Sci-Fi": {"alien", "beep", "laser", "robot", "scifi", "spaceship", "telemetry", "warp"},
    "Sports": {"baseball", "basketball", "football", "game", "hockey", "sport", "sports", "tennis"},
    "Vehicles": {"airplane", "boat", "car", "engine", "ship", "train", "vehicle", "vehicles"},
    "Water": {"boat", "dock", "ocean", "rain", "river", "splash", "water", "wave", "waves"},
    "Weapons": {"cannon", "gun", "gunshot", "rifle", "shot", "weapon", "weapons"},
    "Weather": {"rain", "storm", "thunder", "weather", "wind"},
}
_KNOWN_VENDOR_NAMES = {
    "99sounds": "99Sounds",
    "a sound effect": "A Sound Effect",
    "ghosthack": "Ghosthack",
    "soundmorph": "SoundMorph",
}
_LOW_VALUE_WRAPPER_NAMES = {
    "audio",
    "audios",
    "content",
    "contents",
    "designed",
    "file",
    "files",
    "mono",
    "sample",
    "samples",
    "sound",
    "sounds",
    "source",
    "sources",
    "stereo",
    "wav",
    "wave",
    "waves",
    "wavs",
}
_APPLYABLE_LEAF_WRAPPER_NAMES = {
    "audio",
    "audios",
    "file",
    "files",
    "sample",
    "samples",
    "wav",
    "wave",
    "waves",
    "wavs",
}
_SOURCE_BRANCH_FOLDER_KEYS = {"raw", "source", "sources"}
_DESIGNED_BRANCH_FOLDER_KEYS = {"designed"}
_DESIGN_SPLIT_FOLDER_KEYS = _SOURCE_BRANCH_FOLDER_KEYS | _DESIGNED_BRANCH_FOLDER_KEYS


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_leading_number(name: str) -> str | None:
    """Return a folder name without obvious manual sort or wrapper noise."""
    original = name.strip()
    name = _strip_surrounding_delimiters(name)
    changed = name != original
    for pattern in (_DOTTED_OR_DASHED_PREFIX_RE, _DOUBLE_SPACE_PREFIX_RE, _SORT_SPACE_PREFIX_RE):
        match = pattern.match(name)
        if not match:
            continue
        name = match.group(1).strip(" -_.")
        changed = True
        break

    candidate = _strip_surrounding_delimiters(name)
    if candidate != name:
        changed = True
    candidate = candidate.strip()
    if changed and candidate and candidate != original and not candidate.isdigit():
        return candidate
    return None


def _strip_surrounding_delimiters(name: str) -> str:
    """Strip whole-name square brackets or parentheses without touching inner text."""
    candidate = name.strip()
    changed = True
    while changed:
        changed = False
        for opening, closing in _SURROUNDING_DELIMITERS:
            if candidate.startswith(opening) and candidate.endswith(closing):
                inner = candidate[1:-1].strip()
                if inner:
                    candidate = inner
                    changed = True
                    break
    return candidate


def _is_numeric_category_parent(path: Path, child: Path) -> bool:
    """Return True for meaningful category wrappers such as Vehicles/13000."""
    return path.name in _CATEGORY_KEYWORDS and child.name.isdigit()


def _clean_folder_display_name(name: str) -> str:
    """Apply non-destructive display cleanup used before organization matching."""
    return _strip_leading_number(name) or _strip_surrounding_delimiters(name).strip()


def _vendor_product_parts(name: str) -> tuple[str, str] | None:
    cleaned = _clean_folder_display_name(name)
    cleaned_casefold = cleaned.casefold()
    for vendor_key, vendor in _KNOWN_VENDOR_NAMES.items():
        if not cleaned_casefold.startswith(vendor_key):
            continue
        suffix = cleaned[len(vendor) :]
        if not suffix or suffix[0] not in {" ", "_", "-", "."}:
            continue
        product = _strip_surrounding_delimiters(suffix).strip(" -_.")
        if product:
            return vendor, product

    parts = _VENDOR_PRODUCT_DELIMITER_RE.split(cleaned, maxsplit=1)
    if len(parts) != 2:
        return None
    vendor_raw, product_raw = (part.strip(" -_.") for part in parts)
    vendor = _KNOWN_VENDOR_NAMES.get(vendor_raw.casefold())
    if vendor is None or not product_raw:
        return None
    product = _strip_surrounding_delimiters(product_raw).strip(" -_.")
    if not product or product.casefold() == vendor.casefold():
        return None
    return vendor, product


def _clean_common_prefix_suffix(suffix: str) -> str:
    cleaned = suffix.strip(" -_.+")
    cleaned = re.sub(r"\++", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _common_prefix_parts(name: str) -> tuple[str, str] | None:
    """Extract a repeated sibling prefix and child folder suffix.

    This catches families like ``GDC 2015 - Soniss``, ``GDC+++Game+Audio``,
    ``GDC2023``, and ``CreaturesCK_1``. It deliberately returns only a
    candidate; the audit step requires several sibling matches before planning.
    """
    cleaned = _clean_folder_display_name(name)
    compact = _COMPACT_YEAR_SUFFIX_RE.match(cleaned)
    if compact:
        prefix = compact.group("prefix")
        suffix = compact.group("suffix")
    else:
        match = _PREFIX_DELIMITER_RE.match(cleaned)
        if match is None:
            return None
        prefix = match.group("prefix").strip(" -_.+")
        suffix = match.group("suffix")

    suffix = _clean_common_prefix_suffix(suffix)
    if len(prefix) < 3 or not suffix:
        return None
    if prefix.casefold() in _LOW_VALUE_WRAPPER_NAMES or prefix.casefold() in _KNOWN_VENDOR_NAMES:
        return None
    if not _looks_like_coded_prefix(prefix):
        return None
    return prefix, suffix


def _looks_like_coded_prefix(prefix: str) -> bool:
    """Return True for acronym/code-like prefixes, not normal title-case words."""
    if prefix.isupper() and len(prefix) <= 8:
        return True
    if any(char.isdigit() for char in prefix):
        return True
    return any(char.isupper() for char in prefix[1:])


def _tokenize_name(name: str) -> list[str]:
    normalized = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    return [token.casefold() for token in _SEPARATOR_RE.split(normalized) if token]


def _infer_numeric_folder_category(path: Path) -> str | None:
    scores = {category: 0 for category in _CATEGORY_KEYWORDS}
    audio_files = 0
    for child in path.rglob("*"):
        if not child.is_file() or child.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        audio_files += 1
        token_set = set(_tokenize_name(child.stem))
        for category, keywords in _CATEGORY_KEYWORDS.items():
            scores[category] += len(token_set & keywords)

    if audio_files == 0:
        return None
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_category, best_score = ranked[0]
    next_score = ranked[1][1] if len(ranked) > 1 else 0
    if best_score >= 3 and best_score >= next_score + 2:
        return best_category
    return None


def _iter_dirs_at_depth(root: Path, depth: int) -> list[Path]:
    if depth < 1:
        raise ValueError("depth must be at least 1")
    dirs: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_dir():
            continue
        try:
            rel_parts = path.relative_to(root).parts
        except ValueError:
            continue
        if len(rel_parts) == depth:
            dirs.append(path)
    return sorted(dirs, key=lambda path: str(path).lower())


def _path_depth(root: Path, path: Path) -> int:
    return len(path.relative_to(root).parts)


def _folder_key(name: str) -> str:
    return _SEPARATOR_RE.sub("", name).casefold()


def _walk_directory_stats(root: Path) -> tuple[dict[Path, dict], list[dict]]:
    stats: dict[Path, dict] = {}
    errors: list[dict] = []

    def onerror(error: OSError) -> None:
        errors.append({"path": error.filename or str(root), "error": str(error)})

    for dirpath, dirnames, filenames in os.walk(root, topdown=False, onerror=onerror, followlinks=False):
        path = Path(dirpath)
        child_paths = [path / dirname for dirname in dirnames if not is_junk_dir(path / dirname)]
        audio_files = sum(1 for name in filenames if Path(name).suffix.lower() in AUDIO_EXTENSIONS)
        stats[path] = {
            "child_dirs": len(child_paths),
            "direct_files": len(filenames),
            "audio_files": audio_files + sum(stats.get(child, {}).get("audio_files", 0) for child in child_paths),
            "children": sorted(child_paths, key=lambda child: child.name.casefold()),
        }
    return stats, errors


def _has_source_designed_split(child_keys: set[str]) -> bool:
    return bool(child_keys & _SOURCE_BRANCH_FOLDER_KEYS) and bool(child_keys & _DESIGNED_BRANCH_FOLDER_KEYS)


def _is_source_designed_branch(path: Path, stats: dict[Path, dict] | None = None) -> bool:
    """Return true when Source/Raw and Designed are deliberate sibling branches."""
    name_key = _folder_key(path.name)
    if name_key not in _DESIGN_SPLIT_FOLDER_KEYS:
        return False
    if stats is not None:
        parent_stats = stats.get(path.parent)
        if not parent_stats:
            return False
        child_keys = {_folder_key(child.name) for child in parent_stats.get("children", [])}
    else:
        try:
            child_keys = {_folder_key(child.name) for child in path.parent.iterdir() if child.is_dir()}
        except OSError:
            return False
    return _has_source_designed_split(child_keys)


def _audit_strip_leading_numbers(root: Path, depth: int) -> OrganizeAuditReport:
    dirs = _iter_dirs_at_depth(root, depth)
    entries: list[OrganizeEntry] = []
    errors: list[dict] = []
    planned_targets: set[Path] = set()

    for path in dirs:
        new_name = _strip_leading_number(path.name)
        if not new_name:
            continue

        target = path.with_name(new_name)
        if target == path:
            continue
        if target.exists():
            errors.append({"path": str(path), "target": str(target), "error": "target exists"})
            continue
        if target in planned_targets:
            errors.append({"path": str(path), "target": str(target), "error": "target planned more than once"})
            continue
        planned_targets.add(target)
        entries.append(
            OrganizeEntry(
                old_path=str(path),
                new_path=str(target),
                old_name=path.name,
                new_name=new_name,
            )
        )

    return OrganizeAuditReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=str(root),
        pattern="strip-leading-numbers",
        depth=depth,
        summary=OrganizeAuditSummary(
            directories_scanned=len(dirs),
            planned=len(entries),
            errors=len(errors),
        ),
        entries=entries,
        errors=errors,
    )


def _audit_redundant_nesting(root: Path, depth: int) -> OrganizeAuditReport:
    stats, errors = _walk_directory_stats(root)
    candidates: list[NestingCandidate] = []
    seen: set[tuple[Path, str]] = set()
    dirs = sorted(
        (path for path in stats if path != root and _path_depth(root, path) <= depth),
        key=lambda path: str(path).lower(),
    )

    def add_candidate(
        path: Path,
        kind: str,
        suggested_action: str,
        reason: str,
        target_path: Path | None = None,
        confidence: str = "medium",
    ) -> None:
        key = (path, kind)
        if key in seen:
            return
        seen.add(key)
        path_stats = stats[path]
        candidates.append(
            NestingCandidate(
                path=str(path),
                name=path.name,
                kind=kind,
                suggested_action=suggested_action,
                reason=reason,
                depth=_path_depth(root, path),
                parent_path=str(path.parent),
                target_path=str(target_path) if target_path is not None else None,
                child_dirs=path_stats["child_dirs"],
                direct_files=path_stats["direct_files"],
                audio_files=path_stats["audio_files"],
                confidence=confidence,
            )
        )

    for path in dirs:
        path_stats = stats[path]
        parent_key = _folder_key(path.parent.name)
        name_key = _folder_key(path.name)

        if _is_source_designed_branch(path, stats):
            continue

        if name_key and name_key == parent_key and path_stats["audio_files"] > 0:
            add_candidate(
                path,
                kind="repeated_folder_name",
                suggested_action="review_flatten_child_into_parent",
                reason="folder name repeats its parent",
                target_path=path.parent,
                confidence="high",
            )

        if path_stats["direct_files"] == 0 and path_stats["child_dirs"] == 1 and path_stats["audio_files"] > 0:
            only_child = path_stats["children"][0]
            if (
                not _is_numeric_category_parent(path, only_child)
                and _folder_key(only_child.name) not in _LOW_VALUE_WRAPPER_NAMES
            ):
                add_candidate(
                    path,
                    kind="single_child_chain",
                    suggested_action="review_collapse_wrapper",
                    reason="folder only contains one child folder and no direct files",
                    target_path=only_child,
                )

        if (
            name_key in _APPLYABLE_LEAF_WRAPPER_NAMES
            and path_stats["child_dirs"] == 0
            and path_stats["audio_files"] > 0
        ):
            add_candidate(
                path,
                kind="low_value_wrapper",
                suggested_action="review_flatten_wrapper",
                reason="generic wrapper folder adds little search context",
                target_path=path.parent,
            )

    return OrganizeAuditReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=str(root),
        pattern="redundant-nesting",
        depth=depth,
        summary=OrganizeAuditSummary(
            directories_scanned=len(dirs),
            candidates=len(candidates),
            errors=len(errors),
        ),
        candidates=candidates,
        errors=errors,
    )


def _audit_vendor_product_folders(root: Path, depth: int) -> OrganizeAuditReport:
    dirs = _iter_dirs_at_depth(root, depth)
    entries: list[OrganizeEntry] = []
    errors: list[dict] = []
    planned_targets: set[Path] = set()

    for path in dirs:
        parts = _vendor_product_parts(path.name)
        if parts is None:
            continue
        vendor, product = parts
        target_parent = path.parent / vendor
        target = target_parent / product
        if target == path:
            continue
        if target.exists():
            errors.append({"path": str(path), "target": str(target), "error": "target exists"})
            continue
        if target_parent.exists() and not target_parent.is_dir():
            errors.append({"path": str(path), "target": str(target_parent), "error": "target parent is not a folder"})
            continue
        if target in planned_targets:
            errors.append({"path": str(path), "target": str(target), "error": "target planned more than once"})
            continue
        planned_targets.add(target)
        entries.append(
            OrganizeEntry(
                old_path=str(path),
                new_path=str(target),
                old_name=path.name,
                new_name=product,
                action="rename",
                reason="vendor_product_refolder",
            )
        )

    return OrganizeAuditReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=str(root),
        pattern="vendor-product-folders",
        depth=depth,
        summary=OrganizeAuditSummary(
            directories_scanned=len(dirs),
            planned=len(entries),
            errors=len(errors),
        ),
        entries=entries,
        errors=errors,
    )


def _audit_common_prefix_folders(root: Path, depth: int) -> OrganizeAuditReport:
    dirs = _iter_dirs_at_depth(root, depth)
    errors: list[dict] = []
    groups: dict[tuple[Path, str], list[tuple[Path, str, str]]] = {}

    for path in dirs:
        parts = _common_prefix_parts(path.name)
        if parts is None:
            continue
        prefix, suffix = parts
        groups.setdefault((path.parent, prefix.casefold()), []).append((path, prefix, suffix))

    entries: list[OrganizeEntry] = []
    planned_targets: set[Path] = set()
    for (parent, _key), members in sorted(groups.items(), key=lambda item: (str(item[0][0]).lower(), item[0][1])):
        if len(members) < _COMMON_PREFIX_MIN_GROUP_SIZE:
            continue
        display_prefix = members[0][1]
        for path, _prefix, suffix in sorted(members, key=lambda item: item[0].name.casefold()):
            target_parent = parent / display_prefix
            target = target_parent / suffix
            if target == path:
                continue
            if target.exists():
                errors.append({"path": str(path), "target": str(target), "error": "target exists"})
                continue
            if target_parent.exists() and not target_parent.is_dir():
                errors.append(
                    {"path": str(path), "target": str(target_parent), "error": "target parent is not a folder"}
                )
                continue
            if target in planned_targets:
                errors.append({"path": str(path), "target": str(target), "error": "target planned more than once"})
                continue
            planned_targets.add(target)
            entries.append(
                OrganizeEntry(
                    old_path=str(path),
                    new_path=str(target),
                    old_name=path.name,
                    new_name=suffix,
                    action="rename",
                    reason="common_prefix_refolder",
                )
            )

    return OrganizeAuditReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=str(root),
        pattern="common-prefix-folders",
        depth=depth,
        summary=OrganizeAuditSummary(
            directories_scanned=len(dirs),
            planned=len(entries),
            errors=len(errors),
        ),
        entries=entries,
        errors=errors,
    )


def _audit_numeric_series_folders(root: Path, depth: int) -> OrganizeAuditReport:
    dirs = _iter_dirs_at_depth(root, depth)
    entries: list[OrganizeEntry] = []
    candidates: list[NestingCandidate] = []
    errors: list[dict] = []
    planned_targets: set[Path] = set()

    for path in dirs:
        if not path.name.isdigit():
            continue

        catalog_match = _NUMERIC_SERIES_CATALOG.get(path.name)
        if catalog_match is not None:
            vendor, series_name = catalog_match
            target_parent = path.parent / vendor
            target = target_parent / series_name
            reason = "numeric_series_catalog"
            new_name = series_name
        else:
            inferred = _infer_numeric_folder_category(path)
            if inferred is None:
                candidates.append(
                    NestingCandidate(
                        path=str(path),
                        name=path.name,
                        kind="numeric_series_unknown",
                        suggested_action="review_or_add_series_catalog_entry",
                        reason="strictly numeric folder has no catalog match or confident filename-category guess",
                        depth=_path_depth(root, path),
                        parent_path=str(path.parent),
                        child_dirs=sum(1 for child in path.iterdir() if child.is_dir()),
                        direct_files=sum(1 for child in path.iterdir() if child.is_file()),
                        audio_files=sum(
                            1
                            for child in path.rglob("*")
                            if child.is_file() and child.suffix.lower() in AUDIO_EXTENSIONS
                        ),
                        confidence="low",
                    )
                )
                continue
            target_parent = path.parent / inferred
            target = target_parent / path.name
            reason = "numeric_series_inferred_category"
            new_name = path.name

        if target == path:
            continue
        if target.exists():
            errors.append({"path": str(path), "target": str(target), "error": "target exists"})
            continue
        if target_parent.exists() and not target_parent.is_dir():
            errors.append({"path": str(path), "target": str(target_parent), "error": "target parent is not a folder"})
            continue
        if target in planned_targets:
            errors.append({"path": str(path), "target": str(target), "error": "target planned more than once"})
            continue
        planned_targets.add(target)
        entries.append(
            OrganizeEntry(
                old_path=str(path),
                new_path=str(target),
                old_name=path.name,
                new_name=new_name,
                action="rename",
                reason=reason,
            )
        )

    return OrganizeAuditReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=str(root),
        pattern="numeric-series-folders",
        depth=depth,
        summary=OrganizeAuditSummary(
            directories_scanned=len(dirs),
            planned=len(entries),
            candidates=len(candidates),
            errors=len(errors),
        ),
        entries=entries,
        candidates=candidates,
        errors=errors,
    )


def audit_organization(
    root: Path,
    pattern: str = "strip-leading-numbers",
    depth: int = 1,
    *,
    config_path: Path | None = None,
    safe_folders: list[Path] | None = None,
) -> OrganizeAuditReport:
    """Build a report-only folder organization preview."""
    if pattern not in _SUPPORTED_PATTERNS:
        supported = "', '".join(sorted(_SUPPORTED_PATTERNS))
        raise ValueError(f"Supported patterns: '{supported}'")
    if depth < 1:
        raise ValueError("depth must be at least 1")

    root = root.resolve()
    rules = build_preservation_rules(config_path=config_path, safe_folders=safe_folders)
    if pattern == "strip-leading-numbers":
        report = _audit_strip_leading_numbers(root, depth)
    elif pattern == "vendor-product-folders":
        report = _audit_vendor_product_folders(root, depth)
    elif pattern == "common-prefix-folders":
        report = _audit_common_prefix_folders(root, depth)
    elif pattern == "numeric-series-folders":
        report = _audit_numeric_series_folders(root, depth)
    else:
        report = _audit_redundant_nesting(root, depth)
    return _apply_organize_safe_folder_blocks(report, rules)


def write_organize_audit_report(report: OrganizeAuditReport, output_path: Path, quiet: bool = False) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.model_dump(), indent=2))
    if not quiet:
        console.print(f"Organization preview written to [cyan]{output_path}[/cyan]")


def _default_nesting_log_path(plan_path: Path) -> Path:
    return default_apply_log_path_for_plan(plan_path, "nesting_log")


def _write_nesting_plan(plan: NestingPlan, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(plan.model_dump(), indent=2))


def build_nesting_plan_from_report(
    report_path: Path,
    kind: str = "repeated_folder_name",
    output_path: Path | None = None,
    quiet: bool = False,
    config_path: Path | None = None,
    safe_folders: list[Path] | None = None,
) -> NestingPlan:
    """Build a reviewed-plan candidate from a redundant nesting audit."""
    raw_report = json.loads(report_path.read_text())
    report = OrganizeAuditReport.model_validate(raw_report)
    rules = build_preservation_rules(config_path=config_path, safe_folders=safe_folders)
    errors: list[dict] = list(report.errors)
    entries: list[NestingPlanEntry] = []
    supported_kinds = {"repeated_folder_name", "single_child_chain", "low_value_wrapper"}

    if report.pattern != "redundant-nesting":
        errors.append({"path": report.root, "error": "source report must use pattern='redundant-nesting'"})
    if kind not in supported_kinds:
        errors.append({"path": report.root, "error": f"candidate kind '{kind}' is report-only"})

    for candidate in report.candidates:
        if candidate.kind != kind:
            continue
        source = Path(candidate.path)
        if not source.exists() or not source.is_dir():
            errors.append({"path": str(source), "error": "source directory missing"})
            continue
        if _is_source_designed_branch(source):
            continue

        if candidate.kind == "repeated_folder_name":
            target = Path(candidate.target_path) if candidate.target_path is not None else source.parent
            if source.parent != target:
                errors.append({"path": str(source), "target": str(target), "error": "target must be source parent"})
                continue
            if not target.exists() or not target.is_dir():
                errors.append({"path": str(source), "target": str(target), "error": "target directory missing"})
                continue

            moves: list[NestingMove] = []
            planned_targets: set[Path] = set()
            for child in sorted(source.iterdir(), key=lambda path: path.name.casefold()):
                destination = target / child.name
                if destination.exists():
                    errors.append({"path": str(child), "target": str(destination), "error": "target exists"})
                    continue
                if destination in planned_targets:
                    errors.append(
                        {"path": str(child), "target": str(destination), "error": "target planned more than once"}
                    )
                    continue
                planned_targets.add(destination)
                moves.append(
                    NestingMove(
                        old_path=str(child),
                        new_path=str(destination),
                        path_type="dir" if child.is_dir() else "file",
                    )
                )
            action = "flatten_child_into_parent"
            target_path = target
        elif candidate.kind == "single_child_chain":
            children = sorted(source.iterdir(), key=lambda path: path.name.casefold())
            if len(children) != 1 or not children[0].is_dir():
                errors.append({"path": str(source), "error": "source must contain exactly one child directory"})
                continue
            child = children[0]
            if _is_numeric_category_parent(source, child):
                continue
            if _folder_key(child.name) in _LOW_VALUE_WRAPPER_NAMES:
                continue
            target_path = source.parent
            destination = target_path / child.name
            if destination.exists():
                errors.append({"path": str(child), "target": str(destination), "error": "target exists"})
                continue
            moves = [
                NestingMove(
                    old_path=str(child),
                    new_path=str(destination),
                    path_type="dir",
                )
            ]
            action = "collapse_single_child_wrapper"
        else:
            if _folder_key(source.name) not in _APPLYABLE_LEAF_WRAPPER_NAMES:
                continue
            children = sorted(source.iterdir(), key=lambda path: path.name.casefold())
            if any(child.is_dir() for child in children):
                continue
            target_path = Path(candidate.target_path) if candidate.target_path is not None else source.parent
            if source.parent != target_path:
                errors.append(
                    {"path": str(source), "target": str(target_path), "error": "target must be source parent"}
                )
                continue
            if not target_path.exists() or not target_path.is_dir():
                errors.append({"path": str(source), "target": str(target_path), "error": "target directory missing"})
                continue
            moves = []
            planned_targets: set[Path] = set()
            for child in children:
                destination = target_path / child.name
                if destination.exists():
                    errors.append({"path": str(child), "target": str(destination), "error": "target exists"})
                    continue
                if destination in planned_targets:
                    errors.append(
                        {"path": str(child), "target": str(destination), "error": "target planned more than once"}
                    )
                    continue
                planned_targets.add(destination)
                moves.append(
                    NestingMove(
                        old_path=str(child),
                        new_path=str(destination),
                        path_type="file",
                    )
                )
            action = "flatten_low_value_leaf_wrapper"

        if not moves:
            errors.append({"path": str(source), "error": "no children to move"})
            continue
        entry = NestingPlanEntry(
            source_path=str(source),
            target_path=str(target_path),
            kind=candidate.kind,
            action=action,
            reason=candidate.reason,
            audio_files=candidate.audio_files,
            moves=moves,
        )
        entry_protection_errors = _nesting_protection_errors(entry, rules)
        if entry_protection_errors:
            errors.extend(entry_protection_errors)
            continue
        entries.append(entry)

    plan = NestingPlan(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=report.root,
        source_report=str(report_path),
        entries=sorted(
            entries, key=lambda entry: (len(Path(entry.source_path).parts), entry.source_path), reverse=True
        ),
        errors=errors,
    )
    if output_path is not None:
        _write_nesting_plan(plan, output_path)
        if not quiet:
            console.print(f"Nesting plan written to [cyan]{output_path}[/cyan]")
    return plan


def review_organize_report(
    report_path: Path,
    output_path: Path | None = None,
    approve_all: bool = False,
    entries: list[int] | None = None,
    quiet: bool = False,
) -> OrganizeReviewResult:
    """Stamp an organization report with approved entry indexes."""
    report = json.loads(report_path.read_text())
    total = len(report.get("entries", []))
    requested = set(entries or [])
    invalid = sorted(entry for entry in requested if entry < 1 or entry > total)
    if approve_all:
        approved = set(range(total))
    else:
        approved = {entry - 1 for entry in requested if 1 <= entry <= total}

    existing_review = report.get("review", {})
    approved.update(existing_review.get("approved_entries", []))
    approved_entries = sorted(approved)
    report["review"] = {
        "status": "approved" if len(approved_entries) == total and total else "partially_approved",
        "approved_at": _now_iso(),
        "approved_entries": approved_entries,
    }

    output = output_path or report_path
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    result = OrganizeReviewResult(
        report_path=str(report_path),
        output_path=str(output),
        total_entries=total,
        approved_entries=len(approved_entries),
        invalid_entries=invalid,
    )
    if not quiet:
        console.print(
            f"Approved [yellow]{result.approved_entries:,}[/yellow] of "
            f"[yellow]{result.total_entries:,}[/yellow] organization entry/entries in [cyan]{output}[/cyan]"
        )
        if invalid:
            console.print(f"[red]Ignored invalid entry number(s): {', '.join(str(i) for i in invalid)}[/red]")
    return result


def _rename_plan_from_report(report: OrganizeAuditReport, raw_report: dict, require_reviewed: bool) -> RenamePlan:
    approved = set(raw_report.get("review", {}).get("approved_entries", []))
    entries: list[RenameEntry] = []
    errors = list(report.errors)
    applyable_patterns = {
        "strip-leading-numbers",
        "common-prefix-folders",
        "numeric-series-folders",
        "vendor-product-folders",
    }
    if report.pattern not in applyable_patterns:
        errors.append(
            {
                "path": report.root,
                "error": f"organize pattern '{report.pattern}' is report-only and cannot be applied",
            }
        )
        return RenamePlan(
            generated_at=_now_iso(),
            root=report.root,
            pattern=f"organize:{report.pattern}",
            entries=[],
            errors=errors,
        )
    if require_reviewed and not approved:
        errors.append({"path": raw_report.get("root"), "error": "report has no approved entries"})

    for index, entry in enumerate(report.entries):
        if entry.action != "rename":
            errors.append({"path": entry.old_path, "error": f"entry {index + 1} action is not applicable"})
            continue
        if require_reviewed and index not in approved:
            errors.append({"path": entry.old_path, "error": f"entry {index + 1} is not approved"})
            continue
        entries.append(
            RenameEntry(
                old_path=entry.old_path,
                new_path=entry.new_path,
                old_filename=entry.old_name,
                new_filename=entry.new_name,
                issue_fixes=(
                    [entry.reason, "create_parent_folder"] if _needs_parent_creation(entry) else [entry.reason]
                ),
            )
        )

    return RenamePlan(
        generated_at=_now_iso(),
        root=report.root,
        pattern=f"organize:{report.pattern}",
        entries=sorted(entries, key=lambda entry: (len(Path(entry.old_path).parts), entry.old_path), reverse=True),
        errors=errors,
    )


def _needs_parent_creation(entry: OrganizeEntry) -> bool:
    return (
        entry.reason
        in {
            "common_prefix_refolder",
            "numeric_series_catalog",
            "numeric_series_inferred_category",
            "vendor_product_refolder",
        }
        and not Path(entry.new_path).parent.exists()
    )


def _protection_error(path: Path, rules: PreservationRules) -> dict | None:
    protected_match = move_protected_by(path, rules)
    if protected_match is None:
        return None
    return {"path": str(path), "error": "protected by safe folder", "safe_folder": protected_match}


def _apply_organize_safe_folder_blocks(report: OrganizeAuditReport, rules: PreservationRules) -> OrganizeAuditReport:
    if not rules.safe_folders:
        return report
    entries: list[OrganizeEntry] = []
    errors = list(report.errors)
    for entry in report.entries:
        protection_error = _protection_error(Path(entry.old_path), rules)
        if protection_error is not None:
            errors.append(protection_error)
            continue
        entries.append(entry)
    summary = report.summary.model_copy(update={"planned": len(entries), "errors": len(errors)})
    return report.model_copy(update={"entries": entries, "errors": errors, "summary": summary})


def _nesting_protection_errors(entry: NestingPlanEntry, rules: PreservationRules) -> list[dict]:
    if not rules.safe_folders:
        return []
    errors: list[dict] = []
    source_error = _protection_error(Path(entry.source_path), rules)
    if source_error is not None:
        errors.append(source_error)
    for move in entry.moves:
        move_error = _protection_error(Path(move.old_path), rules)
        if move_error is not None:
            errors.append(move_error)
    return errors


def apply_organize_report(
    report_path: Path,
    db_path: Path | None = None,
    log_path: Path | None = None,
    require_reviewed: bool = False,
    quiet: bool = False,
    config_path: Path | None = None,
    safe_folders: list[Path] | None = None,
) -> RenameResult:
    """Apply a reviewed organization report using the rename engine."""
    raw_report = json.loads(report_path.read_text())
    report = OrganizeAuditReport.model_validate(raw_report)
    rules = build_preservation_rules(config_path=config_path, safe_folders=safe_folders)
    report = _apply_organize_safe_folder_blocks(report, rules)
    plan = _rename_plan_from_report(report, raw_report, require_reviewed=require_reviewed)
    if log_path is None:
        log_path = default_apply_log_path_for_plan(report_path, "organize_log")
    return apply_rename_plan(
        plan,
        db_path=db_path,
        log_path=log_path,
        dry_run=False,
        quiet=quiet,
        config_path=config_path,
        safe_folders=safe_folders,
    )


def _approved_entry_indexes(raw_plan: dict) -> set[int]:
    return set(raw_plan.get("review", {}).get("approved_entries", []))


def _update_moved_path_rows(conn, old: Path, new: Path, root: Path) -> None:
    if new.is_dir():
        _update_directory_rows(conn, old, new, root)
    else:
        _update_file_row(conn, old, new, root)


def apply_nesting_plan(
    plan_path: Path,
    db_path: Path | None = None,
    log_path: Path | None = None,
    require_reviewed: bool = False,
    dry_run: bool = True,
    quiet: bool = False,
    config_path: Path | None = None,
    safe_folders: list[Path] | None = None,
) -> NestingApplyResult:
    """Flatten repeated-folder-name entries from a reviewed nesting plan."""
    raw_plan = json.loads(plan_path.read_text())
    plan = NestingPlan.model_validate(raw_plan)
    rules = build_preservation_rules(config_path=config_path, safe_folders=safe_folders)
    approved = _approved_entry_indexes(raw_plan)
    result = NestingApplyResult(planned=len(plan.entries), dry_run=dry_run)
    errors = list(plan.errors)

    if errors:
        result.errors.extend(errors)
        if not quiet:
            console.print("[red]Refusing to apply nesting plan with unresolved errors.[/red]")
        return result
    if require_reviewed and not approved:
        result.errors.append({"path": plan.root, "error": "plan has no approved entries"})
        return result

    selected_entries: list[tuple[int, NestingPlanEntry]] = []
    for index, entry in enumerate(plan.entries):
        if require_reviewed and index not in approved:
            result.errors.append({"path": entry.source_path, "error": f"entry {index + 1} is not approved"})
            continue
        entry_protection_errors = _nesting_protection_errors(entry, rules)
        if entry_protection_errors:
            result.errors.extend(entry_protection_errors)
            continue
        selected_entries.append((index, entry))

    if result.errors:
        return result
    if dry_run:
        result.flattened = len(selected_entries)
        result.moved = sum(len(entry.moves) for _, entry in selected_entries)
        if not quiet:
            show_nesting_plan(plan)
        return result

    if log_path is None:
        log_path = _default_nesting_log_path(plan_path)
    conn = get_connection(db_path) if db_path is not None else None
    root = Path(plan.root)
    applied: list[NestingPlanEntry] = []

    for _, entry in selected_entries:
        source = Path(entry.source_path)
        target = Path(entry.target_path)
        if not source.exists() or not source.is_dir():
            result.errors.append({"path": str(source), "error": "source directory missing"})
            continue
        if not target.exists() or not target.is_dir():
            result.errors.append({"path": str(source), "target": str(target), "error": "target directory missing"})
            continue

        entry_errors: list[dict] = []
        for move in entry.moves:
            old = Path(move.old_path)
            new = Path(move.new_path)
            if not old.exists():
                entry_errors.append({"path": str(old), "error": "source missing"})
            if new.exists():
                entry_errors.append({"path": str(old), "target": str(new), "error": "target exists"})
        if entry_errors:
            result.errors.extend(entry_errors)
            continue

        moved_for_entry: list[NestingMove] = []
        for move in entry.moves:
            old = Path(move.old_path)
            new = Path(move.new_path)
            try:
                old.rename(new)
                moved_for_entry.append(move)
                result.moved += 1
                if conn is not None:
                    _update_moved_path_rows(conn, old, new, root)
            except OSError as e:
                result.errors.append({"path": str(old), "target": str(new), "error": str(e)})
                break

        if moved_for_entry:
            applied.append(entry.model_copy(update={"moves": moved_for_entry}))
        if moved_for_entry and len(moved_for_entry) == len(entry.moves):
            try:
                source.rmdir()
            except OSError as e:
                result.errors.append({"path": str(source), "error": f"could not remove emptied folder: {e}"})
            result.flattened += 1

    if conn is not None:
        conn.commit()
        conn.close()

    log_plan = plan.model_copy(update={"entries": applied, "errors": []})
    _write_nesting_plan(log_plan, log_path)
    result.log_path = str(log_path)
    if not quiet:
        console.print(f"Nesting undo log written to [cyan]{log_path}[/cyan]")
    return result


def undo_nesting_log(
    log_path: Path,
    db_path: Path | None = None,
    dry_run: bool = True,
    quiet: bool = False,
) -> NestingApplyResult:
    """Undo a previously applied nesting flatten log."""
    plan = NestingPlan.model_validate(json.loads(log_path.read_text()))
    result = NestingApplyResult(planned=len(plan.entries), dry_run=dry_run, log_path=str(log_path))
    conn = get_connection(db_path) if db_path is not None and not dry_run else None
    root = Path(plan.root)

    for entry in reversed(plan.entries):
        source = Path(entry.source_path)
        if dry_run:
            result.undone += 1
            result.moved += len(entry.moves)
            continue
        source.mkdir(exist_ok=True)
        entry_errors: list[dict] = []
        for move in reversed(entry.moves):
            old = Path(move.old_path)
            new = Path(move.new_path)
            if not new.exists():
                entry_errors.append({"path": str(new), "error": "flattened path missing"})
            if old.exists():
                entry_errors.append({"path": str(new), "target": str(old), "error": "original path exists"})
        if entry_errors:
            result.errors.extend(entry_errors)
            continue
        for move in reversed(entry.moves):
            old = Path(move.old_path)
            new = Path(move.new_path)
            try:
                new.rename(old)
                result.moved += 1
                if conn is not None:
                    _update_moved_path_rows(conn, new, old, root)
            except OSError as e:
                result.errors.append({"path": str(new), "target": str(old), "error": str(e)})
                break
        else:
            result.undone += 1

    if conn is not None:
        conn.commit()
        conn.close()
    return result


def undo_organize_log(
    log_path: Path,
    db_path: Path | None = None,
    dry_run: bool = True,
    quiet: bool = False,
) -> RenameResult:
    """Undo a previously applied organization log."""
    return undo_rename_log(log_path, db_path=db_path, dry_run=dry_run, quiet=quiet)


def show_nesting_plan(plan: NestingPlan) -> None:
    console.print(
        f"Planned [yellow]{len(plan.entries):,}[/yellow] nesting flatten(s), "
        f"found [yellow]{len(plan.errors):,}[/yellow] error(s)."
    )
    if plan.entries:
        table = Table(title="Repeated folder flatten plan", show_lines=False)
        table.add_column("Repeated Folder", style="white")
        table.add_column("Target", style="cyan")
        table.add_column("Moves", justify="right", style="yellow")
        for entry in plan.entries[:50]:
            table.add_row(entry.source_path, entry.target_path, f"{len(entry.moves):,}")
        console.print(table)
        if len(plan.entries) > 50:
            console.print(f"[dim]...{len(plan.entries) - 50} more flatten(s).[/dim]")
    if plan.errors:
        console.print("[red]Plan has collision/error(s); apply would be refused until resolved.[/red]")


def show_organize_audit_report(report: OrganizeAuditReport) -> None:
    console.print(
        f"Scanned [yellow]{report.summary.directories_scanned:,}[/yellow] folder(s), "
        f"planned [yellow]{report.summary.planned:,}[/yellow] rename(s), "
        f"found [yellow]{report.summary.candidates:,}[/yellow] review candidate(s), "
        f"found [yellow]{report.summary.errors:,}[/yellow] error(s)."
    )
    if report.entries:
        table = Table(title="Folder organization preview", show_lines=False)
        table.add_column("Old", style="white")
        table.add_column("New", style="cyan")
        for entry in report.entries[:50]:
            table.add_row(entry.old_name, entry.new_name)
        console.print(table)
        if len(report.entries) > 50:
            console.print(f"[dim]...{len(report.entries) - 50} more planned rename(s).[/dim]")
    if report.candidates:
        table = Table(title="Folder structure review candidates", show_lines=False)
        table.add_column("Kind", style="cyan")
        table.add_column("Folder", style="white")
        table.add_column("Suggestion", style="yellow")
        table.add_column("Audio", justify="right")
        for candidate in report.candidates[:50]:
            table.add_row(
                candidate.kind,
                candidate.path,
                candidate.suggested_action,
                f"{candidate.audio_files:,}",
            )
        console.print(table)
        if len(report.candidates) > 50:
            console.print(f"[dim]...{len(report.candidates) - 50} more review candidate(s).[/dim]")
    if report.errors:
        console.print("[red]Preview has collision/error(s); apply would be refused until resolved.[/red]")
