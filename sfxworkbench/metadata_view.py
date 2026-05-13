"""Per-file indexed metadata view for quick review."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from sfxworkbench import __version__
from sfxworkbench.db import DEFAULT_DB_PATH, get_connection
from sfxworkbench.models import (
    MetadataViewEmbeddedField,
    MetadataViewFile,
    MetadataViewReport,
    MetadataViewTag,
    MetadataViewUcs,
)
from sfxworkbench.ucs import normalize_stem, parse_ucs_stem
from sfxworkbench.ucs_catalog import load_catalog, lookup_entry, resolve_catalog_path

console = Console()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _decode_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return [raw]
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _decode_bool(value) -> bool:
    return bool(value)


def _load_matching_file_rows(db_path: Path, query: str, limit: int):
    conn = get_connection(db_path)
    exact_path = str(Path(query).expanduser())
    like_query = f"%{query}%"
    rows = conn.execute(
        """
        SELECT id, path, filename, stem, extension, size_bytes, mtime, md5,
               sample_rate, bit_depth, channels, duration_s, subtype,
               has_bext, has_ixml, has_riff_info, has_adm, has_cue_markers,
               has_sampler, metadata_sources, is_ucs, scan_error, scanned_at
        FROM files
        WHERE path = ?
           OR filename = ?
           OR stem = ?
           OR path LIKE ?
           OR filename LIKE ?
           OR stem LIKE ?
        ORDER BY
            CASE
                WHEN path = ? THEN 0
                WHEN filename = ? THEN 1
                WHEN stem = ? THEN 2
                ELSE 3
            END,
            path
        LIMIT ?
        """,
        (
            exact_path,
            query,
            query,
            like_query,
            like_query,
            like_query,
            exact_path,
            query,
            query,
            limit,
        ),
    ).fetchall()
    file_ids = [row["id"] for row in rows]
    tags_by_file: dict[int, list[MetadataViewTag]] = {}
    embedded_by_file: dict[int, list[MetadataViewEmbeddedField]] = {}
    if file_ids:
        # Use a temp table rather than inlining one ``?`` per file_id. Caller
        # currently bounds ``limit`` to ~100, but bumping the CLI flag (or a
        # future caller forgetting this constraint) would otherwise blow past
        # SQLite's variable cap silently. Same hardening pattern as
        # ``metadata_workbench_rows`` / ``metadata_tag_change_rows``.
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS _view_file_ids (file_id INTEGER PRIMARY KEY)")
        conn.execute("DELETE FROM _view_file_ids")
        conn.executemany("INSERT OR IGNORE INTO _view_file_ids (file_id) VALUES (?)", ((fid,) for fid in file_ids))
        tag_rows = conn.execute(
            """
            SELECT t.file_id, t.field, t.value, t.source, t.method, t.confidence, t.evidence
            FROM accepted_tags t
            JOIN _view_file_ids v ON v.file_id = t.file_id
            ORDER BY t.field, t.value, t.source
            """
        ).fetchall()
        for tag in tag_rows:
            tags_by_file.setdefault(tag["file_id"], []).append(
                MetadataViewTag(
                    field=tag["field"],
                    value=tag["value"],
                    source=tag["source"],
                    method=tag["method"],
                    confidence=tag["confidence"],
                    evidence=_decode_json_list(tag["evidence"]),
                )
            )
        embedded_rows = conn.execute(
            """
            SELECT mf.file_id, mf.namespace, mf.key, mf.value, mf.source
            FROM metadata_fields mf
            JOIN _view_file_ids v ON v.file_id = mf.file_id
            ORDER BY mf.namespace, mf.key, mf.value, mf.source
            """
        ).fetchall()
        for field in embedded_rows:
            embedded_by_file.setdefault(field["file_id"], []).append(
                MetadataViewEmbeddedField(
                    namespace=field["namespace"],
                    key=field["key"],
                    value=field["value"],
                    source=field["source"],
                )
            )
    conn.close()
    return rows, tags_by_file, embedded_by_file


def _build_ucs_view(stem: str, catalog, catalog_release_version: str | None) -> MetadataViewUcs:
    normalized = normalize_stem(stem)
    parsed = parse_ucs_stem(normalized)
    entry = (
        lookup_entry(catalog, parsed.category, parsed.subcategory) if catalog is not None and parsed.is_ucs else None
    )
    return MetadataViewUcs(
        stem=normalized,
        is_ucs=parsed.is_ucs,
        category=parsed.category,
        subcategory=parsed.subcategory,
        remainder=parsed.remainder,
        source=parsed.source,
        catalog_match=entry is not None,
        catalog_category=entry.category if entry is not None else None,
        catalog_subcategory=entry.subcategory if entry is not None else None,
        catalog_cat_short=entry.cat_short if entry is not None else None,
        catalog_cat_id=entry.cat_id if entry is not None else None,
        catalog_release_version=catalog_release_version if entry is not None else None,
    )


def build_metadata_view_report(
    query: str,
    db_path: Path = DEFAULT_DB_PATH,
    *,
    catalog_path: Path | None = None,
    limit: int = 5,
) -> MetadataViewReport:
    """Build a compact per-file view from the SQLite index and accepted tags."""
    if limit <= 0:
        raise ValueError("--limit must be greater than 0")
    resolved_catalog_path = resolve_catalog_path(catalog_path)
    catalog = load_catalog(catalog_path)
    catalog_release_version = catalog.provenance.release_version if catalog is not None else None
    rows, tags_by_file, embedded_by_file = _load_matching_file_rows(db_path, query, limit)

    files: list[MetadataViewFile] = []
    for row in rows:
        stem = row["stem"] or Path(row["path"]).stem
        files.append(
            MetadataViewFile(
                file_id=row["id"],
                path=row["path"],
                filename=row["filename"],
                stem=row["stem"],
                extension=row["extension"],
                size_bytes=row["size_bytes"],
                mtime=row["mtime"],
                md5=row["md5"],
                sample_rate=row["sample_rate"],
                bit_depth=row["bit_depth"],
                channels=row["channels"],
                duration_s=row["duration_s"],
                subtype=row["subtype"],
                has_bext=_decode_bool(row["has_bext"]),
                has_ixml=_decode_bool(row["has_ixml"]),
                has_riff_info=_decode_bool(row["has_riff_info"]),
                has_adm=_decode_bool(row["has_adm"]),
                has_cue_markers=_decode_bool(row["has_cue_markers"]),
                has_sampler=_decode_bool(row["has_sampler"]),
                metadata_sources=_decode_json_list(row["metadata_sources"]),
                is_ucs=_decode_bool(row["is_ucs"]),
                scan_error=row["scan_error"],
                ucs=_build_ucs_view(stem, catalog, catalog_release_version),
                embedded_fields=embedded_by_file.get(row["id"], []),
                accepted_tags=tags_by_file.get(row["id"], []),
            )
        )

    return MetadataViewReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        db_path=str(db_path),
        query=query,
        catalog_path=str(resolved_catalog_path.resolve()) if resolved_catalog_path is not None else None,
        limit=limit,
        match_count=len(files),
        files=files,
    )


def show_metadata_view_report(report: MetadataViewReport) -> None:
    if not report.files:
        console.print(f"No indexed files matched [yellow]{report.query}[/yellow].")
        return

    for file in report.files:
        table = Table(title=f"Metadata: {file.filename}", show_lines=False)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        table.add_row("Path", file.path)
        table.add_row("File ID", str(file.file_id))
        table.add_row("Format", file.extension or "")
        table.add_row("Sample rate", str(file.sample_rate or ""))
        table.add_row("Bit depth", str(file.bit_depth or ""))
        table.add_row("Channels", str(file.channels or ""))
        table.add_row("Duration", f"{file.duration_s:.3f}s" if file.duration_s is not None else "")
        table.add_row("Subtype", file.subtype or "")
        table.add_row("MD5", file.md5 or "")
        table.add_row("Embedded flags", _format_embedded_flags(file))
        table.add_row("Metadata sources", ", ".join(file.metadata_sources))
        table.add_row("Scan error", file.scan_error or "")
        console.print(table)

        if file.embedded_fields:
            embedded = Table(title="Embedded Fields", show_lines=False)
            embedded.add_column("Namespace", style="cyan")
            embedded.add_column("Key")
            embedded.add_column("Value")
            embedded.add_column("Source")
            for item in file.embedded_fields:
                embedded.add_row(item.namespace, item.key, item.value, item.source)
            console.print(embedded)

        if file.ucs is not None and file.ucs.is_ucs:
            ucs = Table(title="UCS Parse", show_lines=False)
            ucs.add_column("Field", style="cyan")
            ucs.add_column("Value")
            ucs.add_row("Parsed", f"{file.ucs.category or ''} / {file.ucs.subcategory or ''}")
            ucs.add_row("Remainder", file.ucs.remainder or "")
            ucs.add_row("Catalog match", str(file.ucs.catalog_match))
            if file.ucs.catalog_match:
                ucs.add_row("Catalog", f"{file.ucs.catalog_category} / {file.ucs.catalog_subcategory}")
                ucs.add_row("CatID", file.ucs.catalog_cat_id or "")
            console.print(ucs)

        if file.accepted_tags:
            tags = Table(title="Accepted DB Tags", show_lines=False)
            tags.add_column("Field", style="cyan")
            tags.add_column("Value")
            tags.add_column("Source")
            tags.add_column("Conf", justify="right")
            for tag in file.accepted_tags:
                confidence = "" if tag.confidence is None else f"{tag.confidence:.2f}"
                tags.add_row(tag.field, tag.value, tag.source, confidence)
            console.print(tags)


def _format_embedded_flags(file: MetadataViewFile) -> str:
    flags = [
        ("bext", file.has_bext),
        ("iXML", file.has_ixml),
        ("RIFF INFO", file.has_riff_info),
        ("ADM", file.has_adm),
        ("cue", file.has_cue_markers),
        ("sampler", file.has_sampler),
    ]
    present = [name for name, enabled in flags if enabled]
    return ", ".join(present) if present else "none detected"
