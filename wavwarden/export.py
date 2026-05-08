"""sfx export command — export the files table to CSV."""

import csv
from pathlib import Path

from wavwarden.db import get_connection


def export_csv(db_path: Path, output_path: Path) -> int:
    """Export files table to CSV. Returns row count."""
    conn = get_connection(db_path)
    rows = conn.execute(
        """
        SELECT path, filename, stem, extension, size_bytes, mtime, md5,
               sample_rate, bit_depth, channels, duration_s, subtype,
               has_bext, has_ixml, has_riff_info, has_adm, has_cue_markers,
               has_sampler, metadata_sources, is_ucs, scan_error, scanned_at
        FROM files
        ORDER BY path
        """
    ).fetchall()
    conn.close()

    if not rows:
        output_path.write_text("")
        return 0

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(rows[0].keys())
        writer.writerows(rows)

    return len(rows)
