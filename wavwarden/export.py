"""sfx export command — export the files table to CSV."""

import csv
import json
from pathlib import Path

from wavwarden.db import get_connection


def export_csv(db_path: Path, output_path: Path) -> int:
    """Export files table to CSV. Returns row count."""
    conn = get_connection(db_path)
    rows = conn.execute(
        """
        SELECT id, path, filename, stem, extension, size_bytes, mtime, md5,
               sample_rate, bit_depth, channels, duration_s, subtype,
               has_bext, has_ixml, has_riff_info, has_adm, has_cue_markers,
               has_sampler, metadata_sources, is_ucs, scan_error, scanned_at
        FROM files
        ORDER BY path
        """
    ).fetchall()
    tag_rows = conn.execute(
        """
        SELECT file_id, field, value, source, confidence
        FROM accepted_tags
        ORDER BY field, value, source
        """
    ).fetchall()
    conn.close()

    if not rows:
        output_path.write_text("")
        return 0

    tags_by_file: dict[int, list[dict]] = {}
    for tag in tag_rows:
        tags_by_file.setdefault(tag["file_id"], []).append(
            {
                "field": tag["field"],
                "value": tag["value"],
                "source": tag["source"],
                "confidence": tag["confidence"],
            }
        )

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        header = [key for key in rows[0].keys() if key != "id"] + ["accepted_tags"]
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        for row in rows:
            data = dict(row)
            data.pop("id", None)
            data["accepted_tags"] = json.dumps(tags_by_file.get(row["id"], []), sort_keys=True)
            writer.writerow(data)

    return len(rows)
